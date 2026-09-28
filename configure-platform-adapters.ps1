param(
    [string]$StorageRoot='D:/video',
    [string]$ModelsRepo=$PSScriptRoot,
    [string]$WslEnvPrefix='/mnt/d/video/runtime/models/env',
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
$env:BTV_MODEL_COMMANDS_JSON=@{
    'query-rule-v1'=@($platformPython,'-m','packages.models')
    'torchvision-keypointrcnn'=@($platformPython,'-m','packages.runtime.wsl_bridge',
        '--distribution','Ubuntu','--env-prefix',$WslEnvPrefix,'--repo',$modelSource)
} | ConvertTo-Json -Compress
$env:BTV_RENDER_COMMAND_JSON=@($platformPython,'-m','packages.render') | ConvertTo-Json -Compress
if ($FfmpegPath) { $env:BTV_FFMPEG=(Resolve-Path -LiteralPath $FfmpegPath).Path }
if ($FfprobePath) { $env:BTV_FFPROBE=(Resolve-Path -LiteralPath $FfprobePath).Path }
$platformRepoGit=$PSScriptRoot.Replace('\','/')
$env:BTV_CODE_REVISION=git -c "safe.directory=$platformRepoGit" -C $PSScriptRoot rev-parse HEAD
