from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from agent.memory_scope import (
    MAX_MEMORY_TIMESTAMP,
    AuthorizedGatewaySource,
    MemoryIdentityAuthority,
    MemoryInvocationContext,
    MemoryScopeBinding,
    MemoryScopeConflict,
    MemoryScopeEffectState,
    MemoryScopeTransition,
    MemoryScopeTransitionResult,
    MemoryScopeUnavailable,
    MemoryScopeV1,
    build_gateway_memory_identity,
    build_local_memory_identity,
    derive_memory_scope,
    invocation_context,
    memory_operation_id,
    transition_operation_id,
    transition_scope,
)


def _homes(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fabric-root"
    profile = root / "profiles" / "alpha"
    profile.mkdir(parents=True, exist_ok=True)
    return root, profile


def _local_identity(tmp_path: Path, *, surface: str = "cli"):
    root, profile = _homes(tmp_path)
    return build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="Alpha",
        surface=surface,
        os_principal="posix-uid:501",
    )


def _gateway_identity(
    tmp_path: Path,
    *,
    platform: str = "telegram",
    user_id: str | None = "42",
    chat_type: str = "dm",
    chat_id: str = "chat-7",
    thread_id: str | None = None,
    shared_multi_user_session: bool = False,
):
    root, profile = _homes(tmp_path)
    return build_gateway_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="alpha",
        tenant_authority="managed-instance-a",
        source=AuthorizedGatewaySource(
            platform=platform,
            user_id=user_id,
            user_id_alt=None,
            chat_type=chat_type,
            scope_id="workspace-1",
            chat_id=chat_id,
            thread_id=thread_id,
            shared_multi_user_session=shared_multi_user_session,
        ),
    )


def _operation(scope: MemoryScopeV1, marker: str) -> str:
    return memory_operation_id(
        scope,
        operation="test_operation",
        nonce=marker,
    )


def test_local_identity_is_stable_and_normalizes_profile_name(tmp_path: Path):
    first = _local_identity(tmp_path)
    root = tmp_path / "fabric-root"
    profile = root / "profiles" / "alpha"
    second = build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )

    assert first == second
    assert re.fullmatch(r"ten_[0-9a-f]{32}", first.tenant_id)
    assert re.fullmatch(r"pro_[0-9a-f]{32}", first.profile_id)
    assert re.fullmatch(r"pri_[0-9a-f]{32}", first.principal_id)
    assert re.fullmatch(r"aud_[0-9a-f]{32}", first.audience_id)
    assert first.surface == "cli"


def test_local_identity_ignores_username_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("USER", "display-name-a")
    monkeypatch.setenv("USERNAME", "display-name-b")
    first = _local_identity(tmp_path)
    monkeypatch.setenv("USER", "attacker-controlled-name")
    monkeypatch.setenv("USERNAME", "other-name")
    second = _local_identity(tmp_path)

    assert first == second


def test_local_identity_changes_for_cloned_profile_home(tmp_path: Path):
    root = tmp_path / "root"
    first_home = root / "profiles" / "alpha"
    second_home = root / "profiles" / "alpha-clone"
    first_home.mkdir(parents=True)
    second_home.mkdir(parents=True)

    first = build_local_memory_identity(
        deployment_root=root,
        profile_home=first_home,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )
    second = build_local_memory_identity(
        deployment_root=root,
        profile_home=second_home,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )

    assert first.tenant_id == second.tenant_id
    assert first.principal_id == second.principal_id
    assert first.profile_id != second.profile_id
    first_scope = derive_memory_scope(first, session_id="shared-session")
    second_scope = derive_memory_scope(second, session_id="shared-session")
    assert (
        invocation_context(
            first_scope, _operation(first_scope, "first-profile")
        ).principal_key
        != invocation_context(
            second_scope, _operation(second_scope, "second-profile")
        ).principal_key
    )


def test_gateway_provider_principal_keys_are_profile_scoped(tmp_path: Path):
    root = tmp_path / "root"
    first_home = root / "profiles" / "alpha"
    second_home = root / "profiles" / "beta"
    first_home.mkdir(parents=True)
    second_home.mkdir(parents=True)
    source = AuthorizedGatewaySource(
        platform="telegram",
        user_id="42",
        user_id_alt=None,
        chat_type="dm",
        scope_id="workspace",
        chat_id="42",
        thread_id=None,
        shared_multi_user_session=False,
    )
    first = build_gateway_memory_identity(
        deployment_root=root,
        profile_home=first_home,
        profile_name="alpha",
        tenant_authority="managed-instance",
        source=source,
    )
    second = build_gateway_memory_identity(
        deployment_root=root,
        profile_home=second_home,
        profile_name="beta",
        tenant_authority="managed-instance",
        source=source,
    )
    first_scope = derive_memory_scope(first, session_id="same-session")
    second_scope = derive_memory_scope(second, session_id="same-session")

    assert first.principal_id == second.principal_id
    assert first.audience_id == second.audience_id
    assert first.profile_id != second.profile_id
    assert (
        invocation_context(
            first_scope, _operation(first_scope, "first-profile")
        ).principal_key
        != invocation_context(
            second_scope, _operation(second_scope, "second-profile")
        ).principal_key
    )


def test_symlink_alias_resolves_to_same_physical_profile(tmp_path: Path):
    root = tmp_path / "root"
    real_home = root / "profiles" / "alpha"
    alias_home = root / "profile-alias"
    real_home.mkdir(parents=True)
    try:
        alias_home.symlink_to(real_home, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")

    real = build_local_memory_identity(
        deployment_root=root,
        profile_home=real_home,
        profile_name="alpha",
        surface="tui",
        os_principal="posix-uid:501",
    )
    alias = build_local_memory_identity(
        deployment_root=root,
        profile_home=alias_home,
        profile_name="alpha",
        surface="tui",
        os_principal="posix-uid:501",
    )

    assert real == alias


def test_case_alias_resolves_to_same_physical_profile_when_supported(tmp_path: Path):
    root = tmp_path / "Root"
    real_home = root / "Profiles" / "Alpha"
    real_home.mkdir(parents=True)
    alias_home = real_home.with_name(real_home.name.swapcase())
    if not alias_home.exists() or not os.path.samefile(real_home, alias_home):
        pytest.skip("filesystem is case-sensitive")

    real = build_local_memory_identity(
        deployment_root=root,
        profile_home=real_home,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )
    alias = build_local_memory_identity(
        deployment_root=root,
        profile_home=alias_home,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )

    assert real == alias


def test_distinct_case_sensitive_profile_paths_do_not_collapse(tmp_path: Path):
    root = tmp_path / "root"
    lower = root / "profiles" / "alpha"
    upper = root / "profiles" / "ALPHA"
    lower.mkdir(parents=True)
    try:
        upper.mkdir()
    except FileExistsError:
        pytest.skip("filesystem is case-insensitive")
    if os.path.samefile(lower, upper):
        pytest.skip("filesystem aliases case variants")

    first = build_local_memory_identity(
        deployment_root=root,
        profile_home=lower,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )
    second = build_local_memory_identity(
        deployment_root=root,
        profile_home=upper,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )

    assert first.profile_id != second.profile_id


@pytest.mark.parametrize("surface", ["cli", "tui", "desktop", "dashboard", "cron"])
def test_local_surfaces_are_supported_without_changing_personal_identity(
    tmp_path: Path, surface: str
):
    identity = _local_identity(tmp_path, surface=surface)
    cli_identity = _local_identity(tmp_path, surface="cli")

    assert identity.surface == surface
    assert identity.tenant_id == cli_identity.tenant_id
    assert identity.profile_id == cli_identity.profile_id
    assert identity.principal_id == cli_identity.principal_id
    assert identity.audience_id == cli_identity.audience_id


def test_missing_profile_fails_with_stable_redacted_code(tmp_path: Path):
    missing = tmp_path / "sentinel-secret-profile-path"

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_local_memory_identity(
            deployment_root=tmp_path,
            profile_home=missing,
            profile_name="alpha",
            surface="cli",
            os_principal="posix-uid:501",
        )

    assert caught.value.code == "profile_unresolved"
    assert str(missing) not in str(caught.value)
    assert str(missing) not in repr(caught.value)


def test_local_identity_requires_authenticated_os_principal(tmp_path: Path):
    root, profile = _homes(tmp_path)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_local_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name="alpha",
            surface="cli",
            os_principal="",
        )

    assert caught.value.code == "local_principal_unavailable"


@pytest.mark.parametrize(
    "profile_name",
    [".", "..", "alpha beta", "café", "e\u0301", "alpha/name", "alpha:name"],
)
def test_profile_name_uses_existing_ascii_profile_contract(
    tmp_path: Path, profile_name: str
):
    root, profile = _homes(tmp_path)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_local_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name=profile_name,
            surface="cli",
            os_principal="posix-uid:501",
        )

    assert caught.value.code == "profile_identity_unavailable"


def test_ascii_profile_name_normalization_remains_compatible(tmp_path: Path):
    root, profile = _homes(tmp_path)
    lower = build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )
    title_case = build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="Alpha",
        surface="cli",
        os_principal="posix-uid:501",
    )

    assert lower == title_case


def test_unsupported_local_surface_fails_closed(tmp_path: Path):
    with pytest.raises(MemoryScopeUnavailable) as caught:
        _local_identity(tmp_path, surface="serve")

    assert caught.value.code == "surface_unsupported"


def test_same_raw_gateway_user_on_two_platforms_never_collides(tmp_path: Path):
    telegram = _gateway_identity(tmp_path, platform="telegram")
    discord = _gateway_identity(tmp_path, platform="discord")

    assert telegram.tenant_id == discord.tenant_id
    assert telegram.profile_id == discord.profile_id
    assert telegram.principal_id != discord.principal_id
    assert telegram.audience_id != discord.audience_id
    assert telegram.surface == "gateway:telegram"
    assert discord.surface == "gateway:discord"


def test_user_id_alt_is_the_stable_gateway_principal(tmp_path: Path):
    root, profile = _homes(tmp_path)

    def build(user_id: str):
        return build_gateway_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name="alpha",
            tenant_authority="managed-instance-a",
            source=AuthorizedGatewaySource(
                platform="signal",
                user_id=user_id,
                user_id_alt="stable-signal-uuid",
                chat_type="dm",
                scope_id=None,
                chat_id="chat",
                thread_id=None,
                shared_multi_user_session=False,
            ),
        )

    assert build("old-phone-number") == build("new-phone-number")


def test_dm_and_group_audiences_produce_distinct_provider_keys(tmp_path: Path):
    dm = _gateway_identity(tmp_path, chat_type="dm", chat_id="dm-42")
    group = _gateway_identity(
        tmp_path,
        chat_type="group",
        chat_id="group-42",
        thread_id="topic-9",
    )
    dm_scope = derive_memory_scope(dm, session_id="session-dm")
    group_scope = derive_memory_scope(group, session_id="session-group")

    assert dm.principal_id == group.principal_id
    assert dm.audience_id != group.audience_id
    assert (
        invocation_context(dm_scope, _operation(dm_scope, "op-dm")).principal_key
        != invocation_context(
            group_scope, _operation(group_scope, "op-group")
        ).principal_key
    )


@pytest.mark.parametrize("chat_type", ["group", "forum", "channel", "thread"])
def test_anonymous_shared_gateway_principal_fails_closed(
    tmp_path: Path, chat_type: str
):
    with pytest.raises(MemoryScopeUnavailable) as caught:
        _gateway_identity(tmp_path, user_id=None, chat_type=chat_type)

    assert caught.value.code == "ambiguous_gateway_principal"


def test_shared_multi_user_gateway_session_fails_closed(tmp_path: Path):
    with pytest.raises(MemoryScopeUnavailable) as caught:
        _gateway_identity(tmp_path, shared_multi_user_session=True)

    assert caught.value.code == "shared_memory_scope_unsupported"


def test_gateway_identity_requires_verified_tenant_authority(tmp_path: Path):
    root, profile = _homes(tmp_path)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_gateway_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name="alpha",
            tenant_authority="",
            source=AuthorizedGatewaySource(
                platform="telegram",
                user_id="42",
                user_id_alt=None,
                chat_type="dm",
                scope_id=None,
                chat_id="42",
                thread_id=None,
                shared_multi_user_session=False,
            ),
        )

    assert caught.value.code == "tenant_authority_unavailable"


def test_scope_ids_are_deterministic_and_repr_is_redacted(tmp_path: Path):
    identity = _local_identity(tmp_path)
    first = derive_memory_scope(identity, session_id="sentinel-session-id")
    second = derive_memory_scope(identity, session_id="sentinel-session-id")

    assert first == second
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        first.conversation_id,
    )
    assert "sentinel-session-id" not in repr(first)
    assert first.tenant_id not in repr(first)
    assert first.principal_id not in repr(first)
    assert first.conversation_id not in repr(first)
    assert "<redacted>" in repr(first)


def test_session_ids_are_bounded_and_control_free(tmp_path: Path):
    identity = _local_identity(tmp_path)

    for session_id in ("", "has\nnewline", "x" * 1025):
        with pytest.raises(MemoryScopeUnavailable) as caught:
            derive_memory_scope(identity, session_id=session_id)
        assert caught.value.code == "conversation_id_unavailable"


def test_new_reset_branch_rewind_compression_and_delegation_transitions(tmp_path: Path):
    identity = _local_identity(tmp_path)
    root = derive_memory_scope(identity, session_id="root-session")

    new_scope = transition_scope(
        root,
        reason=MemoryScopeTransition.NEW_SESSION,
        new_session_id="new-session",
    )
    reset_scope = transition_scope(
        root,
        reason=MemoryScopeTransition.RESET,
        new_session_id="reset-session",
    )
    branch = transition_scope(
        root,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="branch-session",
    )
    rewind_one = transition_scope(
        root,
        reason=MemoryScopeTransition.REWIND,
        new_session_id="root-session",
        durable_revision=1,
    )
    rewind_two = transition_scope(
        root,
        reason=MemoryScopeTransition.REWIND,
        new_session_id="root-session",
        durable_revision=2,
    )
    compressed = transition_scope(
        rewind_one,
        reason=MemoryScopeTransition.COMPRESSION,
        new_session_id="compressed-session",
    )
    delegated = transition_scope(
        root,
        reason=MemoryScopeTransition.DELEGATION,
        new_session_id="child-session",
    )

    assert new_scope.conversation_id != root.conversation_id
    assert new_scope.branch_id is None
    assert new_scope.parent_conversation_id is None
    assert reset_scope.conversation_id != root.conversation_id
    assert branch.conversation_id != root.conversation_id
    assert branch.branch_id is not None
    assert branch.parent_conversation_id == root.conversation_id
    assert rewind_one.conversation_id == root.conversation_id
    assert rewind_one.branch_id != rewind_two.branch_id
    assert compressed.conversation_id == rewind_one.conversation_id
    assert compressed.branch_id == rewind_one.branch_id
    assert compressed.parent_conversation_id == rewind_one.parent_conversation_id
    assert delegated.conversation_id != root.conversation_id
    assert delegated.branch_id is None
    assert delegated.parent_conversation_id == root.conversation_id


@pytest.mark.parametrize(
    "reason, code",
    [
        (MemoryScopeTransition.RESUME, "scope_transition_requires_binding"),
        (MemoryScopeTransition.PROFILE_CHANGE, "scope_profile_rebuild_required"),
    ],
)
def test_resume_and_profile_change_cannot_be_derived_in_place(
    tmp_path: Path, reason: MemoryScopeTransition, code: str
):
    scope = derive_memory_scope(_local_identity(tmp_path), session_id="root")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        transition_scope(scope, reason=reason, new_session_id="target")

    assert caught.value.code == code


def test_rewind_requires_positive_durable_revision(tmp_path: Path):
    scope = derive_memory_scope(_local_identity(tmp_path), session_id="root")

    for revision in (None, 0, -1, True):
        with pytest.raises(MemoryScopeUnavailable) as caught:
            transition_scope(
                scope,
                reason=MemoryScopeTransition.REWIND,
                new_session_id="root",
                durable_revision=revision,
            )
        assert caught.value.code == "rewind_revision_unavailable"


@pytest.mark.parametrize(
    "reason",
    [
        MemoryScopeTransition.NEW_SESSION,
        MemoryScopeTransition.RESET,
        MemoryScopeTransition.BRANCH,
        MemoryScopeTransition.COMPRESSION,
        MemoryScopeTransition.DELEGATION,
    ],
)
def test_non_rewind_transitions_reject_irrelevant_durable_revision(
    tmp_path: Path, reason: MemoryScopeTransition
):
    scope = derive_memory_scope(_local_identity(tmp_path), session_id="root")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        transition_scope(
            scope,
            reason=reason,
            new_session_id="target",
            durable_revision=1,
        )

    assert caught.value.code == "scope_transition_input_invalid"


def test_invocation_context_distinguishes_root_and_rewind_branch(tmp_path: Path):
    root = derive_memory_scope(_local_identity(tmp_path), session_id="root")
    rewind = transition_scope(
        root,
        reason=MemoryScopeTransition.REWIND,
        new_session_id="root",
        durable_revision=1,
    )

    root_context = invocation_context(root, _operation(root, "operation-root"))
    rewind_context = invocation_context(rewind, _operation(rewind, "operation-rewind"))

    assert root_context.principal_key == rewind_context.principal_key
    assert root_context.conversation_key != rewind_context.conversation_key
    assert "operation-root" not in repr(root_context)
    assert root.conversation_id not in repr(root_context)


def test_operation_ids_are_opaque_deterministic_and_scope_bound(tmp_path: Path):
    first_scope = derive_memory_scope(_local_identity(tmp_path), session_id="first")
    second_scope = derive_memory_scope(_local_identity(tmp_path), session_id="second")

    first = memory_operation_id(
        first_scope,
        operation="sync_turn",
        nonce="raw-platform-user-42",
    )
    retry = memory_operation_id(
        first_scope,
        operation="sync_turn",
        nonce="raw-platform-user-42",
    )
    other = memory_operation_id(
        second_scope,
        operation="sync_turn",
        nonce="raw-platform-user-42",
    )

    assert first == retry
    assert first != other
    assert re.fullmatch(r"mop_[0-9a-f]{32}", first)
    assert "raw-platform-user-42" not in first
    with pytest.raises(MemoryScopeUnavailable) as raw:
        invocation_context(first_scope, "raw-platform-user-42")
    assert raw.value.code == "memory_operation_id_unavailable"

    surface_variant = replace(first_scope, surface="tui")
    parent_variant = replace(
        first_scope,
        parent_conversation_id=second_scope.conversation_id,
    )
    assert first != memory_operation_id(
        surface_variant,
        operation="sync_turn",
        nonce="raw-platform-user-42",
    )
    assert first != memory_operation_id(
        parent_variant,
        operation="sync_turn",
        nonce="raw-platform-user-42",
    )
    for nonce in (" raw", "raw ", "has\ncontrol", "x" * 257):
        with pytest.raises(MemoryScopeUnavailable) as invalid_nonce:
            memory_operation_id(
                first_scope,
                operation="sync_turn",
                nonce=nonce,
            )
        assert invalid_nonce.value.code == "memory_operation_nonce_unavailable"


def test_transition_operation_id_is_deterministic_and_revision_bound(tmp_path: Path):
    root = derive_memory_scope(_local_identity(tmp_path), session_id="root")
    target = transition_scope(
        root,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="branch",
    )

    first = transition_operation_id(
        root,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="root",
        target_session_id="branch",
        source_revision=7,
    )
    retry = transition_operation_id(
        root,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="root",
        target_session_id="branch",
        source_revision=7,
    )
    next_revision = transition_operation_id(
        root,
        target,
        MemoryScopeTransition.BRANCH,
        source_session_id="root",
        target_session_id="branch",
        source_revision=8,
    )
    other_target = transition_scope(
        root,
        reason=MemoryScopeTransition.BRANCH,
        new_session_id="branch-retry-with-different-target",
    )
    different_target_session = transition_operation_id(
        root,
        other_target,
        MemoryScopeTransition.BRANCH,
        source_session_id="root",
        target_session_id="branch-retry-with-different-target",
        source_revision=7,
    )

    assert first == retry
    assert first != next_revision
    assert first != different_target_session
    assert re.fullmatch(r"mtr_[0-9a-f]{32}", first)


def test_exception_and_identity_reprs_never_include_raw_authority(tmp_path: Path):
    identity = _gateway_identity(tmp_path)

    assert "managed-instance-a" not in repr(identity)
    assert "workspace-1" not in repr(identity)
    assert "42" not in repr(identity)
    assert identity.tenant_id not in repr(identity)
    assert repr(identity) == "MemoryIdentityAuthority(<redacted>)"


def test_actual_posix_principal_path_uses_uid_not_username(monkeypatch, tmp_path: Path):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX uid is unavailable")
    root, profile = _homes(tmp_path)
    monkeypatch.setenv("USER", "untrusted-display-name")

    identity = build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="alpha",
        surface="cli",
    )

    expected = build_local_memory_identity(
        deployment_root=root,
        profile_home=profile,
        profile_name="alpha",
        surface="cli",
        os_principal=f"posix-uid:{os.getuid()}",
    )
    assert identity == expected


def test_gateway_source_and_public_model_reprs_are_redacted(tmp_path: Path):
    source = AuthorizedGatewaySource(
        platform="telegram",
        user_id="sentinel-user",
        user_id_alt=None,
        chat_type="dm",
        scope_id="sentinel-workspace",
        chat_id="sentinel-chat",
        thread_id=None,
        shared_multi_user_session=False,
    )
    scope = derive_memory_scope(
        _local_identity(tmp_path), session_id="sentinel-session"
    )
    context = invocation_context(scope, _operation(scope, "sentinel-operation"))

    for value in (
        "sentinel-user",
        "sentinel-workspace",
        "sentinel-chat",
        "sentinel-session",
        "sentinel-operation",
    ):
        assert value not in repr(source)
        assert value not in repr(context)
    assert repr(source) == "AuthorizedGatewaySource(<redacted>)"
    assert repr(context) == "MemoryInvocationContext(<redacted>)"


def test_exception_types_replace_untrusted_error_codes():
    unavailable = MemoryScopeUnavailable("sentinel/secret\nvalue")
    conflict = MemoryScopeConflict("sentinel/secret\nvalue")

    assert unavailable.code == "memory_scope_unavailable"
    assert conflict.code == "memory_scope_conflict"
    assert "sentinel" not in repr(unavailable)
    assert "sentinel" not in repr(conflict)


def test_public_identity_constructor_requires_canonical_surface(tmp_path: Path):
    identity = _local_identity(tmp_path)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        MemoryIdentityAuthority(
            tenant_id=identity.tenant_id,
            profile_id=identity.profile_id,
            principal_id=identity.principal_id,
            audience_id=identity.audience_id,
            surface=" CLI ",
        )

    assert caught.value.code == "surface_unsupported"


def test_public_models_reject_noncanonical_types_versions_and_timestamps(
    tmp_path: Path,
):
    identity = _local_identity(tmp_path)
    scope = derive_memory_scope(identity, session_id="root")
    values = {
        "tenant_id": identity.tenant_id,
        "profile_id": identity.profile_id,
        "principal_id": identity.principal_id,
        "audience_id": identity.audience_id,
        "conversation_id": scope.conversation_id,
        "branch_id": None,
        "parent_conversation_id": None,
        "surface": "cli",
    }

    for version in (True, 1.0):
        with pytest.raises(MemoryScopeUnavailable) as invalid_version:
            MemoryScopeV1(**values, schema_version=version)  # type: ignore[arg-type]
        assert invalid_version.value.code == "scope_version_unsupported"
    with pytest.raises(MemoryScopeUnavailable) as invalid_identity:
        MemoryIdentityAuthority(
            tenant_id=None,  # type: ignore[arg-type]
            profile_id=identity.profile_id,
            principal_id=identity.principal_id,
            audience_id=identity.audience_id,
            surface="cli",
        )
    assert invalid_identity.value.code == "canonical_identity_invalid"
    for timestamp in (-1, float("nan"), float("inf"), MAX_MEMORY_TIMESTAMP + 1):
        with pytest.raises(MemoryScopeUnavailable) as invalid_timestamp:
            MemoryScopeBinding(
                session_id="root",
                scope=scope,
                revision=1,
                updated_at=timestamp,
            )
        assert invalid_timestamp.value.code == "scope_timestamp_invalid"

    target = MemoryScopeBinding(
        session_id="root",
        scope=scope,
        revision=1,
        updated_at=2,
    )
    with pytest.raises(MemoryScopeUnavailable) as reversed_time:
        MemoryScopeTransitionResult(
            transition_id="mtr_" + ("a" * 32),
            source_session_id="root",
            source_revision=1,
            target=target,
            reason=MemoryScopeTransition.REWIND,
            effect_state=MemoryScopeEffectState.PREPARED,
            effect_error_code=None,
            created_at=2,
            updated_at=1,
        )
    assert reversed_time.value.code == "scope_timestamp_invalid"

    older_target = replace(target, updated_at=1)
    ordered = MemoryScopeTransitionResult(
        transition_id="mtr_" + ("b" * 32),
        source_session_id="root",
        source_revision=1,
        target=older_target,
        reason=MemoryScopeTransition.REWIND,
        effect_state=MemoryScopeEffectState.PREPARED,
        effect_error_code=None,
        created_at=2,
        updated_at=3,
    )
    assert ordered.target.updated_at < ordered.created_at < ordered.updated_at

    with pytest.raises(MemoryScopeUnavailable) as future_target:
        MemoryScopeTransitionResult(
            transition_id="mtr_" + ("c" * 32),
            source_session_id="root",
            source_revision=1,
            target=target,
            reason=MemoryScopeTransition.REWIND,
            effect_state=MemoryScopeEffectState.PREPARED,
            effect_error_code=None,
            created_at=1,
            updated_at=3,
        )
    assert future_target.value.code == "scope_timestamp_invalid"


def test_invocation_context_constructor_validates_keys_and_operation(tmp_path: Path):
    scope = derive_memory_scope(_local_identity(tmp_path), session_id="root")
    canonical = invocation_context(scope, _operation(scope, "canonical"))

    with pytest.raises(MemoryScopeUnavailable) as invalid_key:
        MemoryInvocationContext(
            scope=scope,
            principal_key="not-a-provider-key",
            conversation_key=canonical.conversation_key,
            parent_conversation_key=canonical.parent_conversation_key,
            operation_id=canonical.operation_id,
        )
    with pytest.raises(MemoryScopeUnavailable) as invalid_operation:
        MemoryInvocationContext(
            scope=scope,
            principal_key=canonical.principal_key,
            conversation_key=canonical.conversation_key,
            parent_conversation_key=canonical.parent_conversation_key,
            operation_id="has\ncontrol",
        )
    with pytest.raises(MemoryScopeUnavailable) as forged_keys:
        MemoryInvocationContext(
            scope=scope,
            principal_key="mem_" + ("a" * 32),
            conversation_key="mem_" + ("b" * 32),
            parent_conversation_key=None,
            operation_id=canonical.operation_id,
        )

    assert invalid_key.value.code == "provider_key_invalid"
    assert invalid_operation.value.code == "memory_operation_id_unavailable"
    assert forged_keys.value.code == "provider_key_invalid"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"platform": 7}, "surface_unsupported"),
        ({"user_id": 42}, "ambiguous_gateway_principal"),
        ({"scope_id": 42}, "audience_unavailable"),
        ({"chat_type": 42}, "audience_unavailable"),
        ({"shared_multi_user_session": 1}, "gateway_authority_unavailable"),
        ({"user_id": "has\ncontrol"}, "ambiguous_gateway_principal"),
    ],
)
def test_gateway_authority_fields_are_strictly_typed_and_control_free(
    tmp_path: Path, overrides: dict[str, object], code: str
):
    root, profile = _homes(tmp_path)
    values: dict[str, object] = {
        "platform": "telegram",
        "user_id": "42",
        "user_id_alt": None,
        "chat_type": "dm",
        "scope_id": "workspace",
        "chat_id": "chat",
        "thread_id": None,
        "shared_multi_user_session": False,
    }
    values.update(overrides)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_gateway_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name="alpha",
            tenant_authority="managed-instance",
            source=AuthorizedGatewaySource(**values),  # type: ignore[arg-type]
        )

    assert caught.value.code == code


def test_profile_home_must_be_permission_checked(monkeypatch, tmp_path: Path):
    root, profile = _homes(tmp_path)
    original_access = os.access

    def deny_profile(path, mode, **kwargs):
        if Path(path) == profile.resolve():
            return False
        return original_access(path, mode, **kwargs)

    monkeypatch.setattr(os, "access", deny_profile)

    with pytest.raises(MemoryScopeUnavailable) as caught:
        build_local_memory_identity(
            deployment_root=root,
            profile_home=profile,
            profile_name="alpha",
            surface="cli",
            os_principal="posix-uid:501",
        )

    assert caught.value.code == "profile_unresolved"


def test_transition_operation_rejects_cross_authority_target(tmp_path: Path):
    local = derive_memory_scope(_local_identity(tmp_path), session_id="local")
    gateway = derive_memory_scope(_gateway_identity(tmp_path), session_id="gateway")

    with pytest.raises(MemoryScopeUnavailable) as caught:
        transition_operation_id(
            local,
            gateway,
            MemoryScopeTransition.BRANCH,
            source_session_id="local",
            target_session_id="gateway",
            source_revision=1,
        )

    assert caught.value.code == "scope_authority_mismatch"
