"""Closed capability events from host producers through the Journey observer."""

from __future__ import annotations

import contextlib
import copy
import json
from datetime import datetime, timezone

import pytest

from cron import jobs as cron_jobs
from fabric_cli import plugins as plugin_runtime
from fabric_cli.config import DEFAULT_CONFIG
from plugins.achievements import observer
from plugins.achievements.events import Capability, EventType, Outcome
from tools import memory_tool as memory_module
from tools import skill_usage, transcription_tools


_CLOSED_FIELDS = {
    "capability",
    "action",
    "outcome",
    "subject_id",
    "duration_ms",
    "count",
    "occurred_at",
}
_PRIVATE_SENTINEL = "PRIVATE-CONTENT-MUST-NOT-REACH-THE-HOOK"


@pytest.fixture
def observed_capabilities(monkeypatch):
    """Route the real generic emitter into the real Journey projection."""
    payloads = []
    drafts = []

    monkeypatch.setattr(
        plugin_runtime,
        "has_hook",
        lambda hook_name: hook_name == "capability_event",
    )

    def _invoke(hook_name, **payload):
        assert hook_name == "capability_event"
        payloads.append(dict(payload))
        observer.on_capability_event(**payload)
        return [None]

    monkeypatch.setattr(plugin_runtime, "invoke_hook", _invoke)
    monkeypatch.setattr(observer, "_append", drafts.append)
    return payloads, drafts


def _assert_closed(payloads):
    assert payloads
    assert all(set(payload) <= _CLOSED_FIELDS for payload in payloads)
    assert _PRIVATE_SENTINEL not in repr(payloads)


def test_achievement_defaults_are_local_and_first_run_is_unset():
    settings = DEFAULT_CONFIG["achievements"]
    assert settings["tracking_enabled"] is True
    assert settings["active_time_enabled"] is True
    assert settings["celebration_mode"] == "standard"
    assert settings["raw_event_retention_days"] == 90
    assert settings["preferred_outcome"] == ""
    assert "capability_event" in plugin_runtime.VALID_HOOKS


def test_generic_emitter_returns_before_projecting_when_unobserved(monkeypatch):
    class _ExplodingValue:
        def __str__(self):
            raise AssertionError("producer value was projected without a listener")

    monkeypatch.setattr(plugin_runtime, "has_hook", lambda _name: False)
    monkeypatch.setattr(
        plugin_runtime,
        "invoke_hook",
        lambda *_args, **_kwargs: pytest.fail("hook should not be invoked"),
    )

    assert (
        plugin_runtime.emit_capability_event(
            capability=_ExplodingValue(),
            action="used",
            outcome="success",
        )
        is False
    )


def test_skill_producers_project_to_skill_journey_capabilities(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    monkeypatch.setattr(skill_usage, "_mutate", lambda *_args, **_kwargs: True)

    skill_usage.bump_use("safe-skill-id")
    skill_usage.bump_patch("safe-skill-id")

    assert [(item["capability"], item["action"]) for item in payloads] == [
        ("skill", "used"),
        ("skill", "authored"),
    ]
    assert [draft.capability for draft in drafts] == [
        Capability.SKILL_USE,
        Capability.SKILL_AUTHOR,
    ]
    assert all(draft.raw_subject_ref == "safe-skill-id" for draft in drafts)
    _assert_closed(payloads)


def test_skill_producer_does_not_emit_when_usage_commit_fails(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    monkeypatch.setattr(skill_usage, "_mutate", lambda *_args, **_kwargs: False)

    skill_usage.bump_use("safe-skill-id")

    assert payloads == []
    assert drafts == []


def test_transcription_producer_projects_without_path_model_or_result(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    result = {
        "success": True,
        "text": _PRIVATE_SENTINEL,
        "provider": _PRIVATE_SENTINEL,
    }
    monkeypatch.setattr(
        transcription_tools,
        "_transcribe_audio_impl",
        lambda _path, _model: result,
    )

    assert (
        transcription_tools.transcribe_audio(
            f"/private/{_PRIVATE_SENTINEL}.wav",
            model=_PRIVATE_SENTINEL,
        )
        is result
    )

    assert [(item["capability"], item["action"]) for item in payloads] == [
        ("voice", "transcribed")
    ]
    assert drafts[0].capability is Capability.VOICE_STT
    assert drafts[0].event_type is EventType.CAPABILITY_SUCCEEDED
    _assert_closed(payloads)


def test_transcription_failure_is_not_reported_as_success(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    monkeypatch.setattr(
        transcription_tools,
        "_transcribe_audio_impl",
        lambda _path, _model: {"success": False, "error": _PRIVATE_SENTINEL},
    )

    transcription_tools.transcribe_audio(f"/{_PRIVATE_SENTINEL}.wav")

    assert payloads == []
    assert drafts == []


def test_memory_store_and_recall_project_without_memory_content(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    committed = json.dumps({
        "success": True,
        "target": "memory",
        "message": _PRIVATE_SENTINEL,
    })
    monkeypatch.setattr(memory_module, "_memory_tool_impl", lambda **_kwargs: committed)

    assert (
        memory_module.memory_tool(
            action="add",
            target="memory",
            content=_PRIVATE_SENTINEL,
            store=object(),
        )
        == committed
    )

    store = memory_module.MemoryStore()
    store.memory_entries = [_PRIVATE_SENTINEL]
    store._system_prompt_snapshot["memory"] = _PRIVATE_SENTINEL
    assert store.format_for_system_prompt("memory") == _PRIVATE_SENTINEL
    # Formatting retries within one session must not inflate recall progress.
    assert store.format_for_system_prompt("memory") == _PRIVATE_SENTINEL

    assert [(item["capability"], item["action"]) for item in payloads] == [
        ("memory", "stored"),
        ("memory", "recalled"),
    ]
    assert [draft.capability for draft in drafts] == [
        Capability.MEMORY_STORE,
        Capability.MEMORY_RECALL,
    ]
    _assert_closed(payloads)


def test_staged_memory_write_is_not_reported_as_committed(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    monkeypatch.setattr(
        memory_module,
        "_memory_tool_impl",
        lambda **_kwargs: json.dumps({
            "success": True,
            "staged": True,
            "pending_id": "pending-1",
        }),
    )

    memory_module.memory_tool(
        action="add",
        target="memory",
        content=_PRIVATE_SENTINEL,
        store=object(),
    )

    assert payloads == []
    assert drafts == []


def test_approved_memory_write_emits_only_after_commit(
    monkeypatch, tmp_path, observed_capabilities
):
    payloads, drafts = observed_capabilities

    class _Store:
        def __init__(self):
            self.entries = []

        def _entries_for(self, _target):
            return self.entries

        def _path_for(self, _target):
            return tmp_path / "memory" / "MEMORY.md"

        def add(self, target, content):
            self.entries.append(content)
            return {"success": True, "target": target}

    monkeypatch.setattr(
        "agent.memory_governance.record_committed_write_best_effort",
        lambda **_kwargs: None,
    )

    result = memory_module.apply_memory_pending(
        {"action": "add", "target": "memory", "content": _PRIVATE_SENTINEL},
        _Store(),
    )

    assert result["success"] is True
    assert [(item["capability"], item["action"]) for item in payloads] == [
        ("memory", "stored")
    ]
    assert drafts[0].capability is Capability.MEMORY_STORE
    _assert_closed(payloads)


def test_cron_create_and_completion_project_without_job_inputs(
    monkeypatch, observed_capabilities
):
    payloads, drafts = observed_capabilities
    stored_jobs = []

    monkeypatch.setattr(cron_jobs, "_jobs_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(cron_jobs, "load_jobs", lambda: copy.deepcopy(stored_jobs))

    def _save_jobs(jobs):
        stored_jobs[:] = copy.deepcopy(jobs)

    monkeypatch.setattr(cron_jobs, "save_jobs", _save_jobs)
    monkeypatch.setattr(
        cron_jobs,
        "parse_schedule",
        lambda _schedule: {
            "kind": "interval",
            "minutes": 60,
            "display": "every hour",
        },
    )
    monkeypatch.setattr(
        cron_jobs,
        "compute_next_run",
        lambda *_args, **_kwargs: "2030-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(
        cron_jobs,
        "_compute_provider_model_snapshots",
        lambda **_kwargs: (None, None),
    )
    monkeypatch.setattr(
        cron_jobs,
        "_fabric_now",
        lambda: datetime(2029, 12, 31, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "cron.lifecycle_guard.check_gateway_lifecycle",
        lambda *_args, **_kwargs: None,
    )

    job = cron_jobs.create_job(
        prompt=_PRIVATE_SENTINEL,
        schedule=_PRIVATE_SENTINEL,
        name=_PRIVATE_SENTINEL,
        deliver=_PRIVATE_SENTINEL,
    )
    cron_jobs.mark_job_run(
        job["id"],
        success=False,
        error=_PRIVATE_SENTINEL,
        delivery_error=_PRIVATE_SENTINEL,
    )

    assert [(item["capability"], item["action"]) for item in payloads] == [
        ("automation", "schedule_created"),
        ("automation", "run_completed"),
    ]
    assert [draft.capability for draft in drafts] == [
        Capability.AUTOMATION_SCHEDULE,
        Capability.AUTOMATION_RUN,
    ]
    assert drafts[0].outcome is Outcome.SUCCESS
    assert drafts[1].outcome is Outcome.FAILED
    assert all(draft.raw_subject_ref == job["id"] for draft in drafts)
    _assert_closed(payloads)
