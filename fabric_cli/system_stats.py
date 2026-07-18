"""Shared host/system stats collection.

A single collector for the dynamic device metrics rendered by the web
dashboard's Host card (``GET /api/system/stats``), the desktop app's Host
monitor, and the ``fabric monitor`` CLI. Keeping one implementation here
stops the three surfaces from drifting on which metrics exist or how a rate
is computed.

Everything is best-effort: ``psutil`` enriches the picture when present, and
network throughput / GPU utilisation degrade to absent (never an error) on
hosts that don't expose them. The functions are synchronous and safe to run
off the event loop via ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

# Network counters are cumulative byte totals; a throughput rate is the delta
# between two samples over the elapsed time. We remember the previous sample
# per process so successive calls (each web poll, each CLI frame) yield a rate.
_net_lock = threading.Lock()
_last_net: Optional[tuple[float, int, int]] = None  # (monotonic_ts, sent, recv)


def _default_disk_path() -> str:
    try:
        from fabric_constants import get_fabric_home

        return str(get_fabric_home())
    except Exception:
        return os.path.abspath(os.sep)


def _collect_net(psutil) -> Optional[Dict[str, Any]]:
    """Cumulative net counters plus a per-second rate since the last call.

    ``sent_per_sec`` / ``recv_per_sec`` are ``None`` on the first sample (no
    prior reading) and whenever a counter appears to reset (interface reset,
    container restart) so a negative delta never surfaces as a bogus rate.
    """
    global _last_net
    try:
        io = psutil.net_io_counters()
    except Exception:
        return None
    now = time.monotonic()
    sent = int(io.bytes_sent)
    recv = int(io.bytes_recv)
    sent_rate: Optional[float] = None
    recv_rate: Optional[float] = None
    with _net_lock:
        prev = _last_net
        _last_net = (now, sent, recv)
    if prev is not None:
        prev_t, prev_sent, prev_recv = prev
        dt = now - prev_t
        if dt > 0:
            ds = sent - prev_sent
            dr = recv - prev_recv
            if ds >= 0 and dr >= 0:
                sent_rate = ds / dt
                recv_rate = dr / dt
    return {
        "bytes_sent": sent,
        "bytes_recv": recv,
        "sent_per_sec": sent_rate,
        "recv_per_sec": recv_rate,
    }


def _gpu_from_nvml() -> Optional[List[Dict[str, Any]]]:
    """NVIDIA GPUs via the ``pynvml`` bindings when installed (fastest path)."""
    try:
        import pynvml  # type: ignore
    except Exception:
        return None
    try:
        pynvml.nvmlInit()
    except Exception:
        return None
    out: List[Dict[str, Any]] = []
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            total = int(mem.total)
            used = int(mem.used)
            out.append(
                {
                    "name": name,
                    "util_percent": float(util.gpu),
                    "mem_used": used,
                    "mem_total": total,
                    "mem_percent": round(used / total * 100, 1) if total else None,
                }
            )
    except Exception:
        return out or None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return out or None


def _gpu_from_smi() -> Optional[List[Dict[str, Any]]]:
    """NVIDIA GPUs via the ``nvidia-smi`` CLI (no extra dependency)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [
                exe,
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out: List[Dict[str, Any]] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            name = parts[0]
            util = float(parts[1])
            used = int(float(parts[2]) * 1024 * 1024)  # MiB -> bytes
            total = int(float(parts[3]) * 1024 * 1024)
        except (ValueError, IndexError):
            continue
        out.append(
            {
                "name": name,
                "util_percent": util,
                "mem_used": used,
                "mem_total": total,
                "mem_percent": round(used / total * 100, 1) if total else None,
            }
        )
    return out or None


def _collect_gpu() -> Optional[List[Dict[str, Any]]]:
    """Best-effort GPU list; ``None`` when no supported GPU is detectable."""
    return _gpu_from_nvml() or _gpu_from_smi()


def collect_dynamic_stats(disk_path: Optional[str] = None) -> Dict[str, Any]:
    """Return the dynamic (changing) host metrics as a JSON-safe dict.

    Callers assemble their own identity block (OS, arch, version) and merge
    this in. Keys mirror the historical ``/api/system/stats`` payload and add
    ``per_cpu_percent`` (per-core load), ``net`` (throughput), and ``gpus``.
    """
    info: Dict[str, Any] = {}
    if disk_path is None:
        disk_path = _default_disk_path()

    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        info["memory"] = {
            "total": vm.total,
            "available": vm.available,
            "used": vm.used,
            "percent": vm.percent,
        }
        try:
            du = psutil.disk_usage(disk_path)
            info["disk"] = {
                "total": du.total,
                "used": du.used,
                "free": du.free,
                "percent": du.percent,
            }
        except Exception:
            pass
        try:
            # One sampling window yields both the per-core and aggregate load.
            per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
            if per_cpu:
                info["per_cpu_percent"] = list(per_cpu)
                info["cpu_percent"] = round(sum(per_cpu) / len(per_cpu), 1)
            la = getattr(psutil, "getloadavg", None)
            if la:
                info["load_avg"] = list(la())
        except Exception:
            pass
        try:
            info["uptime_seconds"] = int(time.time() - psutil.boot_time())
        except Exception:
            pass
        try:
            proc = psutil.Process()
            info["process"] = {
                "pid": proc.pid,
                "rss": proc.memory_info().rss,
                "create_time": int(proc.create_time()),
                "num_threads": proc.num_threads(),
            }
        except Exception:
            pass
        net = _collect_net(psutil)
        if net is not None:
            info["net"] = net
        info["psutil"] = True
    except Exception:
        info["psutil"] = False
        # stdlib-only fallback for load average where the kernel exposes it.
        try:
            info["load_avg"] = list(os.getloadavg())
        except (OSError, AttributeError):
            pass

    gpus = _collect_gpu()
    if gpus:
        info["gpus"] = gpus

    return info
