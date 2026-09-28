param([string]$StorageRoot='D:/video',[int]$Port=18080)
$env:BTV_STORAGE_ROOT=$StorageRoot
if (!$env:BTV_CODE_REVISION) { $platformRepoGit=$PSScriptRoot.Replace('\','/'); $env:BTV_CODE_REVISION=git -c "safe.directory=$platformRepoGit" -C $PSScriptRoot rev-parse HEAD }
$platformPython=Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
if (!(Test-Path -LiteralPath $platformPython)) { throw "Platform environment missing: $platformPython" }
& $platformPython -m uvicorn apps.platform.main:app --host 127.0.0.1 --port $Port
