@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"

set "PLUGIN_NAME=smartlife_rgb"
set "SOURCE_DIR=%ROOT_DIR%\%PLUGIN_NAME%"

if not defined GMA3_PLUGIN_BASE set "GMA3_PLUGIN_BASE=C:\ProgramData\MALightingTechnology\gma3_library\datapools\plugins"
if not defined PYTHON_BIN set "PYTHON_BIN=python"

set "TARGET_DIR=%GMA3_PLUGIN_BASE%\%PLUGIN_NAME%"
set "VENV_DIR=%TARGET_DIR%\.venv"
set "CONFIG_PATH=%TARGET_DIR%\smartlife_rgb_config.json"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

echo Installing plugin to: %TARGET_DIR%
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

copy /Y "%SOURCE_DIR%\smartlife_rgb.lua" "%TARGET_DIR%\" >nul || goto :error
copy /Y "%SOURCE_DIR%\smartlife_rgb.xml" "%TARGET_DIR%\" >nul || goto :error
copy /Y "%SOURCE_DIR%\smartlife_bridge.py" "%TARGET_DIR%\" >nul || goto :error

echo Creating/updating virtualenv: %VENV_DIR%
"%PYTHON_BIN%" -m venv "%VENV_DIR%" || goto :error
"%VENV_PYTHON%" -m pip install --upgrade pip || goto :error
"%VENV_PYTHON%" -m pip install tinytuya || goto :error

echo Writing/updating plugin config: %CONFIG_PATH%
set "CONFIG_PATH_PY=%CONFIG_PATH%"
set "VENV_PYTHON_PY=%VENV_PYTHON%"
"%VENV_PYTHON%" -c "import json, os; from pathlib import Path; config_path = Path(os.environ['CONFIG_PATH_PY']); venv_python = os.environ['VENV_PYTHON_PY']; data = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}; assert isinstance(data, dict), 'Existing config is not a JSON object'; data.setdefault('settings', {}); data['settings']['python'] = venv_python; data.setdefault('devices', []); data.setdefault('active_device', None); config_path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')" || goto :error

echo.
echo Install complete.
echo Plugin files: %TARGET_DIR%
echo Python: %VENV_PYTHON%
echo.
echo Next steps:
echo 1. Import %TARGET_DIR%\smartlife_rgb.xml in grandMA3 onPC if needed.
echo 2. Run the plugin and import your TinyTuya snapshot.json, or add devices manually.
goto :eof

:error
echo.
echo Install failed.
exit /b 1
