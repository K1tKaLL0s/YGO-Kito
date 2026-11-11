[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$Status,
    [string]$Config = '',
    [string]$Python = 'E:\Ana\envs\pcacgate\python.exe'
)
$ErrorActionPreference = 'Stop'
if ($Start -and $Status) { throw 'Choose Start or Status, not both.' }
$repository = Split-Path -Parent $PSScriptRoot
if (-not $Config) { $Config = Join-Path $repository 'training\axis_generic\config.automatic.v3.json' }
$Config = (Resolve-Path -LiteralPath $Config).Path
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python" }
$pythonRoot = Split-Path -Parent $Python
$env:PATH = "$pythonRoot;$pythonRoot\Library\bin;$pythonRoot\Scripts;" + $env:PATH
$env:PYTHONPATH = "$repository\src;$repository"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONHASHSEED = '0'
$env:PYTHONUTF8 = '1'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
# TEMP stays inside this project's explicit artifact root, outside the locked state directory.
$artifactRoot = Split-Path -Parent $settings.state_dir
$temporary = Join-Path $artifactRoot 'temporary'
New-Item -ItemType Directory -Path $temporary -Force | Out-Null
$env:TEMP = $temporary
$env:TMP = $temporary
$arguments = @('-B','-u','-m','training.axis_generic.automatic_v3','--config',$Config)
if ($Start) { $arguments += '--start' }
if ($Status) { $arguments += '--status' }
Push-Location -LiteralPath $repository
try {
    & $Python @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
