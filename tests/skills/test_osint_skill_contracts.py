from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "research"
    / "osint-investigation"
)


def load_script(name: str):
    path = SKILL_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"osint_{path.stem}_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"ok"


def test_http_uses_fabric_user_agent_override(monkeypatch):
    mod = load_script("_http.py")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("FABRIC_OSINT_UA", "fabric-audit/1.0 (ops@example.com)")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    assert mod.get("https://example.test/data") == b"ok"
    assert seen["request"].get_header("User-agent") == "fabric-audit/1.0 (ops@example.com)"
    assert seen["timeout"] == 30.0


def test_explicit_user_agent_precedes_environment(monkeypatch):
    mod = load_script("_http.py")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return _Response()

    monkeypatch.setenv("FABRIC_OSINT_UA", "fabric-environment/1.0")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    mod.get("https://example.test/data", user_agent="test-client/2.0")

    assert seen["request"].get_header("User-agent") == "test-client/2.0"


def test_icij_cache_uses_fabric_cache_root(monkeypatch, tmp_path: Path):
    mod = load_script("fetch_icij_offshore.py")
    cache_root = tmp_path / "shared-osint-cache"
    monkeypatch.setenv("FABRIC_OSINT_CACHE", str(cache_root))

    assert mod._cache_dir() == cache_root / "icij"


def test_icij_cache_has_stable_default(monkeypatch, tmp_path: Path):
    mod = load_script("fetch_icij_offshore.py")
    monkeypatch.delenv("FABRIC_OSINT_CACHE", raising=False)
    monkeypatch.setattr(mod.Path, "home", lambda: tmp_path)

    assert mod._cache_dir() == tmp_path / ".cache" / "fabric-osint" / "icij"
