"""Profile-scoped application policy for AI inference egress.

This module is intentionally pure: it does not read files, environment
variables, credentials, DNS, or the network.  Callers load the active
profile's config and pass it to :func:`policy_from_config` at the route
resolution boundary.

``local_ai`` is an application routing policy, not a whole-process sandbox.
It accepts only literal local/private inference endpoints.  ``air_gapped`` is
reserved until a separately verified process-wide network boundary exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import ipaddress
import re
from typing import Any, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit


class EgressMode(str, Enum):
    """Configured application egress mode."""

    ONLINE = "online"
    LOCAL_AI = "local_ai"
    AIR_GAPPED = "air_gapped"


class InferencePurpose(str, Enum):
    """AI route purposes covered by the application policy."""

    PRIMARY = "primary"
    AUXILIARY = "auxiliary"
    FALLBACK = "fallback"
    DELEGATION = "delegation"
    MOA_SLOT = "moa_slot"
    MEMORY = "memory"
    EMBEDDING = "embedding"


_PRIVATE_APPROVAL_SUPERNETS: Tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)

# Cloud metadata addresses are denied even when a user approves a containing
# private/CGNAT range. Most platforms use 169.254.169.254 (already rejected as
# link-local); Alibaba Cloud also exposes instance metadata at the CGNAT
# address 100.100.100.200, which would otherwise pass an approved 100.64/10.
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)

_SAFE_IDENTITY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")

# Pure, shipped provider-alias normalization for pre-credential trust checks.
# Runtime/provider registries can load plugins or inspect credentials, so the
# egress boundary cannot call them merely to learn that (for example) `codex`
# is the OAuth-backed `openai-codex` transport. Keep this list aligned with the
# built-in provider profiles and auth resolver aliases.
_INFERENCE_PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "claude-oauth": "anthropic",
    "claude-code": "anthropic",
    "copilot": "copilot",
    "github": "copilot",
    "github-copilot": "copilot",
    "github-models": "copilot",
    "github-model": "copilot",
    "openai-codex": "openai-codex",
    "openai_codex": "openai-codex",
    "codex": "openai-codex",
    "nous": "nous",
    "nous-portal": "nous",
    "nousresearch": "nous",
    "qwen": "qwen-oauth",
    "qwen-portal": "qwen-oauth",
    "qwen-cli": "qwen-oauth",
    "qwen-oauth": "qwen-oauth",
    "x-ai-oauth": "xai-oauth",
    "grok-oauth": "xai-oauth",
    "xai-grok-oauth": "xai-oauth",
    "xai-oauth": "xai-oauth",
    "minimax-portal": "minimax-oauth",
    "minimax-global": "minimax-oauth",
    "minimax_oauth": "minimax-oauth",
    "minimax-oauth-io": "minimax-oauth",
    "minimax-oauth": "minimax-oauth",
    "aws": "bedrock",
    "aws-bedrock": "bedrock",
    "amazon-bedrock": "bedrock",
    "amazon": "bedrock",
    "bedrock": "bedrock",
    "github-copilot-acp": "copilot-acp",
    "copilot-acp-agent": "copilot-acp",
    "copilot-acp": "copilot-acp",
    "google-vertex": "vertex",
    "vertex-ai": "vertex",
    "gcp-vertex": "vertex",
    "vertexai": "vertex",
    "vertex": "vertex",
    "moa": "moa",
    "ollama": "ollama",
    "ollama-local": "ollama",
    "azure": "azure-foundry",
    "azure-ai-foundry": "azure-foundry",
    "azure-ai": "azure-foundry",
    "azure-foundry": "azure-foundry",
}


def canonical_inference_provider(value: Any) -> str:
    """Normalize a built-in provider identity without I/O or discovery."""

    normalized = str(value or "").strip().lower()
    return _INFERENCE_PROVIDER_ALIASES.get(normalized, normalized)


def _safe_identity(value: Any, *, fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if _SAFE_IDENTITY_RE.fullmatch(normalized):
        return normalized
    return fallback


def _short_digest(value: Any) -> str:
    raw = str(value or "").encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:12]


_EMPTY_ORIGIN_DIGEST = _short_digest("")


def _sanitized_origin_digest(value: Any) -> str:
    """Hash only canonical scheme/host/port, never URL secret material."""

    if not isinstance(value, str):
        return _EMPTY_ORIGIN_DIGEST
    candidate = value.strip()
    if not candidate or any(
        ord(char) < 32 or ord(char) == 127 for char in candidate
    ):
        return _EMPTY_ORIGIN_DIGEST
    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return _EMPTY_ORIGIN_DIGEST
    if scheme not in {"http", "https"} or not hostname or "%" in hostname:
        return _EMPTY_ORIGIN_DIGEST

    if hostname == "localhost":
        host_text = "127.0.0.1"
    else:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            host_text = hostname.lower()
            if (
                not host_text.isascii()
                or not re.fullmatch(r"[a-z0-9.-]+", host_text)
            ):
                return _EMPTY_ORIGIN_DIGEST
        else:
            host_text = str(address)
            if isinstance(address, ipaddress.IPv6Address):
                host_text = f"[{host_text}]"

    default_port = 80 if scheme == "http" else 443
    netloc = host_text if port in {None, default_port} else f"{host_text}:{port}"
    return _short_digest(f"{scheme}://{netloc}")


class EgressPolicyError(RuntimeError):
    """Base class for stable, secret-free policy failures."""

    def __init__(
        self,
        reason: str,
        *,
        mode: EgressMode,
        purpose: str,
        provider: str,
        origin_digest: str,
    ) -> None:
        self.reason = reason
        self.mode = mode
        self.purpose = _safe_identity(purpose, fallback="unknown")
        self.provider = _safe_identity(provider, fallback="unknown")
        self.origin_digest = origin_digest
        super().__init__(
            f"egress_policy:{reason} mode={mode.value} "
            f"purpose={self.purpose} provider={self.provider} "
            f"origin={origin_digest}"
        )


class EgressPolicyViolation(EgressPolicyError):
    """The requested inference route is forbidden by the active policy."""


class EgressPolicyUnavailable(EgressPolicyError):
    """The configured policy cannot honestly be enforced by this runtime."""


class EgressPolicyConfigurationError(ValueError):
    """Invalid egress configuration, reported without echoing its value."""

    def __init__(self, reason: str, *, item_index: Optional[int] = None) -> None:
        self.reason = reason
        self.item_index = item_index
        suffix = f" item={item_index}" if item_index is not None else ""
        super().__init__(f"egress_policy_config:{reason}{suffix}")


@dataclass(frozen=True)
class EgressPolicy:
    """Immutable policy derived from one profile's config snapshot."""

    mode: EgressMode
    allowed_cidrs: Tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @property
    def available(self) -> bool:
        return self.mode is not EgressMode.AIR_GAPPED

    @property
    def unavailable_reason(self) -> Optional[str]:
        if self.available:
            return None
        return "whole_process_network_boundary_missing"


@dataclass(frozen=True)
class AuthorizedInferenceRoute:
    """Normalized route safe to hand to a local-policy HTTP client."""

    purpose: str
    provider: str
    base_url: str
    address: str
    origin_digest: str
    allow_environment_proxy: bool = False


def _is_approvable_private_network(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    return any(
        network.version == supernet.version and network.subnet_of(supernet)
        for supernet in _PRIVATE_APPROVAL_SUPERNETS
    )


def _parse_allowed_cidrs(raw: Any) -> Tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise EgressPolicyConfigurationError("allowed_cidrs_must_be_list")

    parsed: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise EgressPolicyConfigurationError(
                "invalid_allowed_cidr", item_index=index
            )
        try:
            network = ipaddress.ip_network(item.strip(), strict=True)
        except ValueError as exc:
            raise EgressPolicyConfigurationError(
                "invalid_allowed_cidr", item_index=index
            ) from exc
        if not _is_approvable_private_network(network):
            raise EgressPolicyConfigurationError(
                "cidr_not_private_approvable", item_index=index
            )
        parsed.append(network)

    unique = set(parsed)
    return tuple(
        sorted(
            unique,
            key=lambda net: (net.version, int(net.network_address), net.prefixlen),
        )
    )


def policy_from_config(config: Mapping[str, Any] | None) -> EgressPolicy:
    """Build a policy from an already profile-scoped config mapping."""

    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise EgressPolicyConfigurationError("config_must_be_mapping")

    security = config.get("security", {})
    if security is None:
        security = {}
    if not isinstance(security, Mapping):
        raise EgressPolicyConfigurationError("security_must_be_mapping")

    raw_mode = security.get("egress_mode", EgressMode.ONLINE.value)
    if not isinstance(raw_mode, str):
        raise EgressPolicyConfigurationError("invalid_egress_mode")
    try:
        mode = EgressMode(raw_mode.strip().lower())
    except ValueError as exc:
        raise EgressPolicyConfigurationError("invalid_egress_mode") from exc

    cidrs = _parse_allowed_cidrs(security.get("local_ai_allowed_cidrs", []))
    return EgressPolicy(mode=mode, allowed_cidrs=cidrs)


def require_policy_available(policy: EgressPolicy, *, surface: str) -> None:
    """Reject configured-but-unavailable enforcement before side effects."""

    if policy.available:
        return
    raise EgressPolicyUnavailable(
        "whole_process_network_boundary_missing",
        mode=policy.mode,
        purpose=_safe_identity(surface, fallback="unknown"),
        provider="none",
        origin_digest=_short_digest(""),
    )


def _violation(
    reason: str,
    *,
    policy: EgressPolicy,
    purpose: str,
    provider: str,
    base_url: Any,
) -> EgressPolicyViolation:
    return EgressPolicyViolation(
        reason,
        mode=policy.mode,
        purpose=purpose,
        provider=provider,
        origin_digest=_sanitized_origin_digest(base_url),
    )


def _address_is_approved(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_cidrs: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    if address.is_loopback:
        return True
    return any(
        address.version == network.version and address in network
        for network in allowed_cidrs
    )


def authorize_inference_route(
    policy: EgressPolicy,
    *,
    purpose: InferencePurpose | str,
    provider: str,
    base_url: Any,
) -> Optional[AuthorizedInferenceRoute]:
    """Authorize and normalize one inference route.

    ``online`` returns ``None`` so callers preserve the exact legacy route.
    ``local_ai`` returns a canonical literal-IP URL.  No DNS function is ever
    called.  ``air_gapped`` raises unavailable until the deployment boundary
    is implemented.
    """

    purpose_value = (
        purpose.value if isinstance(purpose, InferencePurpose) else str(purpose or "")
    )
    safe_purpose = _safe_identity(purpose_value, fallback="unknown")
    safe_provider = _safe_identity(provider, fallback="unknown")

    require_policy_available(policy, surface=safe_purpose)
    if policy.mode is EgressMode.ONLINE:
        return None

    if not isinstance(base_url, str) or not base_url.strip():
        raise _violation(
            "remote_ai_forbidden",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=base_url,
        )

    candidate = base_url.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise _violation(
            "invalid_endpoint",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        )
    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise _violation(
            "invalid_endpoint",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        ) from None

    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in hostname
        or port == 0
    ):
        raise _violation(
            "invalid_endpoint",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        )

    if hostname == "localhost":
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            "127.0.0.1"
        )
    else:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            raise _violation(
                "hostname_not_allowed",
                policy=policy,
                purpose=safe_purpose,
                provider=safe_provider,
                base_url=candidate,
            ) from None

    # Mapped IPv4 addresses create two textual identities for the same target
    # and have varied proxy/firewall treatment.  Keep the trust contract
    # single-form and require the ordinary IPv4 literal instead.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        raise _violation(
            "address_not_approved",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        )

    if not address.is_loopback and (
        address in _METADATA_ADDRESSES
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or address.is_reserved
        or not _address_is_approved(address, policy.allowed_cidrs)
    ):
        raise _violation(
            "address_not_approved",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        )

    host_text = str(address)
    if isinstance(address, ipaddress.IPv6Address):
        host_text = f"[{host_text}]"
    netloc = f"{host_text}:{port}" if port is not None else host_text
    normalized = urlunsplit((scheme, netloc, parsed.path, "", "")).rstrip("/")
    if not normalized:
        # Defensive only; valid scheme + netloc above should make this
        # unreachable, but keep the failure category stable if that changes.
        raise _violation(
            "invalid_endpoint",
            policy=policy,
            purpose=safe_purpose,
            provider=safe_provider,
            base_url=candidate,
        )

    return AuthorizedInferenceRoute(
        purpose=safe_purpose,
        provider=safe_provider,
        base_url=normalized,
        address=str(address),
        origin_digest=_sanitized_origin_digest(normalized),
    )


__all__ = [
    "AuthorizedInferenceRoute",
    "EgressMode",
    "EgressPolicy",
    "EgressPolicyConfigurationError",
    "EgressPolicyError",
    "EgressPolicyUnavailable",
    "EgressPolicyViolation",
    "InferencePurpose",
    "authorize_inference_route",
    "canonical_inference_provider",
    "policy_from_config",
    "require_policy_available",
]
