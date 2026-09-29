param(
    [string]$StorageRoot='D:/video',
    [string]$ModelsRepo=$PSScriptRoot,
    [string]$WslEnvPrefix='/mnt/d/video/runtime/models/env',
    [string]$VlEnvPrefix='/mnt/d/video/runtime/models/vl-env',
    [switch]$EnableExperimentalBst,
    [switch]$EnableVlEmbedding,
    [string]$ModelCatalogPath,
    [string]$FfmpegPath=$env:BTV_FFMPEG,
    [string]$FfprobePath=$env:BTV_FFPROBE
)
# Administrator configuration only. Dot-source in both API and worker terminals.
# The integrated repository is the default; an alternate worktree is a temporary
# development override, never a recorded job command supplied from the browser.
$platformPython=Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
if (!(Test-Path -LiteralPath $platformPython -PathType Leaf)) { throw 'Platform venv is missing' }
$modelSource=(Resolve-Path -LiteralPath $ModelsRepo).Path
$env:BTV_STORAGE_ROOT=$StorageRoot
$env:PYTHONPATH=$PSScriptRoot
$env:BTV_MODEL_CATALOG_PATH=if ($ModelCatalogPath) { (Resolve-Path -LiteralPath $ModelCatalogPath).Path } else { Join-Path $modelSource 'configs/models/catalog.json' }
$platformModelCommands=@{
    'query-rule-v1'=@($platformPython,'-m','packages.models')
    'torchvision-keypointrcnn'=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$WslEnvPrefix,'--repo',$modelSource)
    'tracknetv3-reuse'=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$WslEnvPrefix,'--repo',$modelSource)
    'torchvision-continuous-pose'=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$WslEnvPrefix,'--repo',$modelSource)
}
if ($EnableExperimentalBst) {
    $platformModelCommands['bst-cg-ap-reuse']=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$WslEnvPrefix,'--repo',$modelSource)
}
if ($EnableVlEmbedding) {
    $platformModelCommands['qwen3-vl-embedding-2b']=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$VlEnvPrefix,'--repo',$modelSource)
}
$env:BTV_MODEL_COMMANDS_JSON=$platformModelCommands | ConvertTo-Json -Compress
$env:BTV_RENDER_COMMAND_JSON=@($platformPython,'-m','packages.render') | ConvertTo-Json -Compress
if ($FfmpegPath) { $env:BTV_FFMPEG=(Resolve-Path -LiteralPath $FfmpegPath).Path }
if ($FfprobePath) { $env:BTV_FFPROBE=(Resolve-Path -LiteralPath $FfprobePath).Path }
$platformRepoGit=$PSScriptRoot.Replace('\','/')
$env:BTV_CODE_REVISION=git -c "safe.directory=$platformRepoGit" -C $PSScriptRoot rev-parse HEAD
