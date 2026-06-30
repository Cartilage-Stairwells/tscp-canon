// Error codes and stages MUST match TSCP-CANON-001 §8 exactly.
// Do not add, rename, or remove codes/stages here without a corresponding
// spec version bump — divergence here defeats the purpose of cross-language
// conformance (two implementations rejecting "for different reasons").

export type CanonicalStage =
  | "VALIDATION"
  | "NORMALIZATION"
  | "NUMERIC";

export type CanonicalErrorCode =
  | "TSCP-CANON-TOPLEVEL-NONMAP"   // §2.1 — VALIDATION
  | "TSCP-CANON-NON-STRING-KEY"    // §2   — VALIDATION
  | "TSCP-CANON-FLOAT-PROHIBITED"  // §3.1.3 — NUMERIC
  | "TSCP-CANON-KEY-COLLISION";    // §3.1.2 — NORMALIZATION

export class CanonicalizationError extends Error {
  constructor(
    public readonly code: CanonicalErrorCode,
    public readonly stage: CanonicalStage,
    message: string,
  ) {
    super(`[${stage}][${code}] ${message}`);
    this.name = "CanonicalizationError";
    Object.setPrototypeOf(this, CanonicalizationError.prototype);
  }
}
