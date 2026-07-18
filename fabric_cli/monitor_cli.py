"""``fabric monitor`` — a live terminal view of this machine's health.

Renders CPU (aggregate + per-core), memory, disk, load average, network
throughput and GPU utilisation, refreshing in place. Shares
:func:`fabric_cli.system_stats.collect_dynamic_stats` with the web dashboard's
Host card and the desktop app so the three surfaces never disagree on which
metrics exist or how a throughput rate is computed.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from typing import Any, Dict, List, Optional

from fabric_cli.system_stats import collect_dynamic_stats

_LEVELS = " ▁▂▃▄▅▆▇█"


def _tone(pct: float) -> str:
    if pct >= 85:
        return "red"
    if pct >= 60:
        return "yellow"
    return "green"


def _level_char(pct: float) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    idx = int(pct / 100 * (len(_LEVELS) - 1) + 0.5)
    return _LEVELS[idx]


def _fmt_bytes(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    if n < 1024:
        return f"{n:.0f}B"
    if n < 1024**2:
        return f"{n / 1024:.0f}K"
    if n < 1024**3:
        return f"{n / 1024**2:.0f}M"
    return f"{n / 1024**3:.1f}G"


def _fmt_rate(bps: Optional[float]) -> str:
    if bps is None:
        return "—"
    bps = max(0.0, float(bps))
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024**2:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps / 1024**2:.1f} MB/s"


def _fmt_duration(seconds: int) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _identity() -> Dict[str, Any]:
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "hostname": platform.node(),
    }


def snapshot(disk_path: Optional[str] = None) -> Dict[str, Any]:
    """Identity block + the shared dynamic metrics, as one JSON-safe dict."""
    info = _identity()
    info.update(collect_dynamic_stats(disk_path))
    return info


def _bar(pct: float, width: int = 20):
    from rich.text import Text

    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(pct / 100 * width))
    t = Text()
    t.append("█" * filled, style=_tone(pct))
    t.append("░" * (width - filled), style="dim")
    return t


def _metric_line(label: str, pct: float, suffix: str = ""):
    from rich.text import Text

    t = Text()
    t.append(f"{label:<4} ", style="dim")
    t.append_text(_bar(pct))
    t.append(f" {pct:>3.0f}%", style="bold")
    if suffix:
        t.append(f"  {suffix}", style="dim")
    return t


def _render(snap: Dict[str, Any]):
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    lines: List[Any] = []

    header = Text()
    header.append(str(snap.get("hostname") or "host"), style="bold")
    os_l = f"{snap.get('os', '')} {snap.get('os_release', '')}".strip()
    header.append(f"  {os_l}  {snap.get('arch', '')}", style="dim")
    up = snap.get("uptime_seconds")
    if isinstance(up, (int, float)):
        header.append(f"  up {_fmt_duration(int(up))}", style="dim")
    lines.append(header)
    lines.append(Text(""))

    if not snap.get("psutil"):
        lines.append(
            Text(
                "psutil not installed — install the psutil extra for "
                "CPU / memory / disk / network metrics.",
                style="yellow",
            )
        )
        return Panel(
            Group(*lines),
            title="fabric · infra",
            border_style="magenta",
            padding=(0, 1),
        )

    cpu = snap.get("cpu_percent")
    if cpu is not None:
        cores = snap.get("cpu_count")
        lines.append(_metric_line("cpu", cpu, f"{cores}c" if cores else ""))
    per_cpu = snap.get("per_cpu_percent")
    if per_cpu:
        strip = Text("     ")
        for v in per_cpu:
            strip.append(_level_char(v), style=_tone(v))
        lines.append(strip)

    mem = snap.get("memory")
    if mem:
        lines.append(
            _metric_line(
                "mem",
                mem["percent"],
                f"{_fmt_bytes(mem['used'])}/{_fmt_bytes(mem['total'])}",
            )
        )
    disk = snap.get("disk")
    if disk:
        lines.append(
            _metric_line(
                "dsk",
                disk["percent"],
                f"{_fmt_bytes(disk['used'])}/{_fmt_bytes(disk['total'])}",
            )
        )
    load = snap.get("load_avg")
    if load:
        lines.append(
            Text("ld   " + " / ".join(f"{x:.2f}" for x in load), style="default")
        )

    net = snap.get("net")
    if net:
        line = Text("net  ")
        line.append("↓ ", style="dim")
        line.append(_fmt_rate(net.get("recv_per_sec")), style="cyan")
        line.append("   ↑ ", style="dim")
        line.append(_fmt_rate(net.get("sent_per_sec")), style="green")
        lines.append(line)

    for g in snap.get("gpus") or []:
        lines.append(_metric_line("gpu", g["util_percent"], str(g.get("name", ""))))
        if g.get("mem_percent") is not None:
            lines.append(
                _metric_line(
                    "vram",
                    g["mem_percent"],
                    f"{_fmt_bytes(g['mem_used'])}/{_fmt_bytes(g['mem_total'])}",
                )
            )

    return Panel(
        Group(*lines),
        title="fabric · infra",
        subtitle="Ctrl-C to quit",
        border_style="magenta",
        padding=(0, 1),
    )


def cmd_monitor(args) -> int:
    interval = getattr(args, "interval", 2.0) or 2.0
    interval = max(0.5, float(interval))
    as_json = bool(getattr(args, "json", False))
    once = bool(getattr(args, "once", False))

    if as_json:
        # Prime the network counters, wait briefly, then sample so the rate
        # fields are populated rather than null on the very first read.
        collect_dynamic_stats()
        time.sleep(min(interval, 1.0))
        print(json.dumps(snapshot(), indent=2, default=str))
        return 0

    try:
        from rich.console import Console
        from rich.live import Live
    except Exception:
        # rich is a declared dependency, but degrade to plain text rather
        # than crash if it is somehow unavailable.
        snap = snapshot()
        print(f"{snap.get('hostname')}  cpu {snap.get('cpu_percent')}%  ")
        return 0

    console = Console()

    # A non-interactive stdout (piped / redirected) can't host a live view.
    if once or not sys.stdout.isatty():
        console.print(_render(snapshot()))
        return 0

    # Seed the net counters so the first visible frame already shows a rate.
    collect_dynamic_stats()
    try:
        with Live(
            _render(snapshot()),
            console=console,
            screen=True,
            refresh_per_second=4,
        ) as live:
            while True:
                time.sleep(interval)
                live.update(_render(snapshot()))
    except KeyboardInterrupt:
        pass
    return 0
