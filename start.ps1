# start.ps1 — launch FastAPI backend + Angular dev server in one terminal
# Usage: .\start.ps1

$root = $PSScriptRoot
$apiLog = "$root\.api.log"
$apiErr = "$root\.api.err.log"

# Kill any leftover process on port 8000
$old = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($old) {
    Stop-Process -Id (Get-Process -Id $old.OwningProcess -ErrorAction SilentlyContinue).Id -Force -ErrorAction SilentlyContinue
    Write-Host "  Cleared stale process on :8000" -ForegroundColor DarkYellow
}

# Start FastAPI — redirect stdout and stderr to separate log files
$api = Start-Process `
    -FilePath "$root\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $apiLog `
    -RedirectStandardError  $apiErr `
    -PassThru `
    -NoNewWindow

Write-Host "✓ Backend PID $($api.Id) — tailing $apiLog" -ForegroundColor Green

# Background job: tail both log files to this console
$tail = Start-Job -ScriptBlock {
    param($log, $err)
    $posOut = 0; $posErr = 0
    while ($true) {
        Start-Sleep -Milliseconds 400
        if (Test-Path $log) {
            $content = Get-Content $log -Raw -ErrorAction SilentlyContinue
            if ($content -and $content.Length -gt $posOut) {
                Write-Host $content.Substring($posOut) -NoNewline -ForegroundColor DarkCyan
                $posOut = $content.Length
            }
        }
        if (Test-Path $err) {
            $content = Get-Content $err -Raw -ErrorAction SilentlyContinue
            if ($content -and $content.Length -gt $posErr) {
                Write-Host $content.Substring($posErr) -NoNewline -ForegroundColor DarkCyan
                $posErr = $content.Length
            }
        }
    }
} -ArgumentList $apiLog, $apiErr

# Wait for uvicorn to bind
Start-Sleep -Seconds 4

if ($api.HasExited) {
    Write-Host "`n✗ Backend crashed — last output:" -ForegroundColor Red
    if (Test-Path $apiLog) { Get-Content $apiLog | Select-Object -Last 30 }
    if (Test-Path $apiErr) { Get-Content $apiErr | Select-Object -Last 30 }
    Stop-Job $tail; Remove-Job $tail -Force
    exit 1
}

# Start Angular in the foreground (Ctrl+C stops everything)
try {
    Set-Location "$root\ui"
    npx ng serve --open --proxy-config proxy.conf.json
} finally {
    Write-Host "`nStopping backend (PID $($api.Id))..." -ForegroundColor Yellow
    Stop-Job  $tail
    Remove-Job $tail -Force
    $api.Kill()
    Remove-Item $apiLog -ErrorAction SilentlyContinue
    Remove-Item $apiErr -ErrorAction SilentlyContinue
    Set-Location $root
}
