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
if (-not (Test-Path (Join-Path $root "web\dist\index.html"))) {
    Write-Warning "Web UI not built, so /app shows a notice. Build it once: cd web; npm ci; npm run build"
}

# Stop leftovers from a previous run (e.g. the scheduled task was killed and its children survived).
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match '-m (uvicorn app\.main:app|app\.worker|app\.scheduler)\b' } |  # venv launcher and its real interpreter child
    ForEach-Object { Write-Host "stopping leftover Sift process $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Push-Location $backend
try {
    & $py -m alembic upgrade head
    $bind = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
    $services = [ordered]@{
        api       = "-m uvicorn app.main:app --host $bind --port 8000 --no-access-log"
        worker    = "-m app.worker"
        scheduler = "-m app.scheduler"
    }
    $supervisorLog = Join-Path $root "logs\supervisor.log"
    function Start-Service($name) {
        # each start gets a fresh log; the previous one is kept as <name>.prev.log for post-mortems
        $log = Join-Path $root "logs\$name.log"
        if (Test-Path $log) { Move-Item $log (Join-Path $root "logs\$name.prev.log") -Force }
        Start-Process $py -ArgumentList $services[$name] -NoNewWindow -PassThru -RedirectStandardError $log
    }
    $procs = @{}
    foreach ($name in $services.Keys) { $procs[$name] = Start-Service $name }
    Write-Host "Sift running: http://localhost:8000/health   logs in .\logs   (Ctrl+C to stop)"
    if ($Lan) {
        $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' -and $_.IPAddress -notlike '169.*' } | Select-Object -ExpandProperty IPAddress
        foreach ($ip in $ips) { Write-Host "Phone app server address: http://${ip}:8000" }
    }
    # Supervise: restart any service that exits, with a short pause so a crash loop cannot spin.
    while ($true) {
        Start-Sleep -Seconds 5
        foreach ($name in @($procs.Keys)) {
            if ($procs[$name].HasExited) {
                $msg = "$(Get-Date -Format s) $name exited (code $($procs[$name].ExitCode)); restarting in 10 s"
                Write-Host $msg
                Add-Content $supervisorLog $msg
                Start-Sleep -Seconds 10
                $procs[$name] = Start-Service $name
            }
        }
    }
}
finally {
    $procs.Values | Where-Object { $_ -and -not $_.HasExited } | ForEach-Object { Stop-Process -Id $_.Id -Force }
    Pop-Location
}
