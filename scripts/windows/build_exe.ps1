param(
    [string]$Python = "python",
    [string]$ProjectRoot = "."
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

& $Python -m pip install -r requirements.txt pyinstaller
& $Python -m PyInstaller --noconfirm --clean --distpath dist/windows --workpath build/pyi-win build/compare.spec

Write-Host "Windows build completed: dist/windows/compare" -ForegroundColor Green
