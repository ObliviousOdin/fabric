"""``fabric link`` local device-identity and authorization commands."""

from __future__ import annotations

from typing import Callable


def build_link_parser(subparsers, *, cmd_link: Callable) -> None:
    parser = subparsers.add_parser(
        "link",
        help="Securely pair and authorize Fabric controllers",
        description=(
            "Manage per-device Fabric Link identity, grants, and revocation. "
            "No GitHub, Google, password, or dashboard token is used."
        ),
    )
    actions = parser.add_subparsers(dest="link_action")

    setup = actions.add_parser("setup", help="Initialize Fabric Link on this machine")
    setup.add_argument(
        "--relay",
        default="",
        help="Relay HTTPS origin or WSS /link URL (may be configured later)",
    )

    enable = actions.add_parser("enable", help="Enable Link and create machine identity")
    enable.add_argument(
        "--relay",
        default="",
        help="Relay HTTPS origin or WSS /link URL (may be configured later)",
    )

    actions.add_parser(
        "disable",
        help="Disable Link networking while preserving identity and paired devices",
    )

    status = actions.add_parser("status", help="Show Link identity and local state")
    status.add_argument("--json", action="store_true", dest="json_output")

    core = actions.add_parser(
        "core",
        help="Inspect or install the native OpenMLS companion",
    )
    core.set_defaults(link_action="core", core_action="status")
    core_actions = core.add_subparsers(dest="core_action")
    core_status = core_actions.add_parser(
        "status",
        help="Verify the installed native core and protocol contract",
    )
    core_status.set_defaults(link_action="core")
    core_status.add_argument("--json", action="store_true", dest="json_output")
    core_install = core_actions.add_parser(
        "install",
        help="Install a verified release wheel or build from this source checkout",
    )
    core_install.set_defaults(link_action="core")
    source = core_install.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--wheel",
        default="",
        help="Platform wheel downloaded from the same Fabric release",
    )
    source.add_argument(
        "--from-source",
        action="store_true",
        help="Build the pinned OpenMLS core from this Fabric checkout",
    )
    core_install.add_argument(
        "--sha256",
        default="",
        help="Required release-manifest SHA-256 when --wheel is used",
    )

    pair = actions.add_parser(
        "pair",
        help="Pair one controller with local approval",
        description=(
            "Print a v3 pairing QR, receive the encrypted controller request "
            "through the configured blind relay, and require local approval. "
            "The request/response file flags enable an offline manual fallback."
        ),
    )
    pair.add_argument(
        "controller",
        nargs="?",
        choices=("mobile", "desktop", "web"),
        default="mobile",
    )
    pair.add_argument("--name", default="", help="Optional controller label hint")
    pair.add_argument(
        "--grants",
        default="observe,chat,dispatch",
        help="Maximum requested grants (comma-separated)",
    )
    pair.add_argument(
        "--relay",
        default="",
        help="Override the configured relay origin for this pairing",
    )
    pair.add_argument(
        "--request-file",
        default="",
        help="One-time encrypted enrollment request file",
    )
    pair.add_argument(
        "--response-file",
        default="",
        help="New file to receive the encrypted enrollment response",
    )

    devices = actions.add_parser("devices", help="List paired controllers and grants")
    devices.add_argument("--json", action="store_true", dest="json_output")

    grant = actions.add_parser("grant", help="Replace one controller's local grants")
    grant.add_argument("device", help="Exact device id or unambiguous id prefix")
    grant.add_argument(
        "--preset",
        choices=("standard", "observe", "dispatch"),
        default="",
    )
    grant.add_argument(
        "--grants",
        default="",
        help="Custom comma-separated grants",
    )
    grant.add_argument(
        "--approve",
        action="store_true",
        help="Also grant approval/clarification authority",
    )

    revoke = actions.add_parser(
        "revoke",
        help="Deny a controller locally, then remove it from its MLS group",
    )
    revoke.add_argument("device", help="Exact device id or unambiguous id prefix")
    revoke.add_argument(
        "--yes",
        action="store_true",
        help="Confirm revocation without an additional prompt",
    )

    host = actions.add_parser(
        "host",
        help="Run the outbound-only Fabric Link host broker",
    )
    host.add_argument(
        "--relay",
        default="",
        help="Override the configured relay origin",
    )
    host.add_argument(
        "--once",
        action="store_true",
        help="Poll once, flush pending encrypted responses, and exit",
    )

    controller = actions.add_parser(
        "controller",
        help="Manage this device as a controller for other Fabric machines",
    )
    controller_actions = controller.add_subparsers(dest="controller_action")
    controller_pair = controller_actions.add_parser(
        "pair",
        help="Pair this terminal or Desktop backend from a Fabric Link QR",
    )
    controller_pair.set_defaults(link_action="controller_pair")
    controller_pair.add_argument(
        "pairing_url",
        help="The fabric-link-v3 pairing URL copied from the target machine",
    )
    controller_pair.add_argument(
        "--name",
        default="Fabric controller",
        help="Controller name shown during local approval",
    )
    controller_pair.add_argument(
        "--platform",
        choices=("cli", "desktop"),
        default="cli",
        help="Controller surface whose protected store will own the pairing",
    )
    controller_pair.add_argument(
        "--grants",
        default="observe,chat,dispatch",
        help="Requested grants, limited by the target machine's pairing QR",
    )

    controller_list = controller_actions.add_parser(
        "list",
        help="List machines paired to this controller",
    )
    controller_list.set_defaults(link_action="controller_list")
    controller_list.add_argument("--json", action="store_true", dest="json_output")

    call = actions.add_parser(
        "call",
        help="Invoke one reviewed Link RPC on a paired machine",
    )
    call.add_argument("controller", help="Exact controller profile id or id prefix")
    call.add_argument("method", help="Reviewed Fabric gateway RPC method")
    call.add_argument(
        "--params-json",
        default="{}",
        help="RPC parameters as one JSON object",
    )
    call.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the encrypted response",
    )

    dispatch = actions.add_parser(
        "dispatch",
        help="Start separate durable Work on a paired machine",
    )
    dispatch.add_argument("controller", help="Exact controller profile id or id prefix")
    dispatch.add_argument("prompt", help="Prompt for the new background Work job")
    dispatch.add_argument(
        "--title",
        default="Dispatched from Fabric Link",
        help="Optional Work title",
    )
    dispatch.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the encrypted job receipt",
    )

    relay = actions.add_parser(
        "relay",
        help="Run or inspect a self-hosted blind relay",
    )
    relay_actions = relay.add_subparsers(dest="relay_action")
    relay_serve = relay_actions.add_parser(
        "serve",
        help="Run the reference relay behind a TLS reverse proxy",
    )
    relay_serve.set_defaults(link_action="relay_serve")
    relay_serve.add_argument(
        "--origin",
        required=True,
        help="Public HTTPS origin controllers pin, for example https://link.example.com",
    )
    relay_serve.add_argument(
        "--database",
        required=True,
        help="Private SQLite path for opaque relay queues",
    )
    relay_serve.add_argument("--bind", default="127.0.0.1")
    relay_serve.add_argument("--port", type=int, default=8787)
    relay_serve.add_argument(
        "--behind-tls-proxy",
        action="store_true",
        help="Required for a non-loopback bind; confirms TLS terminates upstream",
    )

    service = actions.add_parser(
        "service",
        help="Manage the always-available current-user Link host",
    )
    service_actions = service.add_subparsers(dest="service_action")
    service_install = service_actions.add_parser(
        "install",
        help="Install and start the outbound-only broker at login",
    )
    service_install.set_defaults(link_action="service")
    service_install.add_argument(
        "--workspace",
        default="",
        help="Default working directory for Link-dispatched Work",
    )
    service_install.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing Fabric-managed Link service definition",
    )
    service_install.add_argument(
        "--no-start-now",
        action="store_false",
        dest="start_now",
        default=True,
        help="Install without starting the broker immediately",
    )
    service_install.add_argument(
        "--no-start-on-login",
        action="store_false",
        dest="start_on_login",
        default=True,
        help="Do not enable the broker at the next login",
    )
    for service_action in ("start", "stop", "restart", "uninstall"):
        command = service_actions.add_parser(
            service_action,
            help=f"{service_action.capitalize()} the Link host service",
        )
        command.set_defaults(link_action="service")
    service_status = service_actions.add_parser(
        "status",
        help="Show installation and runtime state",
    )
    service_status.set_defaults(link_action="service")
    service_status.add_argument("--json", action="store_true", dest="json_output")

    reset = actions.add_parser(
        "reset",
        help="Destroy this machine's Link identity and all paired-device state",
    )
    reset.add_argument(
        "--confirm",
        required=True,
        help="Current machine fingerprint shown by `fabric link status`",
    )

    parser.set_defaults(func=cmd_link)
