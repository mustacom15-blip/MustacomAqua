#requires -Version 5.1
<# Build the real Windows application and installer on Windows 10/11 x64.
   Run PowerShell in this folder: Set-ExecutionPolicy -Scope Process Bypass; .\build_windows.ps1
   Inno Setup 6 must be installed, or pass -InnoCompiler "C:\path\ISCC.exe".
#>
param([string]$InnoCompiler = "", [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $IsWindows -and $env:OS -ne "Windows_NT") { throw "Build the Windows executable on Windows, not on Linux/macOS." }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install 64-bit Python 3.11 or 3.12 from python.org and enable PATH." }
python -c "import sys,struct; assert (3,11)<=sys.version_info[:2]<=(3,12); assert struct.calcsize('P')*8==64; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Use supported 64-bit Python 3.11/3.12." }
if (-not (Test-Path .venv-build)) { python -m venv .venv-build }
$py = Join-Path $PSScriptRoot ".venv-build\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt "pyinstaller>=6.10,<7" "pytest>=8,<10"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; installer was not created." }
& $py -m PyInstaller --noconfirm --clean MustacomAqua.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
$exe = "dist\MustacomAquaGestionPro\MustacomAquaGestionPro.exe"
if (-not (Test-Path $exe)) { throw "Expected executable was not created." }
Write-Host "Application built: $exe" -ForegroundColor Green
if (-not $SkipInstaller) {
    $candidates = @($InnoCompiler, "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) { throw "Inno Setup 6 not found. Install it from jrsoftware.org or use -SkipInstaller." }
    & $candidates[0] "installer\MustacomAqua.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
    Write-Host "Installer created in dist_installer" -ForegroundColor Green
}
Write-Host "Test installation and Arabic printing on a clean Windows machine before production deployment." -ForegroundColor Yellow
