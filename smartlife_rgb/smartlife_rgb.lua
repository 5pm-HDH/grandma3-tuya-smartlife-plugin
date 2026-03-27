local pluginName = select(1, ...)
local componentName = select(2, ...)
local signalTable = select(3, ...)
local my_handle = select(4, ...)

local json = require("json")

local function join_path(base, leaf)
    return tostring(base) .. "/" .. tostring(leaf)
end

local function file_exists(path)
    return FileExists(path) == true
end

local function detect_plugin_dir()
    local candidates = {
        join_path(GetPath(Enums.PathType.Library), "datapools/plugins/smartlife_rgb"),
        join_path(GetPath(Enums.PathType.PluginLibrary), "smartlife_rgb"),
    }

    for _, candidate in ipairs(candidates) do
        if file_exists(join_path(candidate, "smartlife_bridge.py")) then
            return candidate
        end
    end

    return candidates[1]
end

local PLUGIN_DIR = detect_plugin_dir()
local CONFIG_PATH = join_path(PLUGIN_DIR, "smartlife_rgb_config.json")
local BRIDGE_PATH = join_path(PLUGIN_DIR, "smartlife_bridge.py")
local RESULT_PATH = join_path(PLUGIN_DIR, "smartlife_bridge_result.json")
local ASYNC_LOG_PATH = join_path(PLUGIN_DIR, "smartlife_bridge_async.log")

local function ensure_plugin_dir()
    CreateDirectoryRecursive(PLUGIN_DIR)
end

local function read_file(path)
    local handle = io.open(path, "r")
    if not handle then
        return nil
    end
    local content = handle:read("*a")
    handle:close()
    return content
end

local function write_file(path, content)
    local handle = assert(io.open(path, "w"))
    handle:write(content)
    handle:close()
end

local function load_config()
    ensure_plugin_dir()
    if not file_exists(CONFIG_PATH) then
        return {
            settings = { python = "python3" },
            devices = {},
            active_device = nil,
        }
    end
    local content = read_file(CONFIG_PATH)
    if not content or content == "" then
        return {
            settings = { python = "python3" },
            devices = {},
            active_device = nil,
        }
    end
    local ok, data = pcall(json.decode, content)
    if not ok or type(data) ~= "table" then
        ErrEcho("SmartLife RGB: invalid config JSON, resetting defaults")
        return {
            settings = { python = "python3" },
            devices = {},
            active_device = nil,
        }
    end
    data.settings = data.settings or {}
    if not data.settings.python or data.settings.python == "" then
        data.settings.python = "python3"
    end
    data.devices = data.devices or {}
    return data
end

local function save_config(data)
    ensure_plugin_dir()
    write_file(CONFIG_PATH, json.encode(data))
end

local function shell_quote(value)
    local text = tostring(value or "")
    text = string.gsub(text, "'", "'\"'\"'")
    return "'" .. text .. "'"
end

local function show_message(title, message)
    MessageBox({
        title = title,
        message = message,
        commands = {
            { value = 1, name = "Ok" },
        },
    })
end

local function show_error(message)
    ErrEcho("SmartLife RGB: " .. tostring(message))
    show_message("SmartLife RGB Error", tostring(message))
end

local function show_success(message)
    Printf("SmartLife RGB: " .. tostring(message))
end

local function parse_cli_string(input)
    local tokens = {}
    local buffer = {}
    local quote = nil
    local i = 1
    local len = string.len(input or "")

    while i <= len do
        local ch = string.sub(input, i, i)
        if quote then
            if ch == quote then
                quote = nil
            else
                table.insert(buffer, ch)
            end
        else
            if ch == "'" or ch == "\"" then
                quote = ch
            elseif ch == " " or ch == "\t" or ch == "\n" then
                if #buffer > 0 then
                    table.insert(tokens, table.concat(buffer))
                    buffer = {}
                end
            else
                table.insert(buffer, ch)
            end
        end
        i = i + 1
    end

    if #buffer > 0 then
        table.insert(tokens, table.concat(buffer))
    end

    local command = tokens[1]
    local params = {}
    for index = 2, #tokens do
        local token = tokens[index]
        local key, value = string.match(token, "^([^=]+)=(.*)$")
        if key then
            params[key] = value
        else
            params["arg" .. tostring(index - 1)] = token
        end
    end
    return command, params
end

local function build_helper_command(args, output_path)
    local config = load_config()
    local python_path = config.settings.python or "python3"
    return shell_quote(python_path)
        .. " "
        .. shell_quote(BRIDGE_PATH)
        .. " --config "
        .. shell_quote(CONFIG_PATH)
        .. " "
        .. args
        .. " > "
        .. shell_quote(output_path)
        .. " 2>&1"
end

local function run_helper(args)
    local command = build_helper_command(args, RESULT_PATH)

    os.remove(RESULT_PATH)
    os.execute(command)

    local raw = read_file(RESULT_PATH)
    if not raw or raw == "" then
        return { ok = false, message = "Helper produced no output" }
    end

    local ok, payload = pcall(json.decode, raw)
    if not ok or type(payload) ~= "table" then
        return { ok = false, message = raw }
    end
    return payload
end

local function run_helper_async(args)
    local command = build_helper_command(args, ASYNC_LOG_PATH)
    os.execute("(" .. command .. ") >/dev/null 2>&1 &")
    return { ok = true, message = "Command dispatched" }
end

local function helper_call(command, options)
    local parts = { command }
    for _, entry in ipairs(options or {}) do
        table.insert(parts, entry.flag .. " " .. shell_quote(entry.value))
    end
    return run_helper(table.concat(parts, " "))
end

local function helper_call_async(command, options)
    local parts = { command }
    for _, entry in ipairs(options or {}) do
        table.insert(parts, entry.flag .. " " .. shell_quote(entry.value))
    end
    return run_helper_async(table.concat(parts, " "))
end

local function require_devices()
    local payload = helper_call("list")
    if not payload.ok then
        return nil, payload.message
    end
    if not payload.devices or #payload.devices == 0 then
        return nil, "No devices configured yet"
    end
    return payload.devices, payload.active_device
end

local function choose_device(display_handle, title)
    local devices, active_or_err = require_devices()
    if not devices then
        return nil, active_or_err
    end

    local items = {}
    local lookup = {}
    for _, device in ipairs(devices) do
        local label = device.name
        if device.id == active_or_err then
            label = label .. " [active]"
        end
        table.insert(items, label)
        lookup[label] = device
    end

    local _, selected = PopupInput({
        title = title or "Select Device",
        caller = display_handle,
        items = items,
    })

    if not selected or selected == "" then
        return nil, "Canceled"
    end
    return lookup[selected]
end

local function set_python_path()
    local config = load_config()
    local current = config.settings.python or "python3"
    local value = TextInput("Python executable path", current)
    if not value or value == "" then
        return
    end
    config.settings.python = value
    save_config(config)
    show_success("Saved Python path: " .. value)
end

local function import_snapshot_ui()
    local path = TextInput("Path to snapshot.json", "~/snapshot.json")
    if not path or path == "" then
        return
    end
    local payload = helper_call("import-snapshot", {
        { flag = "--path", value = path },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function add_manual_ui()
    local result = MessageBox({
        title = "Add SmartLife Device",
        message = "Enter Tuya LAN details",
        commands = {
            { value = 1, name = "Save" },
            { value = 0, name = "Cancel" },
        },
        inputs = {
            { name = "Name", value = "" },
            { name = "IP", value = "" },
            { name = "Device ID", value = "" },
            { name = "Local Key", value = "" },
            { name = "Version", value = "3.3", whiteFilter = "0123456789." },
        },
    })

    if result.success ~= true or result.result == 0 then
        return
    end

    local payload = helper_call("add-manual", {
        { flag = "--name", value = result.inputs["Name"] or "" },
        { flag = "--ip", value = result.inputs["IP"] or "" },
        { flag = "--id", value = result.inputs["Device ID"] or "" },
        { flag = "--key", value = result.inputs["Local Key"] or "" },
        { flag = "--version", value = result.inputs["Version"] or "3.3" },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function select_device_ui(display_handle)
    local device, err = choose_device(display_handle, "Active Device")
    if not device then
        if err ~= "Canceled" then
            show_error(err)
        end
        return
    end
    local payload = helper_call("select", {
        { flag = "--device", value = device.id },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function list_devices_ui()
    local payload = helper_call("list")
    if not payload.ok then
        show_error(payload.message)
        return
    end

    local lines = {}
    for _, device in ipairs(payload.devices or {}) do
        local prefix = (device.id == payload.active_device) and "* " or "  "
        table.insert(lines, prefix .. device.name .. " | " .. device.ip .. " | v" .. tostring(device.version))
    end
    if #lines == 0 then
        table.insert(lines, "No devices configured")
    end
    show_message("SmartLife Devices", table.concat(lines, "\n"))
end

local function status_ui(display_handle)
    local device, err = choose_device(display_handle, "Status Device")
    if not device then
        if err ~= "Canceled" then
            show_error(err)
        end
        return
    end
    local payload = helper_call("status", {
        { flag = "--device", value = device.id },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end

    local state = payload.state or {}
    local lines = {
        "Device: " .. device.name,
        "IP: " .. device.ip,
        "On: " .. tostring(state.is_on ~= nil and state.is_on or "unknown"),
        "Mode: " .. tostring(state.mode or "unknown"),
        "Brightness: " .. tostring(state.brightness or "unknown"),
        "ColourTemp: " .. tostring(state.colourtemp or "unknown"),
    }
    show_message("SmartLife Status", table.concat(lines, "\n"))
end

local function onoff_ui(display_handle, command_name)
    local device, err = choose_device(display_handle, command_name == "on" and "Turn On" or "Turn Off")
    if not device then
        if err ~= "Canceled" then
            show_error(err)
        end
        return
    end
    local payload = helper_call_async(command_name, {
        { flag = "--device", value = device.id },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function rgb_ui(display_handle)
    local device, err = choose_device(display_handle, "RGB Device")
    if not device then
        if err ~= "Canceled" then
            show_error(err)
        end
        return
    end

    local result = MessageBox({
        title = "Set RGB",
        message = "Values are 0-255",
        commands = {
            { value = 1, name = "Apply" },
            { value = 0, name = "Cancel" },
        },
        inputs = {
            { name = "R", value = "255", whiteFilter = "0123456789" },
            { name = "G", value = "255", whiteFilter = "0123456789" },
            { name = "B", value = "255", whiteFilter = "0123456789" },
        },
    })
    if result.success ~= true or result.result == 0 then
        return
    end

    local payload = helper_call_async("rgb", {
        { flag = "--device", value = device.id },
        { flag = "--r", value = result.inputs["R"] or "0" },
        { flag = "--g", value = result.inputs["G"] or "0" },
        { flag = "--b", value = result.inputs["B"] or "0" },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function white_ui(display_handle)
    local device, err = choose_device(display_handle, "White Device")
    if not device then
        if err ~= "Canceled" then
            show_error(err)
        end
        return
    end

    local result = MessageBox({
        title = "Set White",
        message = "Brightness and temp are 0-100%",
        commands = {
            { value = 1, name = "Apply" },
            { value = 0, name = "Cancel" },
        },
        inputs = {
            { name = "Brightness", value = "100", whiteFilter = "0123456789" },
            { name = "Temp", value = "0", whiteFilter = "0123456789" },
        },
    })
    if result.success ~= true or result.result == 0 then
        return
    end

    local payload = helper_call_async("white", {
        { flag = "--device", value = device.id },
        { flag = "--brightness", value = result.inputs["Brightness"] or "100" },
        { flag = "--temp", value = result.inputs["Temp"] or "0" },
    })
    if not payload.ok then
        show_error(payload.message)
        return
    end
    show_success(payload.message)
end

local function show_help()
    local text = [[Interactive actions:
- Import TinyTuya snapshot.json
- Add a manual device
- Select the active device
- Turn a device on/off
- Set RGB or white mode

Command-line examples:
Plugin "SmartLife RGB" "list"
Plugin "SmartLife RGB" "import_snapshot path='/Users/me/snapshot.json'"
Plugin "SmartLife RGB" "add_manual name='LED Strip' ip=192.168.1.60 id=abc key=xyz version=3.3"
Plugin "SmartLife RGB" "select device='LED Strip'"
Plugin "SmartLife RGB" "on device='LED Strip'"
Plugin "SmartLife RGB" "rgb device='LED Strip' r=255 g=0 b=0"
Plugin "SmartLife RGB" "white device='LED Strip' brightness=100 temp=20"
Plugin "SmartLife RGB" "set_python path='/opt/homebrew/bin/python3'"]]
    show_message("SmartLife RGB Help", text)
end

local function handle_cli(display_handle, arguments)
    local command, params = parse_cli_string(arguments or "")
    if not command or command == "" then
        return false
    end

    if command == "help" then
        show_help()
        return true
    end
    if command == "set_python" then
        local path = params.path
        if not path or path == "" then
            show_error("Missing path=...")
            return true
        end
        local config = load_config()
        config.settings.python = path
        save_config(config)
        show_success("Saved Python path: " .. path)
        return true
    end
    if command == "list" then
        list_devices_ui()
        return true
    end
    if command == "import_snapshot" then
        if not params.path or params.path == "" then
            show_error("Missing path=...")
            return true
        end
        local payload = helper_call("import-snapshot", {
            { flag = "--path", value = params.path },
        })
        if not payload.ok then
            show_error(payload.message)
        else
            show_success(payload.message)
        end
        return true
    end
    if command == "add_manual" then
        local payload = helper_call("add-manual", {
            { flag = "--name", value = params.name or "" },
            { flag = "--ip", value = params.ip or "" },
            { flag = "--id", value = params.id or "" },
            { flag = "--key", value = params.key or "" },
            { flag = "--version", value = params.version or "3.3" },
        })
        if not payload.ok then
            show_error(payload.message)
        else
            show_success(payload.message)
        end
        return true
    end
    if command == "select" then
        local selector = params.device or params.id or params.name
        if not selector or selector == "" then
            show_error("Missing device=...")
            return true
        end
        local payload = helper_call("select", {
            { flag = "--device", value = selector },
        })
        if not payload.ok then
            show_error(payload.message)
        else
            show_success(payload.message)
        end
        return true
    end
    if command == "status" or command == "on" or command == "off" then
        local options = {}
        local selector = params.device or params.id or params.name
        if selector and selector ~= "" then
            table.insert(options, { flag = "--device", value = selector })
        end
        local payload = command == "status" and helper_call(command, options) or helper_call_async(command, options)
        if not payload.ok then
            show_error(payload.message)
        elseif command == "status" then
            local state = payload.state or {}
            show_message("SmartLife Status", json.encode({
                device = payload.device,
                state = state,
                status = payload.status,
            }))
        else
            show_success(payload.message)
        end
        return true
    end
    if command == "rgb" then
        local options = {
            { flag = "--r", value = params.r or "" },
            { flag = "--g", value = params.g or "" },
            { flag = "--b", value = params.b or "" },
        }
        local selector = params.device or params.id or params.name
        if selector and selector ~= "" then
            table.insert(options, 1, { flag = "--device", value = selector })
        end
        local payload = helper_call_async("rgb", options)
        if not payload.ok then
            show_error(payload.message)
        else
            show_success(payload.message)
        end
        return true
    end
    if command == "white" then
        local options = {
            { flag = "--brightness", value = params.brightness or "" },
            { flag = "--temp", value = params.temp or "" },
        }
        local selector = params.device or params.id or params.name
        if selector and selector ~= "" then
            table.insert(options, 1, { flag = "--device", value = selector })
        end
        local payload = helper_call_async("white", options)
        if not payload.ok then
            show_error(payload.message)
        else
            show_success(payload.message)
        end
        return true
    end

    show_error("Unknown command: " .. tostring(command))
    return true
end

local function interactive_menu(display_handle)
    local items = {
        "List devices",
        "Import snapshot.json",
        "Add manual device",
        "Select active device",
        "Turn on",
        "Turn off",
        "Set RGB",
        "Set white",
        "Show status",
        "Set Python path",
        "Help",
    }

    local _, selected = PopupInput({
        title = "SmartLife RGB",
        caller = display_handle,
        items = items,
    })

    if not selected or selected == "" then
        return
    end

    if selected == "List devices" then
        list_devices_ui()
    elseif selected == "Import snapshot.json" then
        import_snapshot_ui()
    elseif selected == "Add manual device" then
        add_manual_ui()
    elseif selected == "Select active device" then
        select_device_ui(display_handle)
    elseif selected == "Turn on" then
        onoff_ui(display_handle, "on")
    elseif selected == "Turn off" then
        onoff_ui(display_handle, "off")
    elseif selected == "Set RGB" then
        rgb_ui(display_handle)
    elseif selected == "Set white" then
        white_ui(display_handle)
    elseif selected == "Show status" then
        status_ui(display_handle)
    elseif selected == "Set Python path" then
        set_python_path()
    elseif selected == "Help" then
        show_help()
    end
end

local function main(display_handle, arguments)
    if not file_exists(BRIDGE_PATH) then
        show_error("Helper script not found at " .. BRIDGE_PATH)
        return
    end
    if arguments and arguments ~= "" then
        handle_cli(display_handle, arguments)
        return
    end
    interactive_menu(display_handle)
end

return main
