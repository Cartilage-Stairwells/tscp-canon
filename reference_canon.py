#!/usr/bin/env python3
"""
Independent reference implementation of TSCP-CANON-001 v1.0.

v1.1 of this generator adds: deterministic error codes/stages (spec §8),
top-level type validation (§2.1), and full corpus provenance (§9).

Used ONLY to generate the golden corpus (conformance/canon/fixtures/) with
real, computed digests. Written independently from the Rust implementation
(tools/tscp-canon) so the two can cross-validate.
"""
import json
import hashlib
import unicodedata
from pathlib import Path

GENERATOR_NAME = "reference_canon.py"
GENERATOR_VERSION = "1.1.0"
CANON_VERSION = "1.0"


class CanonError(Exception):
    def __init__(self, message, code, stage, spec_section):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.spec_section = spec_section


def validate_top_level(value):
    if not isinstance(value, dict):
        raise CanonError(
            f"top-level input must be a JSON object, got {type(value).__name__}",
            code="TSCP-CANON-TOPLEVEL-NONMAP",
            stage="VALIDATION",
            spec_section="§2.1",
        )


def normalize(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise CanonError(
            f"floats are prohibited in Protocol Objects: {value!r}",
            code="TSCP-CANON-FLOAT-PROHIBITED",
            stage="NUMERIC",
            spec_section="§3.1.3",
        )
    if isinstance(value, int):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonError(
                    f"non-string key: {k!r}",
                    code="TSCP-CANON-NON-STRING-KEY",
                    stage="VALIDATION",
                    spec_section="§2",
                )
            nk = unicodedata.normalize("NFC", k)
            if nk in out:
                raise CanonError(
                    f"duplicate key after NFC normalization: {nk!r}",
                    code="TSCP-CANON-KEY-COLLISION",
                    stage="NORMALIZATION",
                    spec_section="§3.1.2",
                )
            out[nk] = normalize(v)
        return out
    raise CanonError(f"unsupported type: {type(value)}", code="TSCP-CANON-UNSUPPORTED-TYPE",
                      stage="VALIDATION", spec_section="§2")


def serialize_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def serialize(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return serialize_string(value)
    if isinstance(value, list):
        return "[" + ",".join(serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0])
        body = ",".join(f"{serialize_string(k)}:{serialize(v)}" for k, v in items)
        return "{" + body + "}"
    raise CanonError(f"unsupported type at serialize: {type(value)}",
                      code="TSCP-CANON-UNSUPPORTED-TYPE", stage="VALIDATION", spec_section="§2")


def canonicalize_bytes(obj) -> bytes:
    validate_top_level(obj)
    normalized = normalize(obj)
    text = serialize(normalized)
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    fixtures_dir = Path(__file__).resolve().parent / "conformance" / "canon" / "fixtures"
    inputs_dir = fixtures_dir / "inputs"
    expected_dir = fixtures_dir / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_schema_version": "1.1",
        "canon_version": CANON_VERSION,
        "hash_algorithm": "sha256",
        "generated_by": f"{GENERATOR_NAME} v{GENERATOR_VERSION} (Python, independent oracle)",
        "test_cases": [],
    }

    reject_prefixes = ("malformed_", "010_reject", "011_reject")

    for input_path in sorted(inputs_dir.glob("*.json")):
        case_id = input_path.stem
        raw_text = input_path.read_text(encoding="utf-8")
        expect_reject = input_path.name.startswith(reject_prefixes)

        obj = json.loads(raw_text)

        if expect_reject:
            try:
                canonicalize_bytes(obj)
            except CanonError as e:
                manifest["test_cases"].append({
                    "id": case_id,
                    "status": "REJECT",
                    "input_file": f"inputs/{input_path.name}",
                    "error_code": e.code,
                    "error_stage": e.stage,
                    "spec": f"TSCP-CANON-001 {e.spec_section}",
                    "actual_error_message": str(e),
                })
                print(f"[REJECT OK] {case_id}: {e.code} ({e.stage}) - {e}")
                continue
            else:
                raise SystemExit(f"[FAIL] {case_id} should have raised CanonError but did not")

        canon_bytes = canonicalize_bytes(obj)
        digest = sha256_hex(canon_bytes)

        out_bin = expected_dir / f"{case_id}.canonical.bin"
        out_bin.write_bytes(canon_bytes)
        out_sha = expected_dir / f"{case_id}.sha256"
        out_sha.write_text(digest + "\n", encoding="utf-8")

        manifest["test_cases"].append({
            "id": case_id,
            "status": "SUCCESS",
            "input_file": f"inputs/{input_path.name}",
            "expected_output_file": f"expected/{case_id}.canonical.bin",
            "expected_sha256": digest,
            "generated_by": f"{GENERATOR_NAME} v{GENERATOR_VERSION}",
            "canon_version": CANON_VERSION,
        })
        print(f"[OK] {case_id}: sha256={digest}  bytes={canon_bytes!r}")

    manifest_path = fixtures_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote manifest: {manifest_path}")


def verify():
    fixtures_dir = Path(__file__).resolve().parent / "conformance" / "canon" / "fixtures"
    manifest_path = fixtures_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    failures = 0
    total = 0

    for case in manifest["test_cases"]:
        total += 1
        cid = case["id"]
        input_path = fixtures_dir / case["input_file"]
        obj = json.loads(input_path.read_text(encoding="utf-8"))

        if case["status"] == "REJECT":
            try:
                canonicalize_bytes(obj)
            except CanonError as e:
                if e.code == case["error_code"] and e.stage == case["error_stage"]:
                    print(f"[OK]   {cid}: {e.code} ({e.stage})")
                else:
                    print(f"[FAIL] {cid}: wrong reason. expected {case['error_code']}/{case['error_stage']}, got {e.code}/{e.stage}")
                    failures += 1
            else:
                print(f"[FAIL] {cid}: expected rejection ({case['error_code']}), but succeeded")
                failures += 1
        else:
            try:
                canon_bytes = canonicalize_bytes(obj)
            except CanonError as e:
                print(f"[FAIL] {cid}: canonicalization errored unexpectedly: {e}")
                failures += 1
                continue
            digest = sha256_hex(canon_bytes)
            if digest == case["expected_sha256"]:
                print(f"[OK]   {cid}: sha256={digest}")
            else:
                print(f"[FAIL] {cid}: digest mismatch\n  expected: {case['expected_sha256']}\n  actual:   {digest}")
                failures += 1

    print(f"\n{total - failures} / {total} cases passed")
    return failures == 0


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "generate"
    if mode == "verify":
        ok = verify()
        sys.exit(0 if ok else 1)
    else:
        main()
