//! Library surface for the TSCP-CANON-001 reference implementation.
//!
//! The `tscp-canon` binary is a thin CLI over this module, so the
//! conformance suite in `tests/` can exercise the canonicalizer directly
//! instead of shelling out and parsing stdout.

pub mod canonical;
pub mod hash;
