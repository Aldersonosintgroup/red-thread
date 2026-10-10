# Builds the customer installer: frozen backend -> frontend -> signed NSIS installer.
#
# Usage (from anywhere):   pwsh C:\Projects\RedThread\scripts\build-release.ps1
#
# Code signing: once you own a code-signing certificate, install it in the
# Windows certificate store and set its SHA-1 thumbprint before building:
#   $env:REDTHREAD_CERT_THUMBPRINT = "ABCDEF0123..."
# The installer and every program inside it are then signed and timestamped.
# Without it the build still works but is unsigned (Windows shows
# "Unknown publisher").
#
# For a cloud-HSM certificate (Azure Trusted Signing, SSL.com eSigner,
# DigiCert KeyLocker) set REDTHREAD_SIGN_COMMAND instead, with %1 where the
# file path goes, e.g.:
#   $env:REDTHREAD_SIGN_COMMAND = 'trusted-signing-cli -e https://eus.codesigning.azure.net -a MyAccount -c MyProfile %1'

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$binaries = Join-Path $frontend 'src-tauri\binaries'

Write-Host '== 1/5 Backend tests' -ForegroundColor Cyan
& "$backend\venv\Scripts\python.exe" -m pytest -q $backend\tests
if ($LASTEXITCODE) { throw 'Backend tests failed; not building a release.' }

Write-Host '== 2/5 Freezing backend' -ForegroundColor Cyan
Push-Location $backend
& .\venv\Scripts\python.exe -m PyInstaller --noconfirm redthread-backend.spec
if ($LASTEXITCODE) { Pop-Location; throw 'PyInstaller failed.' }
Pop-Location
foreach ($triple in 'msvc', 'gnu') {
    Copy-Item "$backend\dist\redthread-backend.exe" "$binaries\redthread-backend-x86_64-pc-windows-$triple.exe" -Force
}

Write-Host '== 3/5 Building frontend' -ForegroundColor Cyan
Push-Location $frontend
npm run build
if ($LASTEXITCODE) { Pop-Location; throw 'Frontend build failed.' }

Write-Host '== 4/5 Checking for real case data' -ForegroundColor Cyan
# Names from real investigations must never ship. They are listed one per
# line in scripts\private-names.txt, which is git-ignored so the list itself
# never ends up in the source code.
$namesFile = Join-Path $PSScriptRoot 'private-names.txt'
if (Test-Path $namesFile) {
    $names = @(Get-Content $namesFile | Where-Object { $_.Trim() -and -not $_.StartsWith('#') } | ForEach-Object { [regex]::Escape($_.Trim()) })
    if ($names) {
        $forbidden = $names -join '|'
        $hits = @(Get-ChildItem dist -Recurse -File | Select-String -Pattern $forbidden -List)
        $hits += @(Get-ChildItem "$backend\app" -Recurse -Include *.py | Select-String -Pattern $forbidden -List)
        if ($hits) { Pop-Location; $hits | ForEach-Object { Write-Host $_.Path }; throw 'Real case names found in the build. Remove them first.' }
        Write-Host "No real case names found ($($names.Count) checked)."
    }
} else {
    Write-Warning 'No scripts\private-names.txt: skipping the real-name check.'
}

Write-Host '== 5/5 Packaging installer' -ForegroundColor Cyan
$override = @{}
if ($env:REDTHREAD_SIGN_COMMAND) {
    $override = @{ bundle = @{ windows = @{ signCommand = $env:REDTHREAD_SIGN_COMMAND } } }
    Write-Host 'Signing with REDTHREAD_SIGN_COMMAND'
} elseif ($env:REDTHREAD_CERT_THUMBPRINT) {
    $override = @{ bundle = @{ windows = @{ certificateThumbprint = $env:REDTHREAD_CERT_THUMBPRINT } } }
    Write-Host 'Signing with certificate' $env:REDTHREAD_CERT_THUMBPRINT
} else {
    Write-Warning 'No code-signing certificate configured: the installer will be UNSIGNED.'
}
if ($override.Count) {
    $configFile = Join-Path $env:TEMP 'redthread-sign.json'
    $override | ConvertTo-Json -Depth 5 | Set-Content $configFile -Encoding utf8
    npx tauri build --config $configFile
} else {
    npx tauri build
}
if ($LASTEXITCODE) { Pop-Location; throw 'Tauri build failed.' }
Pop-Location

$installer = Get-ChildItem "$frontend\src-tauri\target\release\bundle\nsis\*-setup.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
$signature = Get-AuthenticodeSignature $installer.FullName
Write-Host ''
Write-Host "Installer: $($installer.FullName)" -ForegroundColor Green
Write-Host ("Size: {0:N2} GB   Signature: {1}" -f ($installer.Length / 1GB), $signature.Status)
Write-Host "SHA-256: $((Get-FileHash $installer.FullName -Algorithm SHA256).Hash)"
