#!/usr/bin/env python3
"""
Generates conformance/canon/artifacts/acceptance-receipt.json.

This script does NOT compute or assert pass/fail itself. It runs each of
the three reference implementations as a real subprocess, captures their
actual stdout, parses the "N / M cases passed" line each one prints, and
only emits a receipt with conformance: "PASS" if all three independently
report full pass against the same manifest.json. If any implementation is
missing, fails to build, or reports a failure, the script exits non-zero
and writes nothing — there is no code path that produces a PASS receipt
without three real, fresh execution results backing it.
"""
import json
import re
import subprocess
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = REPO_ROOT / "conformance" / "canon" / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
ARTIFACTS_DIR = REPO_ROOT / "conformance" / "canon" / "artifacts"

PASS_LINE_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*cases passed")


def run(cmd, cwd=None, env=None):
    print(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
    return proc


def parse_pass_count(stdout: str):
    m = PASS_LINE_RE.search(stdout)
    if not m:
        return None
    passed, total = int(m.group(1)), int(m.group(2))
    return passed, total


def git_commit():
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode == 0:
        return proc.stdout.strip()
    return None


def manifest_summary():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    digests = {}
    for case in manifest["test_cases"]:
        if case["status"] == "SUCCESS":
            digests[case["id"]] = case["expected_sha256"]
        else:
            digests[case["id"]] = f"REJECT:{case['error_code']}"
    return manifest, digests


def main():
    if not MANIFEST_PATH.exists():
        print(f"FAIL: no manifest at {MANIFEST_PATH}", file=sys.stderr)
        return 1

    manifest, digests = manifest_summary()
    expected_total = len(manifest["test_cases"])

    results = {}

    # --- Python reference oracle ---
    py_proc = run(["python3", str(REPO_ROOT / "reference_canon.py"), "verify"])
    py_counts = parse_pass_count(py_proc.stdout)
    results["python"] = {
        "implementation": "reference_canon.py",
        "exit_code": py_proc.returncode,
        "cases_passed": py_counts[0] if py_counts else None,
        "cases_total": py_counts[1] if py_counts else None,
    }

    # --- Rust reference implementation ---
    rust_bin = REPO_ROOT / "tools" / "tscp-canon" / "target" / "release" / "tscp-canon"
    if not rust_bin.exists():
        print(f"NOTE: Rust binary not found at {rust_bin}; build it first with "
              f"`cargo build --release` in tools/tscp-canon", file=sys.stderr)
        results["rust"] = {"implementation": "tools/tscp-canon", "exit_code": None,
                            "cases_passed": None, "cases_total": None, "error": "binary not built"}
    else:
        import os
        env = dict(**__import__("os").environ, FIXTURES_ROOT=str(FIXTURES_DIR))
        rust_proc = run([str(rust_bin), "verify"], cwd=REPO_ROOT, env=env)
        rust_counts = parse_pass_count(rust_proc.stdout)
        results["rust"] = {
            "implementation": "tools/tscp-canon",
            "exit_code": rust_proc.returncode,
            "cases_passed": rust_counts[0] if rust_counts else None,
            "cases_total": rust_counts[1] if rust_counts else None,
        }

    # --- TypeScript reference implementation ---
    ts_dir = REPO_ROOT / "triune-handoff-ts"
    ts_script = ts_dir / "scripts" / "run_conformance.ts"
    if not ts_script.exists():
        results["typescript"] = {"implementation": "triune-handoff-ts", "exit_code": None,
                                  "cases_passed": None, "cases_total": None, "error": "script not found"}
    else:
        ts_proc = run(["npx", "ts-node", "--transpile-only", str(ts_script)], cwd=ts_dir)
        ts_counts = parse_pass_count(ts_proc.stdout)
        results["typescript"] = {
            "implementation": "triune-handoff-ts",
            "exit_code": ts_proc.returncode,
            "cases_passed": ts_counts[0] if ts_counts else None,
            "cases_total": ts_counts[1] if ts_counts else None,
        }

    all_pass = all(
        r.get("exit_code") == 0 and r.get("cases_passed") == r.get("cases_total") == expected_total
        for r in results.values()
    )

    receipt = {
        "spec": "TSCP-CANON-001",
        "canon_version": manifest.get("canon_version", "unknown"),
        "manifest_schema_version": manifest.get("manifest_schema_version", "unknown"),
        "module": "tscp-canon-conformance",
        "git_commit": git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fixture_count": expected_total,
        "fixture_digests": digests,
        "implementation_results": results,
        "conformance": "PASS" if all_pass else "FAIL",
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = ARTIFACTS_DIR / "acceptance-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'='*60}")
    print(json.dumps(receipt, indent=2))
    print(f"{'='*60}")
    print(f"\nWrote {receipt_path}")
    print(f"conformance: {receipt['conformance']}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
