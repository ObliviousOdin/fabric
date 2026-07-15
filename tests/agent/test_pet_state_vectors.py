"""Conformance vectors for derive_pet_state, shared with non-Python mirrors.

`agent/pet/state.py` is the canonical implementation of the activity →
animation-state priority ladder, but it is mirrored in TypeScript
(`apps/desktop/src/store/pet.ts`) and Rust (`apps/companion`). The JSON file
under `apps/companion/conformance/` enumerates every combination of the seven
input signals with the state the canonical implementation resolves; each
mirror asserts the same file, so a change to the ladder that forgets to update
a mirror (or the vectors) fails somewhere loudly instead of drifting silently.

If the ladder changes intentionally: update `derive_pet_state`, regenerate the
vector file by enumerating `itertools.product` over the signals (see the
file's `$comment`), and update every mirror in the same change.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from agent.pet.state import derive_pet_state

VECTORS_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "companion"
    / "conformance"
    / "derive_pet_state.json"
)


def _load():
    return json.loads(VECTORS_PATH.read_text())


def test_vectors_are_exhaustive():
    data = _load()
    assert len(data["vectors"]) == 2 ** len(data["signals"])
    seen = {tuple(sorted(v["signals"].items())) for v in data["vectors"]}
    assert len(seen) == len(data["vectors"]), "duplicate signal combinations"


def test_vectors_match_canonical_implementation():
    data = _load()
    for vector in data["vectors"]:
        got = derive_pet_state(**vector["signals"])
        assert got.value == vector["expect"], (
            f"vectors out of date for signals {vector['signals']}: "
            f"canonical={got.value!r} vectors={vector['expect']!r} — "
            "regenerate apps/companion/conformance/derive_pet_state.json"
        )


def test_signal_list_matches_signature():
    data = _load()
    for signals in itertools.product([False, True], repeat=len(data["signals"])):
        # Raises TypeError if the vector file's signal names ever diverge
        # from the canonical keyword-only signature.
        derive_pet_state(**dict(zip(data["signals"], signals)))
