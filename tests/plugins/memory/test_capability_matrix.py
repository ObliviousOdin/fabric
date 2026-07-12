import pytest

from plugins.memory import load_memory_provider


EXPECTED = {
    "byterover": {
        "supported": {"recall", "capture", "store", "search", "health"},
        "unsupported": {
            "list", "edit", "delete", "export", "import", "provenance",
            "deletion_guarantee",
        },
    },
    "hindsight": {
        "supported": {"recall", "capture", "store", "search", "local_only"},
        "unsupported": {
            "list", "edit", "delete", "export", "import", "provenance",
            "health", "deletion_guarantee",
        },
    },
    "holographic": {
        "supported": {
            "recall", "capture", "store", "search", "list", "edit", "delete",
            "local_only",
        },
        "unsupported": {"export", "import", "health", "deletion_guarantee"},
    },
    "honcho": {
        "supported": {"recall", "capture", "store", "search", "edit", "delete"},
        "unsupported": {
            "list", "export", "import", "backup", "provenance", "health",
            "deletion_guarantee",
        },
    },
    "mem0": {
        "supported": {"recall", "capture", "store", "search", "edit", "delete", "local_only"},
        "unsupported": {
            "list", "export", "import", "backup", "health", "deletion_guarantee",
        },
    },
    "openviking": {
        "supported": {
            "recall", "capture", "store", "search", "list", "delete", "provenance", "health",
        },
        "unsupported": {"edit", "export", "import", "backup", "deletion_guarantee"},
    },
    "retaindb": {
        "supported": {"recall", "capture", "store", "search", "delete"},
        "unsupported": {
            "list", "edit", "export", "import", "backup", "health", "local_only",
            "deletion_guarantee",
        },
    },
    "supermemory": {
        "supported": {"recall", "capture", "store", "search", "delete", "health"},
        "unsupported": {
            "list", "edit", "export", "import", "backup", "local_only",
            "deletion_guarantee",
        },
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_bundled_memory_provider_capability_contract(name):
    provider = load_memory_provider(name)
    assert provider is not None

    capabilities = provider.get_capabilities().as_dict()
    expected = EXPECTED[name]
    for operation in expected["supported"]:
        assert capabilities[operation] == "supported"
    for operation in expected["unsupported"]:
        assert capabilities[operation] == "unsupported"
    for operation in set(capabilities) - expected["supported"] - expected["unsupported"]:
        assert capabilities[operation] == "unknown"

    # Portable round-trip transfer and strong erasure are not implemented by
    # any bundled adapter; never let marketing-like capability drift claim them.
    assert capabilities["export"] == "unsupported"
    assert capabilities["import"] == "unsupported"
    assert capabilities["deletion_guarantee"] == "unsupported"
