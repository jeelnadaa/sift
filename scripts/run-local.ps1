# Run Sift natively on Windows (no Docker): API, worker and scheduler in this window's background jobs.
# Needs: backend/.venv (see README), a Postgres database, and .env at the repo root with
#   QUEUE_BACKEND=postgres and DATABASE_URL pointing at your Postgres.
# Stop with Ctrl+C (all three processes stop).
#   -Lan   also listen on this laptop's Wi-Fi address so the phone app can reach it
#          (http://<laptop IP>:8000; Windows asks once to allow it through the firewall).
param([switch]$Lan)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Create the venv first: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null

Push-Location $backend
try {
    & $py -m alembic upgrade head
    $bind = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
    $procs = @(
        Start-Process $py -ArgumentList "-m uvicorn app.main:app --host $bind --port 8000 --no-access-log" -NoNewWindow -PassThru -RedirectStandardError (Join-Path $root "logs\api.log")
        Start-Process $py -ArgumentList "-m app.worker" -NoNewWindow -PassThru -RedirectStandardError (Join-Path $root "logs\worker.log")
        Start-Process $py -ArgumentList "-m app.scheduler" -NoNewWindow -PassThru -RedirectStandardError (Join-Path $root "logs\scheduler.log")
    )
    Write-Host "Sift running: http://localhost:8000/health   logs in .\logs   (Ctrl+C to stop)"
    if ($Lan) {
        $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' -and $_.IPAddress -notlike '169.*' } | Select-Object -ExpandProperty IPAddress
        foreach ($ip in $ips) { Write-Host "Phone app server address: http://${ip}:8000" }
    }
    while ($true) {
        Start-Sleep -Seconds 5
        foreach ($p in $procs) { if ($p.HasExited) { throw "process $($p.Id) exited; see logs" } }
    }
}
finally {
    $procs | Where-Object { $_ -and -not $_.HasExited } | ForEach-Object { Stop-Process -Id $_.Id -Force }
    Pop-Location
}
