param([string]$StorageRoot='D:/video')
$env:BTV_STORAGE_ROOT=$StorageRoot
if (!$env:BTV_CODE_REVISION) { $env:BTV_CODE_REVISION=git -c "safe.directory=$PSScriptRoot" -C $PSScriptRoot rev-parse HEAD }
$platformPython=Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
& $platformPython -m packages.runtime.worker --db (Join-Path $StorageRoot 'platform/runtime.sqlite3') --storage-root $StorageRoot
