"""Behavior contracts for quarantined background skill learning."""

import json

from agent.background_review import (
    _COMBINED_REVIEW_PROMPT,
    _SKILL_REVIEW_PROMPT,
    summarize_background_review_actions,
)


def test_review_prompts_explain_draft_governance():
    for prompt in (_SKILL_REVIEW_PROMPT, _COMBINED_REVIEW_PROMPT):
        low = prompt.lower()
        assert "quarantined" in low
        assert "/skills approve <id>" in prompt
        assert "never as 'active skill updated'" in low


def test_review_prompts_require_evidence_and_allow_noop():
    for prompt in (_SKILL_REVIEW_PROMPT, _COMBINED_REVIEW_PROMPT):
        low = prompt.lower()
        assert "a no-op is normal and correct" in low
        assert "durable, reusable" in low
        assert "missed learning opportunity" not in low
        assert "most sessions produce" not in low


def test_staged_skill_result_is_not_reported_as_active_update():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "skill_manage",
                        "arguments": json.dumps(
                            {"action": "create", "name": "draft-skill"}
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": json.dumps(
                {
                    "success": True,
                    "staged": True,
                    "pending_id": "abc12345",
                    "gist": "create 'draft-skill' — evidence workflow",
                    "message": "Saved as a quarantined skill draft.",
                }
            ),
        },
    ]

    actions = summarize_background_review_actions(messages, [])

    assert actions == [
        "📝 Skill draft staged for approval: "
        "create 'draft-skill' — evidence workflow [abc12345]"
    ]
