#!/usr/bin/env python3
"""TinyTuya-backed helper for the grandMA3 SmartLife RGB plugin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VERSION_CANDIDATES = ("3.4", "3.3", "3.5", "3.1")


def response(ok: bool, message: str, **extra: Any) -> int:
    payload = {"ok": ok, "message": message}
    payload.update(extra)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"settings": {"python": "python3"}, "devices": [], "active_device": None}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object")
    data.setdefault("settings", {})
    data["settings"].setdefault("python", "python3")
    data.setdefault("devices", [])
    data.setdefault("active_device", None)
    return data


def save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_version(value: Any) -> str:
    if value in (None, ""):
        return "3.3"
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    text = str(value).strip()
    if not text:
        return "3.3"
    try:
        return f"{float(text):.1f}"
    except ValueError:
        return text


def normalize_device(data: dict[str, Any]) -> dict[str, Any] | None:
    device_id = first_value(data, "id", "gwId", "dev_id", "device_id", "devId")
    key = first_value(data, "key", "local_key", "localKey")
    ip = first_value(data, "ip", "address")
    if not device_id or not key or not ip:
        return None
    name = str(first_value(data, "name", "label", "device_name") or device_id)
    return {
        "name": name,
        "id": str(device_id),
        "key": str(key),
        "ip": str(ip),
        "version": normalize_version(first_value(data, "version")),
    }


def walk_snapshot(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        candidate = normalize_device(node)
        if candidate:
            found.append(candidate)
        for value in node.values():
            found.extend(walk_snapshot(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(walk_snapshot(item))
    return found


def dedupe_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for device in devices:
        merged[device["id"]] = device
    return sorted(merged.values(), key=lambda item: item["name"].lower())


def find_device(config: dict[str, Any], selector: str | None) -> dict[str, Any]:
    target = selector or config.get("active_device")
    if not target:
        raise ValueError("No active device is configured")
    for device in config["devices"]:
        if device["id"] == target or device["name"] == target:
            return device
    raise ValueError(f"Device not found: {target}")


def require_tinytuya():
    try:
        import tinytuya  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "tinytuya is not installed. Install it with: python3 -m pip install tinytuya"
        ) from exc
    return tinytuya


def is_error_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and ("Error" in payload or "Err" in payload)


def make_bulb(device: dict[str, Any], version: str | None = None):
    tinytuya = require_tinytuya()
    bulb = tinytuya.BulbDevice(device["id"], device["ip"], device["key"])
    bulb.set_version(float(version or device.get("version", "3.3")))
    bulb.set_socketTimeout(3)
    bulb.set_socketRetryLimit(1)
    bulb.set_socketRetryDelay(0)
    bulb.set_socketPersistent(False)
    return bulb


def persist_device_version(config_path: Path, config: dict[str, Any], device_id: str, version: str) -> None:
    changed = False
    for device in config["devices"]:
        if device["id"] == device_id and device.get("version") != version:
            device["version"] = version
            changed = True
            break
    if changed:
        save_json_file(config_path, config)


def ordered_versions_for(device: dict[str, Any]) -> list[str]:
    ordered_versions = []
    preferred = normalize_version(device.get("version"))
    if preferred:
        ordered_versions.append(preferred)
    for candidate in VERSION_CANDIDATES:
        if candidate not in ordered_versions:
            ordered_versions.append(candidate)
    return ordered_versions


def remember_version(config_path: Path, config: dict[str, Any], device: dict[str, Any], version: str) -> None:
    if device.get("version") != version:
        device["version"] = version
        persist_device_version(config_path, config, device["id"], version)


def resolve_bulb(config_path: Path, config: dict[str, Any], selector: str | None):
    device = find_device(config, selector)

    last_status = None
    for version in ordered_versions_for(device):
        bulb = make_bulb(device, version=version)
        status = bulb.status()
        if not is_error_payload(status):
            remember_version(config_path, config, device, version)
            return device, bulb, status
        last_status = status

    raise RuntimeError(
        f"Unable to communicate with {device['name']} at {device['ip']}: {last_status}"
    )


def ensure_ok_result(result: Any, action: str) -> Any:
    if is_error_payload(result):
        raise RuntimeError(f"{action} failed: {result}")
    return result


def execute_with_version_fallback(config_path: Path, config: dict[str, Any], selector: str | None, action_name: str, fn):
    device = find_device(config, selector)
    versions = ordered_versions_for(device)
    last_error = None

    for index, version in enumerate(versions):
        bulb = make_bulb(device, version=version)
        result = fn(bulb)
        if not is_error_payload(result):
            remember_version(config_path, config, device, version)
            return device, bulb, result

        last_error = result
        if index == 0:
            continue

    raise RuntimeError(
        f"{action_name} failed for {device['name']} at {device['ip']}: {last_error}"
    )


def command_list(config: dict[str, Any]) -> int:
    return response(
        True,
        f"{len(config['devices'])} device(s) configured",
        active_device=config.get("active_device"),
        devices=config["devices"],
    )


def command_import_snapshot(config_path: Path, config: dict[str, Any], snapshot_path: str) -> int:
    path = Path(snapshot_path).expanduser()
    with path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    imported = dedupe_devices(walk_snapshot(snapshot))
    if not imported:
        return response(False, f"No devices with id/key/ip were found in {path}")
    config["devices"] = imported
    if not config.get("active_device") or not any(d["id"] == config["active_device"] for d in imported):
        config["active_device"] = imported[0]["id"]
    save_json_file(config_path, config)
    return response(
        True,
        f"Imported {len(imported)} device(s) from {path}",
        active_device=config["active_device"],
        devices=imported,
    )


def command_add_manual(
    config_path: Path,
    config: dict[str, Any],
    name: str,
    device_id: str,
    key: str,
    ip: str,
    version: str,
) -> int:
    device = {
        "name": name,
        "id": device_id,
        "key": key,
        "ip": ip,
        "version": normalize_version(version),
    }
    existing = [entry for entry in config["devices"] if entry["id"] != device_id]
    existing.append(device)
    config["devices"] = dedupe_devices(existing)
    config["active_device"] = device_id
    save_json_file(config_path, config)
    return response(True, f"Saved device {name}", active_device=device_id, device=device)


def command_select(config_path: Path, config: dict[str, Any], selector: str) -> int:
    device = find_device(config, selector)
    config["active_device"] = device["id"]
    save_json_file(config_path, config)
    return response(True, f"Selected {device['name']}", active_device=device["id"], device=device)


def command_status(config_path: Path, config: dict[str, Any], selector: str | None) -> int:
    device, bulb, raw_status = resolve_bulb(config_path, config, selector)
    state: dict[str, Any] | None = None
    try:
        state = bulb.state()
    except Exception:
        state = None
    return response(True, f"Fetched status for {device['name']}", device=device, status=raw_status, state=state)


def command_onoff(config_path: Path, config: dict[str, Any], selector: str | None, turn_on: bool) -> int:
    if turn_on:
        device, _, result = execute_with_version_fallback(
            config_path, config, selector, "turn_on", lambda bulb: bulb.turn_on()
        )
        message = f"Turned on {device['name']}"
    else:
        device, _, result = execute_with_version_fallback(
            config_path, config, selector, "turn_off", lambda bulb: bulb.turn_off()
        )
        message = f"Turned off {device['name']}"
    return response(True, message, device=device, result=result)


def command_rgb(config_path: Path, config: dict[str, Any], selector: str | None, r: int, g: int, b: int) -> int:
    def apply_rgb(bulb):
        result = bulb.turn_on()
        if is_error_payload(result):
            return result
        return bulb.set_colour(r, g, b)

    device, _, result = execute_with_version_fallback(
        config_path, config, selector, "set_colour", apply_rgb
    )
    return response(True, f"Set {device['name']} to rgb({r}, {g}, {b})", device=device, result=result)


def command_white(
    config_path: Path, config: dict[str, Any], selector: str | None, brightness: int, colourtemp: int
) -> int:
    def apply_white(bulb):
        result = bulb.turn_on()
        if is_error_payload(result):
            return result
        return bulb.set_white_percentage(brightness=brightness, colourtemp=colourtemp)

    device, _, result = execute_with_version_fallback(
        config_path, config, selector, "set_white_percentage", apply_white
    )
    return response(
        True,
        f"Set {device['name']} white brightness={brightness}% temp={colourtemp}%",
        device=device,
        result=result,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartLife RGB helper for grandMA3")
    parser.add_argument("--config", required=True, help="Path to plugin config JSON")
    parser.add_argument("--request-file", help="Path to JSON request file")

    subparsers = parser.add_subparsers(dest="command", required=False)
    subparsers.add_parser("list")

    import_snapshot = subparsers.add_parser("import-snapshot")
    import_snapshot.add_argument("--path", required=True)

    add_manual = subparsers.add_parser("add-manual")
    add_manual.add_argument("--name", required=True)
    add_manual.add_argument("--id", required=True)
    add_manual.add_argument("--key", required=True)
    add_manual.add_argument("--ip", required=True)
    add_manual.add_argument("--version", default="3.3")

    select_device = subparsers.add_parser("select")
    select_device.add_argument("--device", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--device")

    turn_on = subparsers.add_parser("on")
    turn_on.add_argument("--device")

    turn_off = subparsers.add_parser("off")
    turn_off.add_argument("--device")

    rgb = subparsers.add_parser("rgb")
    rgb.add_argument("--device")
    rgb.add_argument("--r", type=int, required=True)
    rgb.add_argument("--g", type=int, required=True)
    rgb.add_argument("--b", type=int, required=True)

    white = subparsers.add_parser("white")
    white.add_argument("--device")
    white.add_argument("--brightness", type=int, required=True)
    white.add_argument("--temp", type=int, required=True)

    return parser


def dispatch_request(config_path: Path, config: dict[str, Any], command: str, payload: dict[str, Any]) -> int:
    if command == "list":
        return command_list(config)
    if command == "import-snapshot":
        return command_import_snapshot(config_path, config, str(payload["path"]))
    if command == "add-manual":
        return command_add_manual(
            config_path,
            config,
            str(payload["name"]),
            str(payload["id"]),
            str(payload["key"]),
            str(payload["ip"]),
            str(payload.get("version", "3.3")),
        )
    if command == "select":
        return command_select(config_path, config, str(payload["device"]))
    if command == "status":
        return command_status(config_path, config, payload.get("device"))
    if command == "on":
        return command_onoff(config_path, config, payload.get("device"), True)
    if command == "off":
        return command_onoff(config_path, config, payload.get("device"), False)
    if command == "rgb":
        return command_rgb(
            config_path,
            config,
            payload.get("device"),
            int(payload["r"]),
            int(payload["g"]),
            int(payload["b"]),
        )
    if command == "white":
        return command_white(
            config_path,
            config,
            payload.get("device"),
            int(payload["brightness"]),
            int(payload["temp"]),
        )
    return response(False, f"Unknown command: {command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).expanduser()

    try:
        config = load_json_file(config_path)
        if args.request_file:
            request_path = Path(args.request_file).expanduser()
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                return response(False, "Request file must contain a JSON object")
            command = request.get("command")
            if not command:
                return response(False, "Request file is missing command")
            return dispatch_request(config_path, config, str(command), request)

        command = args.command
        if not command:
            return response(False, "No command provided")
        return dispatch_request(config_path, config, command, vars(args))
    except Exception as exc:
        return response(False, str(exc), error_type=exc.__class__.__name__)


if __name__ == "__main__":
    sys.exit(main())
