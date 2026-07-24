#!/usr/bin/env bash
set -euo pipefail
G="\033[0;32m"; R="\033[0;31m"; N="\033[0m"
ok() { echo -e "  ${G}+${N} $1"; }
fail() { echo -e "  ${R}x${N} $1"; }

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${FABRIC_HOME:-$HOME/.fabric}/text-to-cad/venv"
REQUIREMENTS="$SKILL_DIR/requirements.txt"

echo ""; echo "Text-to-CAD Skill — Environment Setup"; echo ""

command -v python3 &>/dev/null || { fail "Python 3 not found"; exit 1; }
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  && ok "Python $PYVER" \
  || { fail "Python >= 3.11 required (found $PYVER)"; exit 1; }

if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c "import build123d, stl, matplotlib" &>/dev/null; then
  ok "venv ready: $VENV_DIR"
else
  mkdir -p "$(dirname "$VENV_DIR")"
  if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR" --python 3.11 --quiet
    uv pip install --python "$VENV_DIR/bin/python" --quiet -r "$REQUIREMENTS"
    ok "venv created with uv"
  else
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
    ok "venv created with pip"
  fi
  "$VENV_DIR/bin/python" -c "import build123d, stl, matplotlib" \
    && ok "build123d + numpy-stl + matplotlib importable" \
    || { fail "install verification failed"; exit 1; }
fi

echo ""
echo -e "${G}Environment ready.${N} Interpreter:"
echo "$VENV_DIR/bin/python"
echo ""
