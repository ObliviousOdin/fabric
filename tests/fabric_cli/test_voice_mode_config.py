from fabric_cli.config import DEFAULT_CONFIG


def test_voice_experience_defaults_are_profile_safe_and_non_secret():
    experience = DEFAULT_CONFIG["voice"]["experience"]

    assert experience == {
        "attitude": "profile_default",
        "presentation": "chat",
        "voice_ref": "profile_default",
    }
