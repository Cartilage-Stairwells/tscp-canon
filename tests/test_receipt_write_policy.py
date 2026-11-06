#!/usr/bin/env python3
"""Regression tests for the acceptance-receipt write policy.

Bug this pins down: `generate_acceptance_receipt.py` claimed in its docstring
that a failing run "exits non-zero and writes nothing", but it wrote
`conformance/canon/artifacts/acceptance-receipt.json` unconditionally before
returning non-zero. On a host missing the Rust or TypeScript toolchain (the
README tells readers to run exactly this command) a committed PASS receipt was
replaced by a FAIL, i.e. a reader's evidence was destroyed by a report about
the author's machine.

The tests below are hermetic: they build a sandbox copy of the repository and
substitute tiny stand-ins for the three implementation legs, so they need no
cargo, no node and no network. They exercise BOTH paths:

  * failure path  -> the committed receipt must be byte-identical afterwards
  * success path  -> the receipt must be written and reflect the fresh results

Both are asserted, because a passing failure-path test on its own says nothing
about whether the success path still works.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = "generate_acceptance_receipt.py"
RECEIPT_REL = Path("conformance") / "canon" / "artifacts" / "acceptance-receipt.json"
FAILED_REL = Path("conformance") / "canon" / "artifacts" / "acceptance-receipt.failed.json"
RUST_BIN_REL = Path("tools") / "tscp-canon" / "target" / "release" / "tscp-canon"
TS_SCRIPT_REL = Path("triune-handoff-ts") / "scripts" / "run_conformance.ts"


# --------------------------------------------------------------------------
# sandbox construction
# --------------------------------------------------------------------------
def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_sandbox(tmp_path: Path, *, python_passed: int, total: int = 15,
                  rust: str = "stub", ts: str = "stub") -> Path:
    """Copy the minimum tree the generator needs, then control the three legs.

    python: rewritten to a stub that prints "<python_passed> / <total> cases passed"
    rust:   "stub" -> executable at the expected path printing full pass
            "missing" -> nothing on disk
    ts:     "stub" -> a fake `npx` earlier on PATH printing full pass
            "missing" -> the script is deleted so the leg reports "script not found"
    """
    box = tmp_path / "repo"
    box.mkdir()

    shutil.copy2(REPO_ROOT / GENERATOR, box / GENERATOR)
    (box / "conformance").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "conformance" / "canon", box / "conformance" / "canon")
    (box / "triune-handoff-ts" / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / TS_SCRIPT_REL, box / TS_SCRIPT_REL)

    # The sandbox must start from the committed tree, not from whatever a previous
    # failing run left behind in the developer's working copy.
    for leftover in ((box / FAILED_REL), (box / RECEIPT_REL).with_name(RECEIPT_REL.name + ".tmp")):
        if leftover.exists():
            leftover.unlink()

    # Python leg stub (replaces the real oracle on purpose).
    (box / "reference_canon.py").write_text(
        "import sys\n"
        f"print('{python_passed} / {total} cases passed')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    if rust == "stub":
        _write_exec(box / RUST_BIN_REL,
                    "#!/bin/sh\necho '%d / %d cases passed'\nexit 0\n" % (total, total))
    else:
        assert not (box / RUST_BIN_REL).exists()

    if ts == "missing":
        (box / TS_SCRIPT_REL).unlink()

    return box


def run_generator(box: Path, *, fake_npx: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if fake_npx:
        shim_dir = box / "_pathshim"
        _write_exec(shim_dir / "npx",
                    "#!/bin/sh\necho ' 15 / 15 cases passed'\nexit 0\n")
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(box / GENERATOR)],
        cwd=box, env=env, capture_output=True, text=True, timeout=120,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_no_temp_files(box: Path) -> None:
    leftovers = sorted(
        p.name for p in (box / RECEIPT_REL).parent.iterdir() if p.name.endswith(".tmp")
    )
    assert leftovers == [], f"temporary files left behind: {leftovers}"


# --------------------------------------------------------------------------
# failure path
# --------------------------------------------------------------------------
def test_missing_toolchains_does_not_overwrite_committed_receipt(tmp_path):
    """The exact reproduction: Rust + TypeScript legs unavailable."""
    box = build_sandbox(tmp_path, python_passed=15, rust="stub", ts="stub")
    # Python passes fully; the other two legs cannot run at all.
    (box / RUST_BIN_REL).unlink()
    (box / TS_SCRIPT_REL).unlink()

    receipt = box / RECEIPT_REL
    before_bytes = receipt.read_bytes()
    before_hash = sha256(receipt)
    assert json.loads(before_bytes)["conformance"] == "PASS", "fixture must start as a PASS"

    proc = run_generator(box, fake_npx=False)

    assert proc.returncode != 0, "a run that is not a full pass must exit non-zero"
    assert sha256(receipt) == before_hash, "committed receipt was modified by a failing run"
    assert receipt.read_bytes() == before_bytes, "committed receipt bytes changed"
    assert json.loads(receipt.read_text())["conformance"] == "PASS"
    assert "left intact" in proc.stderr, proc.stderr
    assert "FAILED run" in proc.stderr
    assert_no_temp_files(box)


def test_failing_implementation_does_not_overwrite_committed_receipt(tmp_path):
    """An implementation that builds but reports a short count is also a failure."""
    box = build_sandbox(tmp_path, python_passed=14, rust="stub", ts="stub")
    receipt = box / RECEIPT_REL
    before_hash = sha256(receipt)

    proc = run_generator(box, fake_npx=True)

    assert proc.returncode != 0
    assert sha256(receipt) == before_hash
    assert json.loads(receipt.read_text())["conformance"] == "PASS"
    assert_no_temp_files(box)


def test_failing_run_still_records_its_result_somewhere(tmp_path):
    """Failing runs must not be silently swallowed: they go to a separate path."""
    box = build_sandbox(tmp_path, python_passed=15, rust="missing", ts="missing")
    receipt = box / RECEIPT_REL
    before_hash = sha256(receipt)

    proc = run_generator(box, fake_npx=False)
    assert proc.returncode != 0
    assert sha256(receipt) == before_hash

    failed = box / FAILED_REL
    assert failed.exists(), "failing run left no diagnostic receipt"
    payload = json.loads(failed.read_text())
    assert payload["conformance"] == "FAIL"
    assert payload["implementation_results"]["rust"]["cases_passed"] is None
    # The diagnostic path is separate from the evidence path.
    assert failed != receipt
    assert_no_temp_files(box)


# --------------------------------------------------------------------------
# success path
# --------------------------------------------------------------------------
def test_success_path_writes_the_receipt(tmp_path):
    """A full pass must still produce the artifact — the fix must not freeze it."""
    box = build_sandbox(tmp_path, python_passed=15, rust="stub", ts="stub")
    receipt = box / RECEIPT_REL
    before_hash = sha256(receipt)

    proc = run_generator(box, fake_npx=True)

    assert proc.returncode == 0, proc.stderr
    assert sha256(receipt) != before_hash, "successful run did not refresh the receipt"

    payload = json.loads(receipt.read_text())
    assert payload["conformance"] == "PASS"
    assert payload["fixture_count"] == 15
    for leg in ("python", "rust", "typescript"):
        result = payload["implementation_results"][leg]
        assert result["exit_code"] == 0, leg
        assert result["cases_passed"] == result["cases_total"] == 15, leg
    assert not (box / FAILED_REL).exists(), "successful run wrote a diagnostic FAIL receipt"
    assert_no_temp_files(box)


def test_success_then_failure_orders_correctly(tmp_path):
    """Real-world sequence: a good run, then a broken-environment run."""
    box = build_sandbox(tmp_path, python_passed=15, rust="stub", ts="stub")

    first = run_generator(box, fake_npx=True)
    assert first.returncode == 0, first.stderr
    receipt = box / RECEIPT_REL
    pass_bytes = receipt.read_bytes()
    pass_hash = sha256(receipt)

    # Now the environment degrades the way it does on a laptop without cargo/node.
    (box / RUST_BIN_REL).unlink()
    (box / TS_SCRIPT_REL).unlink()

    second = run_generator(box, fake_npx=False)
    assert second.returncode != 0
    assert sha256(receipt) == pass_hash
    assert receipt.read_bytes() == pass_bytes
    assert json.loads(receipt.read_text())["conformance"] == "PASS"
    assert_no_temp_files(box)


# --------------------------------------------------------------------------
# docstring contract
# --------------------------------------------------------------------------
def test_docstring_matches_behaviour():
    """The docstring is the claim; keep it from drifting back to a false one."""
    text = (REPO_ROOT / GENERATOR).read_text(encoding="utf-8")
    doc = text.split('"""')[1]
    lowered = doc.lower()
    assert "writes nothing" not in lowered, "docstring still claims it writes nothing"
    for token in ("temporary file", "on fail", "acceptance-receipt.failed.json", "exit status"):
        assert token in lowered, f"docstring does not document {token!r}"


def test_fail_run_writes_only_the_diagnostic_file(tmp_path):
    """A failing run may write the diagnostic, and must write nothing else there.

    This pins the exact shape of the FAIL path: exactly one new file in the
    artifacts directory, and it is not the receipt of record. Without this, a
    future "fix" could quietly start writing a second file beside the evidence.
    """
    box = build_sandbox(tmp_path, python_passed=15, rust="missing", ts="missing")
    artifacts = (box / RECEIPT_REL).parent
    before = {p.name: sha256(p) for p in artifacts.iterdir() if p.is_file()}

    proc = run_generator(box, fake_npx=False)
    assert proc.returncode != 0

    after = {p.name: sha256(p) for p in artifacts.iterdir() if p.is_file()}
    changed = {n for n in before if after.get(n) != before[n]}
    added = set(after) - set(before)
    assert changed == set(), f"existing artifact files were modified: {sorted(changed)}"
    assert added == {FAILED_REL.name}, f"unexpected files written on FAIL: {sorted(added)}"
    assert_no_temp_files(box)


def test_docstring_does_not_overclaim_what_the_fail_path_touches():
    """The docstring is a claim about behaviour; it must not contradict the code.

    Regression on a real defect: the write-policy docstring said "nothing under
    ``conformance/canon/artifacts/`` is written or replaced" on FAIL, while the
    FAIL branch writes acceptance-receipt.failed.json in exactly that directory.
    A docstring that overclaims is how the original "writes nothing" bug survived.
    """
    text = (REPO_ROOT / GENERATOR).read_text(encoding="utf-8")
    doc = text.split('"""')[1].lower()
    assert "nothing under ``conformance/canon/artifacts/``" not in doc, (
        "docstring claims nothing is written under the artifacts directory, "
        "but the FAIL branch writes acceptance-receipt.failed.json there"
    )
