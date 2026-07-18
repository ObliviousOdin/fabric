"""CLI helpers for configuring Mixture of Agents."""

from __future__ import annotations

from typing import Any

from fabric_cli.config import load_config, save_config
from fabric_cli.inventory import build_models_payload, load_picker_context
from fabric_cli.moa_config import DEFAULT_MOA_PRESET_NAME, normalize_moa_config


def _prompt_choice(title: str, rows: list[str], default: int = 0) -> int:
    try:
        from fabric_cli.curses_ui import curses_radiolist

        return curses_radiolist(title, rows, selected=default, cancel_returns=default)
    except Exception:
        for idx, row in enumerate(rows, start=1):
            print(f"{idx}. {row}")
        raw = input(f"{title} [{default + 1}]: ").strip()
        if not raw:
            return default
        try:
            return max(0, min(len(rows) - 1, int(raw) - 1))
        except ValueError:
            return default


def _model_options(*, refresh_models: bool = False) -> list[dict[str, Any]]:
    payload = build_models_payload(
        load_picker_context(),
        include_unconfigured=True,
        picker_hints=True,
        canonical_order=True,
        pricing=False,
        refresh=refresh_models,
    )
    providers = payload.get("providers") or []
    return [p for p in providers if p.get("slug") and p.get("models")]


_SUBSCRIPTION_PLAN_PRESET = "subscription-plan"
_SUBSCRIPTION_REVIEW_PRESET = "subscription-review"

_SUBSCRIPTION_MODEL_PREFERENCES = {
    "gpt_aggregator": (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6",
        "gpt-5.5-codex",
        "gpt-5.5",
    ),
    "gpt_reference": (
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "gpt-5.6",
        "gpt-5.5-codex",
        "gpt-5.5",
    ),
    "grok_critic": (
        "grok-4.5",
        "grok-4.20-0309-reasoning",
        "grok-4.3",
        "grok-4.2",
    ),
    "grok_worker": (
        "grok-composer-2.5-fast",
        "grok-build-0.1",
    ),
}


def _subscription_catalog(*, refresh_models: bool = True) -> dict[str, set[str]]:
    """Return authenticated subscription-provider models only."""
    catalog: dict[str, set[str]] = {}
    for provider in _model_options(refresh_models=refresh_models):
        slug = str(provider.get("slug") or "").strip().lower()
        if slug not in {"openai-codex", "xai-oauth"}:
            continue
        if not provider.get("authenticated"):
            continue
        catalog[slug] = {
            str(model).strip()
            for model in provider.get("models") or []
            if str(model).strip()
        }
    return catalog


def _preferred_model(available: set[str], preferences: tuple[str, ...], lane: str) -> str:
    for model in preferences:
        if model in available:
            return model
    wanted = ", ".join(preferences)
    raise RuntimeError(f"No supported model found for {lane}. Looked for: {wanted}")


def build_subscription_moa_presets(
    catalog: dict[str, set[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Build subscription-backed planning/review presets from a live catalog."""
    openai_models = catalog.get("openai-codex") or set()
    xai_models = catalog.get("xai-oauth") or set()
    if not openai_models:
        raise RuntimeError(
            "OpenAI Codex subscription models are unavailable. Run `fabric auth add openai-codex`."
        )
    if not xai_models:
        raise RuntimeError(
            "xAI subscription models are unavailable. Run `fabric auth add xai-oauth`."
        )

    chosen = {
        "gpt_aggregator": _preferred_model(
            openai_models,
            _SUBSCRIPTION_MODEL_PREFERENCES["gpt_aggregator"],
            "GPT aggregator",
        ),
        "gpt_reference": _preferred_model(
            openai_models,
            _SUBSCRIPTION_MODEL_PREFERENCES["gpt_reference"],
            "GPT implementation reviewer",
        ),
        "grok_critic": _preferred_model(
            xai_models,
            _SUBSCRIPTION_MODEL_PREFERENCES["grok_critic"],
            "Grok adversarial reviewer",
        ),
        "grok_worker": _preferred_model(
            xai_models,
            _SUBSCRIPTION_MODEL_PREFERENCES["grok_worker"],
            "Grok coding worker",
        ),
    }

    def slot(provider: str, model: str, role: str, instructions: str, effort: str) -> dict[str, str]:
        return {
            "provider": provider,
            "model": model,
            "role": role,
            "instructions": instructions,
            "reasoning_effort": effort,
        }

    presets = {
        _SUBSCRIPTION_PLAN_PRESET: {
            "reference_models": [
                slot(
                    "xai-oauth",
                    chosen["grok_critic"],
                    "adversarial planner",
                    "Challenge assumptions, find hidden failure modes and security risks, and explain why the preferred plan could fail.",
                    "high",
                ),
                slot(
                    "openai-codex",
                    chosen["gpt_reference"],
                    "implementation feasibility reviewer",
                    "Check repository fit, implementation sequence, compatibility, testability, and the smallest complete patch.",
                    "low",
                ),
            ],
            "aggregator": slot(
                "openai-codex",
                chosen["gpt_aggregator"],
                "architecture owner",
                "Reconcile disagreements against the task brief and acceptance criteria; return one executable plan rather than a vote.",
                "high",
            ),
            "reference_max_tokens": 700,
            "fanout": "user_turn",
            "enabled": True,
        },
        _SUBSCRIPTION_REVIEW_PRESET: {
            "reference_models": [
                slot(
                    "xai-oauth",
                    chosen["grok_critic"],
                    "adversarial patch reviewer",
                    "Look for regressions, security issues, untested edge cases, unjustified scope, and reasons each candidate should be rejected.",
                    "high",
                ),
                slot(
                    "openai-codex",
                    chosen["gpt_reference"],
                    "correctness and maintainability reviewer",
                    "Compare only validated candidates against the task brief, public contracts, repository conventions, and deterministic evidence.",
                    "low",
                ),
            ],
            "aggregator": slot(
                "openai-codex",
                chosen["gpt_aggregator"],
                "merge decision owner",
                "Choose A, B, or a precisely described hybrid only from viable evidence. Never prefer explanation quality over correctness.",
                "high",
            ),
            "reference_max_tokens": 700,
            "fanout": "user_turn",
            "enabled": True,
        },
    }
    return presets, chosen


def _pick_slot(current: dict[str, Any] | None = None) -> dict[str, Any]:
    providers = _model_options()
    if not providers:
        raise RuntimeError("No configured model providers found. Run `fabric model` first.")
    current_provider = (current or {}).get("provider", "")
    provider_default = next(
        (idx for idx, p in enumerate(providers) if p.get("slug") == current_provider),
        0,
    )
    provider_rows = [f"{p.get('name') or p.get('slug')}  ({p.get('slug')})" for p in providers]
    provider = providers[_prompt_choice("Select provider", provider_rows, provider_default)]
    models = list(provider.get("models") or [])
    if not models:
        raise RuntimeError(f"Provider {provider.get('slug')} has no selectable models")
    current_model = (current or {}).get("model", "")
    model_default = models.index(current_model) if current_model in models else 0
    model = models[_prompt_choice(f"Select model for {provider.get('slug')}", models, model_default)]
    # Keep additive slot metadata (role/instructions/reasoning_effort) when the
    # interactive picker changes only the provider/model identity.
    selected = dict(current or {})
    selected.update({"provider": str(provider.get("slug") or ""), "model": str(model)})
    return selected


def _print_config(config: dict[str, Any]) -> None:
    cfg = normalize_moa_config(config.get("moa") if isinstance(config, dict) else {})
    print("Mixture of Agents presets")
    print(f"Default: {cfg['default_preset']}")
    active = cfg.get("active_preset") or "(off)"
    print(f"Active in config: {active}")
    for name, preset in cfg["presets"].items():
        marker = "*" if name == cfg["default_preset"] else " "
        print(f"\n{marker} {name}")
        print("  Reference models:")
        for idx, slot in enumerate(preset["reference_models"], start=1):
            role = f" [{slot['role']}]" if slot.get("role") else ""
            effort = f" reasoning={slot['reasoning_effort']}" if slot.get("reasoning_effort") else ""
            print(f"    {idx}. {slot['provider']}:{slot['model']}{role}{effort}")
        agg = preset["aggregator"]
        agg_role = f" [{agg['role']}]" if agg.get("role") else ""
        agg_effort = f" reasoning={agg['reasoning_effort']}" if agg.get("reasoning_effort") else ""
        print(f"  Aggregator: {agg['provider']}:{agg['model']}{agg_role}{agg_effort}")
        print(
            f"  Cadence: {preset.get('fanout', 'per_iteration')} · "
            f"reference cap: {preset.get('reference_max_tokens') or 'provider default'}"
        )


def cmd_moa(args) -> None:
    """Manage Mixture of Agents model presets."""
    cfg = load_config()
    sub = getattr(args, "moa_command", None) or "list"

    if sub in {"list", "ls"}:
        _print_config(cfg)
        return

    if sub == "bootstrap":
        template = str(getattr(args, "template", None) or "subscriptions").strip().lower()
        if template != "subscriptions":
            raise SystemExit(f"Unknown MoA bootstrap template: {template}")
        try:
            catalog = _subscription_catalog(
                refresh_models=not bool(getattr(args, "cached", False))
            )
            presets, chosen = build_subscription_moa_presets(catalog)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

        moa = normalize_moa_config(cfg.get("moa") if isinstance(cfg, dict) else {})
        generated = normalize_moa_config(
            {"default_preset": _SUBSCRIPTION_PLAN_PRESET, "presets": presets}
        )["presets"]
        conflicts = [
            name
            for name, preset in generated.items()
            if name in moa["presets"] and moa["presets"][name] != preset
        ]
        dry_run = bool(getattr(args, "dry_run", False))
        if conflicts and not bool(getattr(args, "force", False)) and not dry_run:
            names = ", ".join(conflicts)
            raise SystemExit(
                f"Refusing to overwrite existing MoA preset(s): {names}. "
                "Re-run with --force after reviewing `fabric moa bootstrap subscriptions --dry-run`."
            )

        moa["presets"].update(generated)
        if not bool(getattr(args, "keep_default", False)):
            moa["default_preset"] = _SUBSCRIPTION_PLAN_PRESET
        next_config = dict(cfg)
        next_config["moa"] = normalize_moa_config(moa)

        action = "Would install" if dry_run else "Installed"
        print(f"{action} subscription-backed MoA presets:")
        print(f"  {_SUBSCRIPTION_PLAN_PRESET}")
        print(f"  {_SUBSCRIPTION_REVIEW_PRESET}")
        print("Selected live subscription models:")
        print(f"  GPT aggregator: openai-codex:{chosen['gpt_aggregator']}")
        print(f"  GPT reviewer: openai-codex:{chosen['gpt_reference']}")
        print(f"  Grok critic: xai-oauth:{chosen['grok_critic']}")
        print(f"  Grok coding worker: xai-oauth:{chosen['grok_worker']}")
        if conflicts and dry_run:
            print(f"Would replace with --force: {', '.join(conflicts)}")
        if dry_run:
            print("Dry run only; config was not changed.")
        else:
            save_config(next_config)
            _print_config(next_config)
        return

    if sub in {"config", "configure"}:
        moa = normalize_moa_config(cfg.get("moa") if isinstance(cfg, dict) else {})
        preset_name = (getattr(args, "name", None) or moa.get("default_preset") or DEFAULT_MOA_PRESET_NAME).strip()
        current = moa["presets"].get(preset_name, moa["presets"][moa["default_preset"]])
        print(f"Configure MoA preset: {preset_name}")
        print("Pick at least one reference model; choose Done when finished.")
        refs: list[dict[str, str]] = []
        existing = list(current.get("reference_models") or [])
        idx = 0
        while True:
            base = existing[idx] if idx < len(existing) else None
            refs.append(_pick_slot(base))
            idx += 1
            choice = _prompt_choice("Add another reference model?", ["Add another", "Done"], 1)
            if choice == 1:
                break
        print("Configure aggregator model.")
        current = dict(current)
        current["reference_models"] = refs
        current["aggregator"] = _pick_slot(current.get("aggregator"))
        moa["presets"][preset_name] = current
        moa.setdefault("default_preset", preset_name)
        cfg["moa"] = normalize_moa_config(moa)
        save_config(cfg)
        print(f"Saved MoA preset: {preset_name}")
        _print_config(cfg)
        return

    if sub == "delete":
        moa = normalize_moa_config(cfg.get("moa") if isinstance(cfg, dict) else {})
        preset_name = (getattr(args, "name", None) or "").strip()
        if not preset_name:
            raise SystemExit("Usage: fabric moa delete <name>")
        if preset_name not in moa["presets"]:
            raise SystemExit(f"Unknown MoA preset: {preset_name}")
        if len(moa["presets"]) <= 1:
            raise SystemExit("Cannot delete the only MoA preset")
        del moa["presets"][preset_name]
        if moa["default_preset"] == preset_name:
            moa["default_preset"] = next(iter(moa["presets"]))
        if moa.get("active_preset") == preset_name:
            moa["active_preset"] = ""
        cfg["moa"] = normalize_moa_config(moa)
        save_config(cfg)
        print(f"Deleted MoA preset: {preset_name}")
        return

    raise SystemExit(f"Unknown moa subcommand: {sub}")
