from agent.skill_distribution_policy import (
    ENFORCE_ALL,
    ENFORCE_LEARNED,
    OBSERVE,
    load_distribution_policy,
)


def test_distribution_policy_defaults_invalid_or_missing_values_to_observe() -> None:
    assert load_distribution_policy({}).mode == OBSERVE
    assert (
        load_distribution_policy({"skills": {"distribution": {"mode": "future"}}}).mode
        == OBSERVE
    )


def test_distribution_policy_enforcement_cohorts_are_explicit() -> None:
    learned = load_distribution_policy({
        "skills": {"distribution": {"mode": ENFORCE_LEARNED}}
    })
    assert learned.requires_signed_release(provenance="learned") is True
    assert learned.requires_signed_release(provenance="background_review") is True
    assert learned.requires_signed_release(provenance="hub") is False

    all_policy = load_distribution_policy({
        "skills": {"distribution": {"mode": ENFORCE_ALL}}
    })
    assert all_policy.requires_signed_release(provenance="hub") is True
    assert all_policy.requires_signed_release(provenance="bundled") is True


def test_observe_mode_never_claims_enforcement() -> None:
    policy = load_distribution_policy({"skills": {"distribution": {"mode": OBSERVE}}})
    assert policy.requires_signed_release(provenance="learned") is False
    assert policy.requires_signed_release(provenance="hub") is False
