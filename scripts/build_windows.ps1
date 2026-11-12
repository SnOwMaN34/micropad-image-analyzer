<#
Build a portable, offline Windows µPAD Image Analyzer release folder.
Run from the repository root:
  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
The script will NOT bundle any research images or result folders.
#>
[CmdletBinding()]
param(
    [switch]$Console,
    [switch]$PackageOnly,
    [string]$ReleaseFolder = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Virtual environment not found. Create .venv and install requirements first.'
}

# Package a successful previous build without rebuilding the executable.
# Useful after an antivirus/indexer temporarily locks _internal/base_library.zip.
$packager = Join-Path $root 'scripts\package_release.py'
if (-not (Test-Path -LiteralPath $packager)) {
    throw 'scripts/package_release.py is missing. Copy both new packaging scripts first.'
}
if ($PackageOnly) {
    if ([string]::IsNullOrWhiteSpace($ReleaseFolder)) {
        throw 'Use -PackageOnly -ReleaseFolder .\release\MicroPADImageAnalyzer_YYYYMMDD_HHMMSS'
    }
    $target = (Resolve-Path -LiteralPath $ReleaseFolder -ErrorAction Stop).Path
    Write-Host ('Packaging existing release folder (no new build): ' + $target)
    & $python $packager $target
    if ($LASTEXITCODE -ne 0) {
        throw 'ZIP packaging failed. Close the application and retry -PackageOnly.'
    }
    Write-Host 'ZIP creation finished. Check the .zip and .sha256.txt files beside the release folder.'
    exit 0
}
if (-not [string]::IsNullOrWhiteSpace($ReleaseFolder)) {
    throw '-ReleaseFolder can only be used with -PackageOnly.'
}

# Verify writable-result path integration without passing Python code through
# Windows PowerShell 5.1 native-command quoting (which strips nested quotes).
# This avoids the broken `python -c` check in the first packaging script.
$pathsModule = Join-Path $root 'scripts\app_paths.py'
$reviewerPath = Join-Path $root 'scripts\roi_test_gui.py'
$analyzerPath = Join-Path $root 'scripts\analyze_image.py'
if (-not (Test-Path -LiteralPath $pathsModule)) {
    throw 'scripts/app_paths.py is missing. Copy the packaging toolkit files first.'
}
foreach ($sourcePath in @($reviewerPath, $analyzerPath)) {
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw ('Missing application source: ' + $sourcePath)
    }
    $sourceText = [System.IO.File]::ReadAllText($sourcePath)
    if (-not $sourceText.Contains('from app_paths import working_root') -or
        -not $sourceText.Contains('PROJECT_ROOT = working_root()')) {
        throw ('Runtime path patch missing from ' + $sourcePath +
               '. Run: .\.venv\Scripts\python.exe scripts\apply_packaging_changes.py')
    }
}
& $python -m py_compile $pathsModule $reviewerPath $analyzerPath
if ($LASTEXITCODE -ne 0) {
    throw 'Python syntax check failed. The build was stopped.'
}
Write-Host 'Runtime path patch verified.'

& $python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is missing. Run: .\.venv\Scripts\python.exe -m pip install pyinstaller'
}

$testRoot = Join-Path $env:TEMP ('micropad_release_tests_' + [guid]::NewGuid().ToString('N'))
Write-Host '[1/4] Running project tests...'
& $python -m pytest -q -o 'addopts=' --basetemp $testRoot -p no:cacheprovider
if ($LASTEXITCODE -ne 0) {
    throw 'Tests failed. Build stopped without producing a release.'
}

$displayMode = if ($Console) { '--console' } else { '--windowed' }
Write-Host '[2/4] Building Windows application...'
& $python -m PyInstaller `
    --noconfirm --clean --onedir $displayMode `
    --name 'MicroPADImageAnalyzer' `
    --exclude-module PySide6 `
    --paths (Join-Path $root 'src') `
    --paths (Join-Path $root 'scripts') `
    --distpath (Join-Path $root 'dist') `
    --workpath (Join-Path $root 'build') `
    --specpath (Join-Path $root 'build') `
    (Join-Path $root 'scripts\micropad_app.py')
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed. Review build output and do not distribute.'
}

$distFolder = Join-Path $root 'dist\MicroPADImageAnalyzer'
$exe = Join-Path $distFolder 'MicroPADImageAnalyzer.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw 'Expected executable not found after packaging.'
}

Write-Host '[3/4] Preparing clean release folder...'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$releaseHome = Join-Path $root 'release'
New-Item -ItemType Directory -Path $releaseHome -Force | Out-Null
$releaseFolder = Join-Path $releaseHome ('MicroPADImageAnalyzer_' + $stamp)
New-Item -ItemType Directory -Path $releaseFolder | Out-Null
Copy-Item -Path (Join-Path $distFolder '*') -Destination $releaseFolder -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root 'docs\LAB_USER_GUIDE.md') -Destination (Join-Path $releaseFolder 'LAB_USER_GUIDE.md')

# Ensure a visible results folder is present immediately after extraction.
# Keep a small instruction file so ZIP tools preserve this initially empty folder.
$resultsFolder = Join-Path $releaseFolder 'results'
New-Item -ItemType Directory -Path $resultsFolder -Force | Out-Null
$resultsNote = @(
    'MicroPAD Image Analyzer - local measurement results',
    '',
    'Reviewed ROI measurements will be saved into new subfolders here.',
    'Use Open Latest Results in the application to open the most recent one.',
    'The original scanned images are never overwritten.',
    'Keep run folders with calibration projects for reproducibility.'
)
Set-Content -LiteralPath (Join-Path $resultsFolder 'README.txt') -Value $resultsNote -Encoding UTF8


$commit = 'unavailable'
try {
    $current = (& git -C $root rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -eq 0) { $commit = ($current | Select-Object -First 1).Trim() }
} catch { }
$versionInfo = @(
    'MicroPAD Image Analyzer - research release candidate',
    'Built: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'),
    'Source commit: ' + $commit,
    'Build Python: ' + ((& $python --version) -join ' '),
    'OS: Windows',
    'Distribution: folder-based executable; keep _internal and EXE together',
    'Validation: release requires clean-PC and real-data acceptance testing'
)
Set-Content -LiteralPath (Join-Path $releaseFolder 'BUILD_INFO.txt') -Value $versionInfo -Encoding UTF8

Write-Host '[4/4] Creating verified ZIP and SHA-256 checksum (with lock retries)...'
$zip = $releaseFolder + '.zip'
& $python $packager $releaseFolder
if ($LASTEXITCODE -ne 0) {
    throw 'ZIP packaging failed. The EXE folder is still available. Use -PackageOnly to retry.'
}
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash

Write-Host ''
Write-Host 'BUILD COMPLETED (not yet laboratory-validated).'
Write-Host ('EXE: ' + (Join-Path $releaseFolder 'MicroPADImageAnalyzer.exe'))
Write-Host ('ZIP: ' + $zip)
Write-Host ('SHA-256: ' + $hash)
Write-Host 'Before sharing: test both tabs, saving, multi-pad calibration, Excel formulas, and a clean PC.'
