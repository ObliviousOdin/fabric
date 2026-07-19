"""Nous Portal provider profile."""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class NousProfile(ProviderProfile):
    """Nous Portal reasoning integration."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        supports_reasoning: bool = False,
        **context,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Nous: passes full reasoning_config, but OMITS when disabled."""
        extra_body = {}
        if supports_reasoning:
            if reasoning_config is not None:
                rc = dict(reasoning_config)
                if rc.get("enabled") is False:
                    pass  # Nous omits reasoning when disabled
                else:
                    extra_body["reasoning"] = rc
            else:
                extra_body["reasoning"] = {"enabled": True, "effort": "medium"}
        return extra_body, {}


nous = NousProfile(
    name="nous",
    aliases=("nous-portal", "nousresearch"),
    display_name="Nous Research",
    description="Nous Research inference platform",
    signup_url="https://nousresearch.com/",
    base_url="https://inference-api.nousresearch.com/v1",
    auth_type="oauth_device_code",
)

register_provider(nous)
