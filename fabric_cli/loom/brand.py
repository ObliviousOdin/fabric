"""Central brand and configuration constants for Loom.

Following the rebrand discipline in
``docs/dockplane-integration/source-spec/REBRAND_MAP.md``: keep the values that
must agree in *one* module rather than scattering literal strings across the
CLI, dashboard, and tools. Environment-variable lookups honour a canonical
``LOOM_`` prefix; there is no legacy prefix to support because this is a
native implementation rather than a rename of an existing install.
"""

from __future__ import annotations

import os
from typing import Final, Optional


class _Brand:
    """Immutable brand constants (a tiny frozen namespace)."""

    product_name: Final[str] = "Loom"
    cli_name: Final[str] = "loom"
    tagline: Final[str] = "Weave source into running deployments."
    env_prefix: Final[str] = "LOOM_"
    # Per-profile store file, resolved under the active FABRIC_HOME.
    store_filename: Final[str] = "loom.db"
    # Docker label namespace used to establish positive ownership of resources
    # Loom creates, so cleanup never relies on name patterns alone.
    label_prefix: Final[str] = "loom"
    user_agent_fmt: Final[str] = "loom/{version}"

    def env(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Read a ``LOOM_<NAME>`` environment variable.

        ``name`` is given without the prefix, e.g. ``env("TOKEN")`` reads
        ``LOOM_TOKEN``.
        """
        return os.environ.get(self.env_prefix + name, default)

    def label(self, suffix: str) -> str:
        """Return a namespaced Docker label key, e.g. ``loom.deployment``."""
        return f"{self.label_prefix}.{suffix}"


BRAND: Final[_Brand] = _Brand()
