"""Shared atomic credential-source re-engagement helper."""

from __future__ import annotations

from agent.credential_pool import CUSTOM_POOL_PREFIX


def clear_provider_suppressions(provider_id: str) -> bool:
    """Re-enable every source for one provider in one locked publication.

    Verified login paths call this from a retriable credential callback, so a
    per-source read/write loop can both publish a partial result and run more
    than once.  One auth-store mutation keeps the provider's suppression set
    all-or-nothing.  Persistence failures deliberately propagate: callers must
    never record an OAuth completion while its credential sources remain
    disabled.
    """

    if provider_id.startswith(CUSTOM_POOL_PREFIX):
        return False
    from fabric_cli import auth as auth_mod

    with auth_mod._auth_store_lock():
        auth_store = auth_mod._load_auth_store()
        suppressed = auth_store.get("suppressed_sources")
        if not isinstance(suppressed, dict) or provider_id not in suppressed:
            return False
        suppressed.pop(provider_id, None)
        if not suppressed:
            auth_store.pop("suppressed_sources", None)
        auth_mod._save_auth_store(auth_store)
        return True


__all__ = ["clear_provider_suppressions"]
