#!/usr/bin/env python3
"""TinyTuya-backed helper and local HTTP server for the grandMA3 SmartLife RGB plugin."""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION_CANDIDATES = ("3.4", "3.3", "3.5", "3.1")
ASYNC_COMMANDS = {"on", "off", "rgb", "white"}
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 9123


def ok_payload(message: str, **extra: Any) -> dict[str, Any]:
    payload = {"ok": True, "message": message}
    payload.update(extra)
    return payload


def error_payload(message: str, **extra: Any) -> dict[str, Any]:
    payload = {"ok": False, "message": message}
    payload.update(extra)
    return payload


def print_payload(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "settings": {
                "python": "python3",
                "server_host": DEFAULT_SERVER_HOST,
                "server_port": DEFAULT_SERVER_PORT,
            },
            "devices": [],
            "active_device": None,
        }
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object")
    data.setdefault("settings", {})
    data["settings"].setdefault("python", "python3")
    data["settings"].setdefault("server_host", DEFAULT_SERVER_HOST)
    data["settings"].setdefault("server_port", DEFAULT_SERVER_PORT)
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


def execute_with_version_fallback(config_path: Path, config: dict[str, Any], selector: str | None, action_name: str, fn):
    device = find_device(config, selector)
    last_error = None
    for version in ordered_versions_for(device):
        bulb = make_bulb(device, version=version)
        result = fn(bulb)
        if not is_error_payload(result):
            remember_version(config_path, config, device, version)
            return device, bulb, result
        last_error = result

    raise RuntimeError(
        f"{action_name} failed for {device['name']} at {device['ip']}: {last_error}"
    )


def command_list(config: dict[str, Any]) -> dict[str, Any]:
    return ok_payload(
        f"{len(config['devices'])} device(s) configured",
        active_device=config.get("active_device"),
        devices=config["devices"],
    )


def command_import_snapshot(config_path: Path, config: dict[str, Any], snapshot_path: str) -> dict[str, Any]:
    path = Path(snapshot_path).expanduser()
    with path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    imported = dedupe_devices(walk_snapshot(snapshot))
    if not imported:
        return error_payload(f"No devices with id/key/ip were found in {path}")
    config["devices"] = imported
    if not config.get("active_device") or not any(d["id"] == config["active_device"] for d in imported):
        config["active_device"] = imported[0]["id"]
    save_json_file(config_path, config)
    return ok_payload(
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
) -> dict[str, Any]:
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
    return ok_payload(f"Saved device {name}", active_device=device_id, device=device)


def command_select(config_path: Path, config: dict[str, Any], selector: str) -> dict[str, Any]:
    device = find_device(config, selector)
    config["active_device"] = device["id"]
    save_json_file(config_path, config)
    return ok_payload(f"Selected {device['name']}", active_device=device["id"], device=device)


def command_status(config_path: Path, config: dict[str, Any], selector: str | None) -> dict[str, Any]:
    device, bulb, raw_status = resolve_bulb(config_path, config, selector)
    try:
        state = bulb.state()
    except Exception:
        state = None
    return ok_payload(f"Fetched status for {device['name']}", device=device, status=raw_status, state=state)


def command_onoff(config_path: Path, config: dict[str, Any], selector: str | None, turn_on: bool) -> dict[str, Any]:
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
    return ok_payload(message, device=device, result=result)


def command_rgb(config_path: Path, config: dict[str, Any], selector: str | None, r: int, g: int, b: int) -> dict[str, Any]:
    def apply_rgb(bulb):
        result = bulb.turn_on()
        if is_error_payload(result):
            return result
        return bulb.set_colour(r, g, b)

    device, _, result = execute_with_version_fallback(
        config_path, config, selector, "set_colour", apply_rgb
    )
    return ok_payload(f"Set {device['name']} to rgb({r}, {g}, {b})", device=device, result=result)


def command_white(
    config_path: Path, config: dict[str, Any], selector: str | None, brightness: int, colourtemp: int
) -> dict[str, Any]:
    def apply_white(bulb):
        result = bulb.turn_on()
        if is_error_payload(result):
            return result
        return bulb.set_white_percentage(brightness=brightness, colourtemp=colourtemp)

    device, _, result = execute_with_version_fallback(
        config_path, config, selector, "set_white_percentage", apply_white
    )
    return ok_payload(
        f"Set {device['name']} white brightness={brightness}% temp={colourtemp}%",
        device=device,
        result=result,
    )


def perform_request(config_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    config = load_json_file(config_path)
    command = str(payload.get("command") or "")
    if not command:
        return error_payload("Missing command")
    if command == "list":
        return command_list(config)
    if command == "import_snapshot":
        return command_import_snapshot(config_path, config, str(payload["path"]))
    if command == "add_manual":
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
        return command_rgb(config_path, config, payload.get("device"), int(payload["r"]), int(payload["g"]), int(payload["b"]))
    if command == "white":
        return command_white(
            config_path,
            config,
            payload.get("device"),
            int(payload["brightness"]),
            int(payload["temp"]),
        )
    return error_payload(f"Unknown command: {command}")


class BridgeApp:
    def __init__(self, config_path: Path, log_path: Path):
        self.config_path = config_path
        self.log_path = log_path
        self.lock = threading.Lock()
        self.action_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.worker = threading.Thread(target=self.worker_loop, daemon=True, name="smartlife-bridge-worker")
        self.worker.start()

    def log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n")

    def dispatch(self, payload: dict[str, Any], allow_async: bool = True) -> tuple[int, dict[str, Any]]:
        command = str(payload.get("command") or "")
        if allow_async and command in ASYNC_COMMANDS:
            self.action_queue.put(dict(payload))
            return 202, ok_payload("Command queued")
        with self.lock:
            try:
                return 200, perform_request(self.config_path, payload)
            except Exception as exc:
                self.log(f"sync error: {exc}")
                return 500, error_payload(str(exc), error_type=exc.__class__.__name__)

    def worker_loop(self) -> None:
        while True:
            payload = self.action_queue.get()
            try:
                with self.lock:
                    result = perform_request(self.config_path, payload)
                if not result.get("ok"):
                    self.log(f"async failure: {json.dumps(result, sort_keys=True)}")
            except Exception as exc:
                self.log(f"async exception: {exc}")
            finally:
                self.action_queue.task_done()


class BridgeHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler_cls, app: BridgeApp):
        super().__init__(server_address, handler_cls)
        self.app = app


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeHttpServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, ok_payload("ok"))
            return
        self.send_json(404, error_payload("Not found"))

    def do_POST(self) -> None:
        if self.path != "/dispatch":
            self.send_json(404, error_payload("Not found"))
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self.send_json(400, error_payload(f"Invalid JSON: {exc}"))
            return
        if not isinstance(payload, dict):
            self.send_json(400, error_payload("Payload must be a JSON object"))
            return
        status, response_payload = self.server.app.dispatch(payload, allow_async=True)
        self.send_json(status, response_payload)

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(config_path: Path, host: str, port: int, log_path: Path) -> int:
    app = BridgeApp(config_path, log_path)
    app.log(f"server start {host}:{port}")
    server = BridgeHttpServer((host, port), BridgeHandler, app)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        app.log("server stop")
    return 0


def spawn_server(config_path: Path, host: str, port: int, log_path: Path) -> dict[str, Any]:
    script_path = Path(__file__).resolve()
    python_path = Path(sys.executable).resolve()
    command = [
        str(python_path),
        str(script_path),
        "--config",
        str(config_path),
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--log-path",
        str(log_path),
    ]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = log_path.open("a", encoding="utf-8")
    stderr_handle = stdout_handle

    kwargs: dict[str, Any] = {
        "stdout": stdout_handle,
        "stderr": stderr_handle,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        creationflags = 0
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **kwargs)
    finally:
        stdout_handle.close()

    return ok_payload("Server spawned", pid=process.pid, host=host, port=port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartLife RGB helper for grandMA3")
    parser.add_argument("--config", required=True, help="Path to plugin config JSON")

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

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default=DEFAULT_SERVER_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    serve.add_argument("--log-path")

    spawn = subparsers.add_parser("spawn-server")
    spawn.add_argument("--host", default=DEFAULT_SERVER_HOST)
    spawn.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    spawn.add_argument("--log-path")

    return parser


def request_payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if not args.command:
        return {}
    payload: dict[str, Any] = {"command": args.command}
    for key, value in vars(args).items():
        if key in {"config", "command", "host", "port", "log_path"}:
            continue
        if value is not None:
            payload[key] = value
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).expanduser()

    if args.command == "serve":
        log_path = Path(args.log_path).expanduser() if args.log_path else config_path.with_name("smartlife_bridge_server.log")
        return run_server(config_path, args.host, args.port, log_path)
    if args.command == "spawn-server":
        log_path = Path(args.log_path).expanduser() if args.log_path else config_path.with_name("smartlife_bridge_server.log")
        return print_payload(spawn_server(config_path, args.host, args.port, log_path))

    payload = request_payload_from_args(args)
    if not payload.get("command"):
        return print_payload(error_payload("No command provided"))

    try:
        return print_payload(perform_request(config_path, payload))
    except Exception as exc:
        return print_payload(error_payload(str(exc), error_type=exc.__class__.__name__))


if __name__ == "__main__":
    sys.exit(main())
