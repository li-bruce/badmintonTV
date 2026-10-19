param([string]$StorageRoot=$env:BTV_STORAGE_ROOT,[int]$Port=18080,
      [ValidateSet('agent','human')][string]$TrainingReviewer='human',
      [string]$DatabasePath='', [string]$TrainingTaxonomy='',
      [string]$EnvRoot='', [string]$Python='', [string]$Profile='workbench-cpu')
$ErrorActionPreference='Stop'
if (!$StorageRoot) { throw 'Specify -StorageRoot (or BTV_STORAGE_ROOT), for example D:/video on the original device.' }
if ($TrainingTaxonomy) { $env:BTV_TRAINING_TAXONOMY=$TrainingTaxonomy }
if (!$Python) {
    $legacy=Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
    $candidate=Join-Path $StorageRoot "runtime/platform/envs/$Profile/Scripts/python.exe"
    if ($EnvRoot) { $candidate=Join-Path $EnvRoot "$Profile/Scripts/python.exe" }
    if (Test-Path -LiteralPath $candidate) { $Python=$candidate }
    elseif (!$EnvRoot -and (Test-Path -LiteralPath $legacy)) { $Python=$legacy }
    else { throw 'Environment missing. Run scripts/deploy/setup.ps1 first.' }
}
$argsForRun=@('run','--profile',$Profile,'--storage-root',$StorageRoot,'--target','web','--reviewer',$TrainingReviewer,'--port',"$Port",'--python',$Python)
if ($EnvRoot) { $argsForRun+=@('--env-root',$EnvRoot) }
if ($DatabasePath) { $argsForRun+=@('--database',$DatabasePath) }
& $Python (Join-Path $PSScriptRoot 'scripts/deploy/manage.py') @argsForRun
exit $LASTEXITCODE
