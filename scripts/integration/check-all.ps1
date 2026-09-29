param([string]$StorageRoot = 'D:/video')
$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pythonPath = Join-Path $StorageRoot 'runtime/platform/env/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Platform virtual environment is missing: $pythonPath"
}
$testRoot = Join-Path $repositoryRoot ('.runtime/integration-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$savedFixtures = $env:BTV_CONTRACT_FIXTURES_DIR
$savedTemp = $env:TEMP
$savedTmp = $env:TMP
$savedStorage = $env:BTV_STORAGE_ROOT
$savedDatabase = $env:BTV_DB_PATH
Push-Location $repositoryRoot
try {
    $env:BTV_CONTRACT_FIXTURES_DIR = Join-Path $repositoryRoot 'packages/contracts/fixtures'
    $env:TEMP = $testRoot
    $env:TMP = $testRoot
    $env:BTV_STORAGE_ROOT = Join-Path $testRoot 'import-state'
    $env:BTV_DB_PATH = Join-Path $testRoot 'import-state/platform/platform.sqlite3'
    & $pythonPath -m pytest -q -p no:cacheprovider tests/contracts tests/platform --basetemp (Join-Path $testRoot 'pytest')
    if ($LASTEXITCODE -ne 0) { throw 'Contract/platform tests failed.' }
    if (!(Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is required for the frontend regression tests; Python checks alone are incomplete.' }
    & node -e "require('vm').runInThisContext(require('fs').readFileSync('tests/platform/preview_ui.test.cjs','utf8'))"
    if ($LASTEXITCODE -ne 0) { throw 'Frontend preview and timeline tests failed.' }
    foreach ($moduleName in @('library', 'models', 'render')) {
        & $pythonPath -m unittest discover -s "tests/$moduleName" -q
        if ($LASTEXITCODE -ne 0) { throw "$moduleName tests failed." }
    }
    foreach ($manifestName in @('assets.v1.json', 'assets.doubles.v1.json')) {
        & $pythonPath scripts/library/check_contracts.py --contracts-root $repositoryRoot --storage-root $StorageRoot --manifest (Join-Path $StorageRoot "data/handoff/$manifestName")
        if ($LASTEXITCODE -ne 0) { throw "Library contract verification failed: $manifestName" }
    }
    & $pythonPath scripts/models/check_contracts.py --contracts-repo $repositoryRoot --storage-root $StorageRoot
    if ($LASTEXITCODE -ne 0) { throw 'Model contract verification failed.' }
    Write-Output 'All CPU contract/module checks passed. This does not run GPU training or measure model accuracy.'
}
finally {
    Pop-Location
    $env:BTV_CONTRACT_FIXTURES_DIR = $savedFixtures
    $env:TEMP = $savedTemp
    $env:TMP = $savedTmp
    $env:BTV_STORAGE_ROOT = $savedStorage
    $env:BTV_DB_PATH = $savedDatabase
}
