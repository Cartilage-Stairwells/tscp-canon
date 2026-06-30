import * as fs from "fs";
import * as path from "path";
import { createHash } from "crypto";
import { canonicalize } from "../src/canonical";
import { CanonicalizationError } from "../src/errors";

const MANIFEST_PATH = path.resolve(__dirname, "../../../conformance/canon/fixtures/manifest.json");
const FIXTURES_DIR = path.dirname(MANIFEST_PATH);

interface ManifestCase {
  id: string;
  status: "SUCCESS" | "REJECT";
  input_file: string;
  expected_sha256?: string;
  expected_output_file?: string;
  error_code?: string;
  error_stage?: string;
}

interface Manifest {
  manifest_schema_version: string;
  canon_version: string;
  test_cases: ManifestCase[];
}

describe("TSCP-CANON-001 v1.0 conformance corpus", () => {
  const manifest: Manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8"));

  manifest.test_cases.forEach((testCase) => {
    it(`${testCase.id} (${testCase.status})`, () => {
      const inputPath = path.resolve(FIXTURES_DIR, testCase.input_file);
      const rawInput = fs.readFileSync(inputPath, "utf-8");

      if (testCase.status === "REJECT") {
        // The real canonicalize() must throw — no rule is reimplemented
        // here. We assert on the actual error it throws.
        let thrown: unknown = null;
        try {
          canonicalize(rawInput);
        } catch (e) {
          thrown = e;
        }

        expect(thrown).toBeInstanceOf(CanonicalizationError);
        const err = thrown as CanonicalizationError;
        expect(err.code).toBe(testCase.error_code);
        expect(err.stage).toBe(testCase.error_stage);
      } else {
        const resultBytes = canonicalize(rawInput);
        const computedHash = createHash("sha256").update(Buffer.from(resultBytes)).digest("hex");

        expect(computedHash).toBe(testCase.expected_sha256);

        if (testCase.expected_output_file) {
          const expectedBytes = fs.readFileSync(path.resolve(FIXTURES_DIR, testCase.expected_output_file));
          expect(Buffer.compare(Buffer.from(resultBytes), expectedBytes)).toBe(0);
        }
      }
    });
  });
});
