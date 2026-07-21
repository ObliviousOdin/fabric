"""Unit tests for Loom's state machine and plan serialisation."""

from __future__ import annotations

from fabric_cli.loom.models import (
    Deployment,
    DeploymentState,
    Plan,
    PlanStep,
    can_transition,
)


def test_happy_path_transitions_are_legal():
    chain = [
        DeploymentState.PLANNED,
        DeploymentState.BUILDING,
        DeploymentState.STARTING,
        DeploymentState.HEALTH_CHECKING,
        DeploymentState.ACTIVE,
    ]
    for src, dst in zip(chain, chain[1:]):
        assert can_transition(src, dst), f"{src} -> {dst} should be legal"


def test_illegal_skips_are_rejected():
    assert not can_transition(DeploymentState.PLANNED, DeploymentState.ACTIVE)
    assert not can_transition(DeploymentState.BUILDING, DeploymentState.ACTIVE)
    assert not can_transition(DeploymentState.FAILED, DeploymentState.ACTIVE)


def test_terminal_states():
    assert DeploymentState.FAILED.is_terminal
    assert DeploymentState.SUPERSEDED.is_terminal
    assert not DeploymentState.ACTIVE.is_terminal
    assert not DeploymentState.PLANNED.is_terminal


def test_superseded_and_rolled_back_can_reactivate():
    # Rollback reactivates a displaced release.
    assert can_transition(DeploymentState.SUPERSEDED, DeploymentState.ACTIVE)
    assert can_transition(DeploymentState.ROLLED_BACK, DeploymentState.ACTIVE)


def test_plan_roundtrip_and_destructive_flag():
    plan = Plan(
        summary="do a thing",
        steps=[
            PlanStep("create net", "docker network create", "create"),
            PlanStep("delete volume", "rm -rf data", "destructive"),
        ],
    )
    assert plan.has_destructive
    restored = Plan.from_dict(plan.to_dict())
    assert restored.summary == "do a thing"
    assert len(restored.steps) == 2
    assert restored.has_destructive
    assert restored.steps[0].kind == "create"


def test_deployment_defaults():
    dep = Deployment(id="dep_1", project_id="p", host_id="h")
    assert dep.state == DeploymentState.PLANNED.value
    assert dep.active is False
