@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Restart the local Obsidian Wiki MCP server on port 8765.
set "PLUGIN_DIR=%~dp0"
set "HERMES_HOME=%LOCALAPPDATA%\hermes"
set "HERMES_PYTHON=%HERMES_HOME%\hermes-agent\venv\Scripts\python.exe"
set "FASTMCP=%HERMES_HOME%\hermes-agent\venv\Scripts\fastmcp.exe"
set "LAUNCHER=%PLUGIN_DIR%run_mcp_background.ps1"
set "VAULT_PATH=%USERPROFILE%\Documents\agent-vault"
set "STATE_DB=%HERMES_HOME%\state.db"
set "PORT=8765"
set "HOST=127.0.0.1"
set "LOG_FILE=%HERMES_HOME%\obsidian-wiki-mcp.log"

if not exist "%FASTMCP%" (
  echo ERROR: fastmcp not found: "%FASTMCP%"
  exit /b 1
)
if not exist "%PLUGIN_DIR%mcp_server.py" (
  echo ERROR: mcp_server.py not found: "%PLUGIN_DIR%mcp_server.py"
  exit /b 1
)
if not exist "%LAUNCHER%" (
  echo ERROR: launcher not found: "%LAUNCHER%"
  exit /b 1
)

rem Stop the process currently listening on the MCP port, if any.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo Stopping process %%P on port %PORT%...
  taskkill /PID %%P /T /F >nul 2>&1
)

rem Wait briefly for Windows to release the port.
for /L %%I in (1,1,20) do (
  netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
  if errorlevel 1 goto port_free
  >nul %SystemRoot%\System32\ping.exe 127.0.0.1 -n 2
)

echo ERROR: port %PORT% is still in use.
exit /b 2

:port_free
if not exist "%HERMES_HOME%" mkdir "%HERMES_HOME%" >nul 2>&1

echo Starting Obsidian Wiki MCP in background...
cd /d "%PLUGIN_DIR%"

rem Use a second hidden PowerShell process so this .cmd returns immediately
rem without inheriting the caller's console pipes.
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File','%LAUNCHER%') -WindowStyle Hidden"
if errorlevel 1 (
  echo ERROR: failed to start the hidden MCP launcher.
  exit /b 3
)

rem Confirm that the new process has opened the port.
for /L %%I in (1,1,30) do (
  netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
  if not errorlevel 1 (
    echo MCP server is running on http://%HOST%:%PORT%/mcp
    echo Log: %LOG_FILE%
    exit /b 0
  )
  >nul %SystemRoot%\System32\ping.exe 127.0.0.1 -n 2
)

echo ERROR: MCP server did not open port %PORT%.
echo Check log: %LOG_FILE%
exit /b 3
