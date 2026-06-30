import * as fs from "fs";
import * as path from "path";
import { createHash } from "crypto";
import { canonicalize } from "../src/canonical";
import { CanonicalizationError } from "../src/errors";

const MANIFEST_PATH = path.resolve(__dirname, "../../conformance/canon/fixtures/manifest.json");
const FIXTURES_DIR = path.dirname(MANIFEST_PATH);

const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8"));

let failures = 0;
let total = 0;

for (const tc of manifest.test_cases) {
  total++;
  const inputPath = path.resolve(FIXTURES_DIR, tc.input_file);
  const rawInput = fs.readFileSync(inputPath, "utf-8");

  if (tc.status === "REJECT") {
    let thrown: any = null;
    try {
      canonicalize(rawInput);
    } catch (e) {
      thrown = e;
    }
    if (!(thrown instanceof CanonicalizationError)) {
      console.error(`[FAIL] ${tc.id}: expected rejection (${tc.error_code}), got ${thrown ? thrown.constructor.name : "no throw"}`);
      failures++;
      continue;
    }
    if (thrown.code === tc.error_code && thrown.stage === tc.error_stage) {
      console.log(`[OK]   ${tc.id}: ${thrown.code} (${thrown.stage})`);
    } else {
      console.error(`[FAIL] ${tc.id}: wrong reason. expected ${tc.error_code}/${tc.error_stage}, got ${thrown.code}/${thrown.stage}`);
      failures++;
    }
  } else {
    try {
      const bytes = canonicalize(rawInput);
      const digest = createHash("sha256").update(Buffer.from(bytes)).digest("hex");
      if (digest === tc.expected_sha256) {
        console.log(`[OK]   ${tc.id}: sha256=${digest}`);
      } else {
        console.error(`[FAIL] ${tc.id}: digest mismatch\n  expected: ${tc.expected_sha256}\n  actual:   ${digest}\n  bytes:    ${Buffer.from(bytes).toString("utf-8")}`);
        failures++;
      }
    } catch (e: any) {
      console.error(`[FAIL] ${tc.id}: unexpected error: ${e.message}`);
      failures++;
    }
  }
}

console.log(`\n${total - failures} / ${total} cases passed`);
process.exit(failures === 0 ? 0 : 1);
