//! Assert the Rust `derive_pet_state` mirror against the shared conformance
//! vectors generated from the canonical Python implementation
//! (`agent/pet/state.py`). The same file is asserted from Python by
//! `tests/agent/test_pet_state_vectors.py`.

use fabric_companion_core::state::{derive_pet_state, ActivitySignals, PetState};
use serde::Deserialize;

#[derive(Deserialize)]
struct VectorFile {
    signals: Vec<String>,
    vectors: Vec<Vector>,
}

#[derive(Deserialize)]
struct Vector {
    signals: ActivitySignals,
    expect: PetState,
}

const VECTORS: &str = include_str!("../../../conformance/derive_pet_state.json");

#[test]
fn matches_canonical_python_vectors() {
    let file: VectorFile = serde_json::from_str(VECTORS).expect("vectors parse");

    // Exhaustive coverage: one vector per combination of the declared signals.
    assert_eq!(
        file.vectors.len(),
        1 << file.signals.len(),
        "vector file must enumerate every signal combination"
    );

    for (i, v) in file.vectors.iter().enumerate() {
        assert_eq!(
            derive_pet_state(v.signals),
            v.expect,
            "vector {i} diverged: signals {:?}",
            v.signals
        );
    }
}

#[test]
fn vector_signal_names_match_struct_fields() {
    let file: VectorFile = serde_json::from_str(VECTORS).expect("vectors parse");
    let expected = [
        "busy",
        "awaiting_input",
        "error",
        "celebrate",
        "just_completed",
        "tool_running",
        "reasoning",
    ];
    assert_eq!(
        file.signals, expected,
        "signal list changed — update ActivitySignals and regenerate vectors"
    );
}
