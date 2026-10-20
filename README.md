# TSCP Canon

`tscp-canon` is the deterministic canonicalization and conformance component for TSCP.
It defines `TSCP-CANON-001`, a versioned canonical representation for hashing, receipts,
state roots, and proof-adjacent artifacts.

## Evidence surface

The repository contains:

- The protocol specification under `specs/protocol/`.
- A Python reference implementation in `reference_canon.py`.
- A Rust implementation under `tools/tscp-canon/`.
- A TypeScript handoff implementation under `triune-handoff-ts/`.
- Shared fixtures and expected outputs under `conformance/canon/fixtures/`.
- The acceptance receipt under `conformance/canon/artifacts/`.

The conformance receipt is an execution result for the listed fixtures. It is not a
formal proof of every downstream consumer and does not establish security of any
cryptographic protocol that uses the canonical bytes.

## Reproduce

From the repository root:

```bash
cargo build --release --manifest-path tools/tscp-canon/Cargo.toml
python3 reference_canon.py verify
python3 generate_acceptance_receipt.py
```

The acceptance script runs the Python, Rust, and TypeScript implementations against the
same manifest and writes a fresh receipt only from their observed outputs.

## License

Apache-2.0. See `LICENSE`.
