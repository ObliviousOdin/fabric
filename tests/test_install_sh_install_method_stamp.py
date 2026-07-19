"""Contract test: install.sh stamps the install method next to the code tree
($INSTALL_DIR), not into the shared $FABRIC_HOME.

Background (shared-$FABRIC_HOME bug)
------------------------------------
$FABRIC_HOME is a data directory users frequently bind-mount into a Docker
gateway as well (``~/.fabric:/opt/data``). The container image stamps 'docker'
there on boot, so if install.sh had written its 'git' marker into the same
$FABRIC_HOME the two installs would fight over one slot — and the container,
booting last, would win and wrongly make the host install look like 'docker'
(blocking ``fabric update``).

The fix: detect_install_method() reads a CODE-scoped stamp first, and the
installer writes ``git`` into $INSTALL_DIR (the git checkout, e.g.
``~/.fabric/fabric-agent``), which is unique to this install and immune to the
shared data dir.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def test_install_sh_stamps_code_tree_not_home() -> None:
    text = INSTALL_SH.read_text()

    # Stamps the code tree.
    assert text.count('echo "git" > "$INSTALL_DIR/.install_method"') >= 1, (
        "install.sh must stamp $INSTALL_DIR/.install_method (code-scoped)"
    )

    # Never stamps the shared data dir.
    assert not re.search(r'>\s*"\$FABRIC_HOME/\.install_method"', text), (
        "install.sh must not stamp $FABRIC_HOME/.install_method — that data "
        "dir may be shared with a Docker gateway whose 'docker' stamp would "
        "clobber it and block host-side `fabric update`"
    )
