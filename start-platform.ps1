param([string]$StorageRoot='D:/video',[int]$Port=18080,
      [ValidateSet('agent','human')][string]$TrainingReviewer='agent',
      [string]$DatabasePath='', [string]$TrainingTaxonomy='')
$env:BTV_STORAGE_ROOT=$StorageRoot
$env:BTV_TRAINING_ACTOR_TYPE=$TrainingReviewer
if ($DatabasePath) { $env:BTV_DB_PATH=$DatabasePath }
if ($TrainingTaxonomy) { $env:BTV_TRAINING_TAXONOMY=$TrainingTaxonomy }
if (!$env:BTV_CODE_REVISION) { $platformRepoGit=$PSScriptRoot.Replace('\','/'); $env:BTV_CODE_REVISION=git -c "safe.directory=$platformRepoGit" -C $PSScriptRoot rev-parse HEAD }
$platformPython=Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
if (!(Test-Path -LiteralPath $platformPython)) { throw "Platform environment missing: $platformPython" }
& $platformPython -m uvicorn apps.platform.main:app --host 127.0.0.1 --port $Port
