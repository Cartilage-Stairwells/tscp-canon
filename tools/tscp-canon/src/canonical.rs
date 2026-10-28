//! Reference implementation of TSCP-CANON-001 v1.0 (Canonical JSON Profile).
//!
//! v1.1 of this tool adds: deterministic error codes/stages (spec §8) and
//! top-level type validation (§2.1), matching reference_canon.py exactly so
//! the two can be cross-validated case-by-case, including rejection cases.

use serde_json::Value;
use std::collections::BTreeMap;
use unicode_normalization::UnicodeNormalization;

pub const GENERATOR_NAME: &str = "tscp-canon";
pub const GENERATOR_VERSION: &str = "1.1.0";
pub const CANON_VERSION: &str = "1.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Validation,
    Normalization,
    Numeric,
}

impl Stage {
    pub fn as_str(&self) -> &'static str {
        match self {
            Stage::Validation => "VALIDATION",
            Stage::Normalization => "NORMALIZATION",
            Stage::Numeric => "NUMERIC",
        }
    }
}

#[derive(Debug)]
pub struct CanonError {
    pub code: &'static str,
    pub stage: Stage,
    pub spec_section: &'static str,
    pub message: String,
}

impl std::fmt::Display for CanonError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{} ({}): {}",
            self.code,
            self.stage.as_str(),
            self.message
        )
    }
}

impl std::error::Error for CanonError {}

fn err_toplevel_nonmap(actual_type: &str) -> CanonError {
    CanonError {
        code: "TSCP-CANON-TOPLEVEL-NONMAP",
        stage: Stage::Validation,
        spec_section: "§2.1",
        message: format!("top-level input must be a JSON object, got {actual_type}"),
    }
}

fn err_float_prohibited(text: &str) -> CanonError {
    CanonError {
        code: "TSCP-CANON-FLOAT-PROHIBITED",
        stage: Stage::Numeric,
        spec_section: "§3.1.3",
        message: format!("floats are prohibited in Protocol Objects: {text}"),
    }
}

fn err_key_collision(key: &str) -> CanonError {
    CanonError {
        code: "TSCP-CANON-KEY-COLLISION",
        stage: Stage::Normalization,
        spec_section: "§3.1.2",
        message: format!("duplicate key after NFC normalization: {key:?}"),
    }
}

fn nfc(s: &str) -> String {
    s.nfc().collect::<String>()
}

fn number_is_integer_literal(n: &serde_json::Number) -> bool {
    let text = n.to_string();
    !text.contains('.') && !text.contains('e') && !text.contains('E')
}

fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn validate_top_level(value: &Value) -> Result<(), CanonError> {
    match value {
        Value::Object(_) => Ok(()),
        other => Err(err_toplevel_nonmap(type_name(other))),
    }
}

fn normalize(value: &Value) -> Result<Value, CanonError> {
    match value {
        Value::Null => Ok(Value::Null),
        Value::Bool(b) => Ok(Value::Bool(*b)),
        Value::Number(n) => {
            if number_is_integer_literal(n) {
                Ok(Value::Number(n.clone()))
            } else {
                Err(err_float_prohibited(&n.to_string()))
            }
        }
        Value::String(s) => Ok(Value::String(nfc(s))),
        Value::Array(arr) => {
            let mut out = Vec::with_capacity(arr.len());
            for v in arr {
                out.push(normalize(v)?);
            }
            Ok(Value::Array(out))
        }
        Value::Object(map) => {
            let mut out: BTreeMap<String, Value> = BTreeMap::new();
            for (k, v) in map {
                let nk = nfc(k);
                let nv = normalize(v)?;
                if out.contains_key(&nk) {
                    return Err(err_key_collision(&nk));
                }
                out.insert(nk, nv);
            }
            let mut obj = serde_json::Map::new();
            for (k, v) in out {
                obj.insert(k, v);
            }
            Ok(Value::Object(obj))
        }
    }
}

fn serialize_string(s: &str) -> String {
    serde_json::to_string(s).expect("string serialization cannot fail")
}

fn serialize(value: &Value) -> Result<String, CanonError> {
    match value {
        Value::Null => Ok("null".to_string()),
        Value::Bool(b) => Ok(if *b {
            "true".to_string()
        } else {
            "false".to_string()
        }),
        Value::Number(n) => {
            if number_is_integer_literal(n) {
                Ok(n.to_string())
            } else {
                Err(err_float_prohibited(&n.to_string()))
            }
        }
        Value::String(s) => Ok(serialize_string(s)),
        Value::Array(arr) => {
            let parts: Result<Vec<String>, CanonError> = arr.iter().map(serialize).collect();
            Ok(format!("[{}]", parts?.join(",")))
        }
        Value::Object(map) => {
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            let mut parts = Vec::with_capacity(entries.len());
            for (k, v) in entries {
                parts.push(format!("{}:{}", serialize_string(k), serialize(v)?));
            }
            Ok(format!("{{{}}}", parts.join(",")))
        }
    }
}

/// Top-level entry point: validate + normalize + serialize to canonical UTF-8 bytes.
pub fn canonicalize_bytes(value: &Value) -> Result<Vec<u8>, CanonError> {
    validate_top_level(value)?;
    let normalized = normalize(value)?;
    let text = serialize(&normalized)?;
    Ok(text.into_bytes())
}
