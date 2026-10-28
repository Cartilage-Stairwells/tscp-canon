use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;
use tscp_canon::canonical::{canonicalize_bytes, CANON_VERSION, GENERATOR_NAME, GENERATOR_VERSION};
use tscp_canon::hash::sha256_hex;

fn fixtures_root() -> PathBuf {
    if let Ok(p) = std::env::var("FIXTURES_ROOT") {
        PathBuf::from(p)
    } else {
        PathBuf::from("conformance/canon/fixtures")
    }
}

fn verify() -> ExitCode {
    let root = fixtures_root();
    let manifest_path = root.join("manifest.json");
    let manifest_text = match fs::read_to_string(&manifest_path) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("FAIL: cannot read manifest at {:?}: {e}", manifest_path);
            return ExitCode::FAILURE;
        }
    };
    let manifest: Value =
        serde_json::from_str(&manifest_text).expect("manifest must be valid JSON");
    let cases = manifest["test_cases"]
        .as_array()
        .expect("test_cases must be an array");

    let mut failures = 0usize;
    let mut total = 0usize;

    for case in cases {
        total += 1;
        let id = case["id"].as_str().unwrap_or("<unknown>");
        let status = case["status"].as_str().unwrap_or("SUCCESS");
        let input_file = case["input_file"].as_str().expect("input_file required");
        let input_path = root.join(input_file);
        let input_text = fs::read_to_string(&input_path)
            .unwrap_or_else(|e| panic!("cannot read input {:?}: {e}", input_path));
        let input_value: Value = serde_json::from_str(&input_text)
            .unwrap_or_else(|e| panic!("bad JSON in {:?}: {e}", input_path));

        match status {
            "REJECT" => {
                let expected_code = case["error_code"]
                    .as_str()
                    .expect("error_code required for REJECT case");
                let expected_stage = case["error_stage"]
                    .as_str()
                    .expect("error_stage required for REJECT case");
                match canonicalize_bytes(&input_value) {
                    Ok(_) => {
                        eprintln!("[FAIL] {id}: expected rejection ({expected_code}), but canonicalization SUCCEEDED");
                        failures += 1;
                    }
                    Err(e) => {
                        if e.code == expected_code && e.stage.as_str() == expected_stage {
                            println!("[OK]   {id}: {} ({})", e.code, e.stage.as_str());
                        } else {
                            eprintln!(
                                "[FAIL] {id}: rejected, but for the wrong reason\n  expected: {expected_code} / {expected_stage}\n  actual:   {} / {}",
                                e.code, e.stage.as_str()
                            );
                            failures += 1;
                        }
                    }
                }
            }
            _ => {
                let expected_sha = case["expected_sha256"]
                    .as_str()
                    .expect("expected_sha256 required");
                match canonicalize_bytes(&input_value) {
                    Err(e) => {
                        eprintln!("[FAIL] {id}: canonicalization errored unexpectedly: {e}");
                        failures += 1;
                    }
                    Ok(bytes) => {
                        let actual_sha = sha256_hex(&bytes);
                        if actual_sha == expected_sha {
                            println!("[OK]   {id}: sha256={actual_sha}");
                        } else {
                            eprintln!(
                                "[FAIL] {id}: digest mismatch\n  expected: {expected_sha}\n  actual:   {actual_sha}\n  bytes:    {:?}",
                                String::from_utf8_lossy(&bytes)
                            );
                            failures += 1;
                        }
                    }
                }
            }
        }
    }

    println!("\n{} / {} cases passed", total - failures, total);
    if failures == 0 {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn generate() -> ExitCode {
    let root = fixtures_root();
    let inputs_dir = root.join("inputs");
    let expected_dir = root.join("expected");
    fs::create_dir_all(&expected_dir).expect("cannot create expected dir");

    let mut entries: Vec<PathBuf> = fs::read_dir(&inputs_dir)
        .expect("cannot read inputs dir")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map(|x| x == "json").unwrap_or(false))
        .collect();
    entries.sort();

    let mut test_cases = Vec::new();

    for input_path in entries {
        let id = input_path
            .file_stem()
            .unwrap()
            .to_string_lossy()
            .to_string();
        let raw = fs::read_to_string(&input_path).expect("read input");
        let value: Value = serde_json::from_str(&raw).expect("parse input json");
        let file_name = input_path
            .file_name()
            .unwrap()
            .to_string_lossy()
            .to_string();

        let expect_reject = file_name.starts_with("malformed_")
            || file_name.starts_with("010_reject")
            || file_name.starts_with("011_reject");

        match canonicalize_bytes(&value) {
            Ok(bytes) => {
                if expect_reject {
                    eprintln!("[FAIL] {id}: expected a REJECT case but canonicalization succeeded");
                    return ExitCode::FAILURE;
                }
                let digest = sha256_hex(&bytes);
                let bin_path = expected_dir.join(format!("{id}.canonical.bin"));
                fs::write(&bin_path, &bytes).expect("write canonical bytes");
                let sha_path = expected_dir.join(format!("{id}.sha256"));
                fs::write(&sha_path, format!("{digest}\n")).expect("write sha256 file");
                println!("[OK] {id}: sha256={digest}");
                test_cases.push(serde_json::json!({
                    "id": id,
                    "status": "SUCCESS",
                    "input_file": format!("inputs/{file_name}"),
                    "expected_output_file": format!("expected/{id}.canonical.bin"),
                    "expected_sha256": digest,
                    "generated_by": format!("{GENERATOR_NAME} v{GENERATOR_VERSION}"),
                    "canon_version": CANON_VERSION,
                }));
            }
            Err(e) => {
                if !expect_reject {
                    eprintln!("[FAIL] {id}: unexpected canonicalization error: {e}");
                    return ExitCode::FAILURE;
                }
                println!("[REJECT OK] {id}: {} ({})", e.code, e.stage.as_str());
                test_cases.push(serde_json::json!({
                    "id": id,
                    "status": "REJECT",
                    "input_file": format!("inputs/{file_name}"),
                    "error_code": e.code,
                    "error_stage": e.stage.as_str(),
                    "spec": format!("TSCP-CANON-001 {}", e.spec_section),
                    "actual_error_message": e.message,
                }));
            }
        }
    }

    let manifest = serde_json::json!({
        "manifest_schema_version": "1.1",
        "canon_version": CANON_VERSION,
        "hash_algorithm": "sha256",
        "generated_by": format!("{GENERATOR_NAME} v{GENERATOR_VERSION} (Rust, independent oracle)"),
        "test_cases": test_cases,
    });
    let manifest_path = root.join("manifest.rust.json");
    fs::write(
        &manifest_path,
        serde_json::to_string_pretty(&manifest).unwrap() + "\n",
    )
    .expect("write manifest");
    println!("\nWrote {:?}", manifest_path);
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(|s| s.as_str()).unwrap_or("verify");
    match mode {
        "verify" => verify(),
        "generate" => generate(),
        other => {
            eprintln!("unknown mode {other:?}; use 'verify' or 'generate'");
            ExitCode::FAILURE
        }
    }
}
