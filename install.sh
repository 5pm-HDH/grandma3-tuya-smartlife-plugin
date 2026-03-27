#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="smartlife_rgb"
SOURCE_DIR="$ROOT_DIR/$PLUGIN_NAME"
TARGET_BASE="${GMA3_PLUGIN_BASE:-$HOME/MALightingTechnology/gma3_library/datapools/plugins}"
TARGET_DIR="$TARGET_BASE/$PLUGIN_NAME"
VENV_DIR="$TARGET_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_PATH="$TARGET_DIR/smartlife_rgb_config.json"
VENV_PYTHON="$VENV_DIR/bin/python"

echo "Installing plugin to: $TARGET_DIR"
mkdir -p "$TARGET_DIR"

cp -f "$SOURCE_DIR/smartlife_rgb.lua" "$TARGET_DIR/"
cp -f "$SOURCE_DIR/smartlife_rgb.xml" "$TARGET_DIR/"
cp -f "$SOURCE_DIR/smartlife_bridge.py" "$TARGET_DIR/"

echo "Creating/updating virtualenv: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install tinytuya

echo "Writing/updating plugin config: $CONFIG_PATH"
CONFIG_PATH="$CONFIG_PATH" VENV_PYTHON="$VENV_PYTHON" "$VENV_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

config_path = Path(os.environ["CONFIG_PATH"])
venv_python = os.environ["VENV_PYTHON"]

if config_path.exists():
    data = json.loads(config_path.read_text(encoding="utf-8"))
else:
    data = {}

if not isinstance(data, dict):
    raise SystemExit("Existing config is not a JSON object")

data.setdefault("settings", {})
data["settings"]["python"] = venv_python
data.setdefault("devices", [])
data.setdefault("active_device", None)

config_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo
echo "Install complete."
echo "Plugin files: $TARGET_DIR"
echo "Python: $VENV_PYTHON"
echo
echo "Next steps:"
echo "1. Import $TARGET_DIR/smartlife_rgb.xml in grandMA3 onPC if needed."
echo "2. Run the plugin and import your TinyTuya snapshot.json, or add devices manually."
