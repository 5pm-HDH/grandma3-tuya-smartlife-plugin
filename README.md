# SmartLife RGB grandMA3 Plugin

This repository contains a grandMA3 onPC plugin that controls Tuya/SmartLife WiFi RGB controllers over LAN by calling a local Python helper built on top of [TinyTuya](https://github.com/jasonacox/tinytuya).

The plugin supports two setup paths:

- import a prebuilt TinyTuya `snapshot.json`
- add devices manually with IP, device ID, local key, and protocol version

The TinyTuya cloud/setup workflow is intentionally not duplicated here. Run that separately first to obtain your local keys.

## Files

- `smartlife_rgb/smartlife_rgb.xml`
- `smartlife_rgb/smartlife_rgb.lua`
- `smartlife_rgb/smartlife_bridge.py`

## Install

Copy the `smartlife_rgb/` folder to your grandMA3 user plugin directory:

`$HOME/MALightingTechnology/gma3_library/datapools/plugins/smartlife_rgb/`

Then import the plugin XML from grandMA3 onPC.

## Python dependency

Install TinyTuya into the Python interpreter that grandMA3 should call:

```bash
python3 -m pip install tinytuya
```

If grandMA3 cannot find the right interpreter, run the plugin and use `Set Python path`, or call:

```text
Plugin "SmartLife RGB" "set_python path='/opt/homebrew/bin/python3'"
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
