# SmartLife RGB grandMA3 Plugin

This repository contains a grandMA3 onPC plugin that controls Tuya/SmartLife WiFi RGB controllers over LAN by calling a local Python helper built on top of [TinyTuya](https://github.com/jasonacox/tinytuya).

The plugin supports two setup paths:

- import a prebuilt TinyTuya `snapshot.json`
- add devices manually with IP, device ID, local key, and protocol version

## Prerequisites

Before using this plugin, complete the TinyTuya setup flow so you have the device information it exports.

- TinyTuya project: https://github.com/jasonacox/tinytuya
- Run the TinyTuya setup flow first
- Obtain the exported `devices.json` / `snapshot.json`
- Import `snapshot.json` into this plugin, or copy the IP / device ID / local key into a manual device entry

The TinyTuya cloud/setup workflow is intentionally not duplicated here.

## Files

- `smartlife_rgb/smartlife_rgb.xml`
- `smartlife_rgb/smartlife_rgb.lua`
- `smartlife_rgb/smartlife_bridge.py`
- `install.sh`
- `install.bat`

## Install

Use the install helper for your platform.

macOS / Linux:

```bash
./install.sh
```

Windows:

```bat
install.bat
```

On Windows, you may need to run `install.bat` from an elevated Command Prompt or PowerShell session if writing to `C:\ProgramData` is blocked by permissions.

The installer copies the plugin into your grandMA3 user plugin directory, creates a plugin-local Python virtualenv, installs TinyTuya into that virtualenv, and updates the plugin config so grandMA3 uses that interpreter.

Default macOS target:

`$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/`

Default Windows target:

`C:\ProgramData\MALightingTechnology\gma3_library\datapools\plugins\smartlife_rgb\`

If needed, override the target base or Python executable.

macOS / Linux:

```bash
GMA3_PLUGIN_BASE="$HOME/MALightingTechnology/gma3_library/datapools/plugins" ./install.sh
PYTHON_BIN=/opt/homebrew/bin/python3 ./install.sh
```

Windows:

```bat
set GMA3_PLUGIN_BASE=C:\ProgramData\MALightingTechnology\gma3_library\datapools\plugins
set PYTHON_BIN=py
install.bat
```

Then import the plugin XML from grandMA3 onPC if it is not already present.

## Python virtualenv

The plugin is designed to use a dedicated virtualenv inside the installed plugin folder:

```bash
$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv
```

On Windows:

```bat
C:\ProgramData\MALightingTechnology\gma3_library\datapools\plugins\smartlife_rgb\.venv
```

That avoids Homebrew's externally-managed system Python restrictions and keeps the dependency isolated to this plugin.

The install helper configures `settings.python` in `smartlife_rgb_config.json` to point at:

```bash
$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv/bin/python
```

On Windows:

```bat
C:\ProgramData\MALightingTechnology\gma3_library\datapools\plugins\smartlife_rgb\.venv\Scripts\python.exe
```

If you want to create the venv manually, the steps are:

```bash
python3 -m venv "$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv"
"$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv/bin/python" -m pip install --upgrade pip
"$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv/bin/python" -m pip install tinytuya
```

If grandMA3 ever points at the wrong interpreter, run the plugin and use `Set Python path`, or call:

```text
Plugin "SmartLife RGB" "set_python path='$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/.venv/bin/python'"
```

## Interactive use

Run the plugin with no arguments to open a menu:

- list devices
- import `snapshot.json`
- add a manual device
- choose the active device
- turn devices on/off
- set RGB
- set white mode
- fetch device status

## Macro / command line use

Examples:

```text
Plugin "SmartLife RGB" "list"
Plugin "SmartLife RGB" "import_snapshot path='/Users/me/snapshot.json'"
Plugin "SmartLife RGB" "add_manual name='LED Strip' ip=192.168.1.60 id=abc key=xyz version=3.3"
Plugin "SmartLife RGB" "select device='LED Strip'"
Plugin "SmartLife RGB" "on device='LED Strip'"
Plugin "SmartLife RGB" "off device='LED Strip'"
Plugin "SmartLife RGB" "rgb device='LED Strip' r=255 g=0 b=0"
Plugin "SmartLife RGB" "white device='LED Strip' brightness=100 temp=20"
Plugin "SmartLife RGB" "status device='LED Strip'"
```

If `device=...` is omitted, the active device is used.
