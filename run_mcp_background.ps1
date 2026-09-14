$ErrorActionPreference = 'Stop'

$pluginDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$hermesHome = Join-Path $env:LOCALAPPDATA 'hermes'
$fastmcp = Join-Path $hermesHome 'hermes-agent\venv\Scripts\fastmcp.exe'
$vaultPath = Join-Path $env:USERPROFILE 'Documents\agent-vault'
$stateDb = Join-Path $hermesHome 'state.db'
$logFile = Join-Path $hermesHome 'obsidian-wiki-mcp.log'
$errorLogFile = "$logFile.err"
$pidFile = Join-Path $hermesHome 'obsidian-wiki-mcp.pid'

if (-not (Test-Path -LiteralPath $fastmcp)) {
    throw "fastmcp not found: $fastmcp"
}

$env:OBSIDIAN_VAULT_PATH = $vaultPath
$env:HERMES_STATE_DB = $stateDb
$env:HERMES_HOME = $hermesHome
$env:HERMES_PYTHON = Join-Path $hermesHome 'hermes-agent\venv\Scripts\python.exe'

$arguments = @(
    'run',
    'mcp_server.py:mcp',
    '--transport', 'http',
    '--host', '127.0.0.1',
    '--port', '8765'
)

$process = Start-Process `
    -FilePath $fastmcp `
    -WorkingDirectory $pluginDir `
    -ArgumentList $arguments `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errorLogFile `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath $pidFile -Value ([string]$process.Id) -Encoding ascii
Write-Output $process.Id
