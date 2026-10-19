param([string]$Profile='workbench-cpu', [Parameter(Mandatory=$true)][string]$StorageRoot, [string]$EnvRoot='', [string]$Python='python', [switch]$DryRun, [switch]$Dev)
$ErrorActionPreference='Stop'
$setupArgs=@('setup','--profile',$Profile,'--storage-root',$StorageRoot)
if ($EnvRoot) { $setupArgs+=@('--env-root',$EnvRoot) }
if ($DryRun) { $setupArgs+='--dry-run' }
if ($Dev) { $setupArgs+='--dev' }
& $Python (Join-Path $PSScriptRoot 'manage.py') @setupArgs
exit $LASTEXITCODE
