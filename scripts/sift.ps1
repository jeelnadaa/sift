<#
Sift on this Windows laptop: one script for everyday control.

  powershell -ExecutionPolicy Bypass -File scripts\sift.ps1 <command>

  start      Turn on the "Sift" autostart task and start Sift now (API, worker, scheduler).
  stop       Stop Sift and keep it stopped: also turns the task off, because its 5-minute
             watchdog would otherwise start it again. Mail is not lost: Sift catches up later.
  restart    stop + start (after an update, or when something looks stuck).
  status     Is it running? Task, processes, local and public health, the tunnel, last errors.
  logs       Follow a log live: logs api | worker | scheduler | supervisor (Ctrl+C to leave).
  update     After you pulled new code: stop, install Python packages, build the web app,
             migrate the database, start. -SkipWeb skips the web build.
  backup     Save the database to backups\sift-<time>.dump (keeps the newest 14).
  restore    Put a backup back: restore backups\sift-<time>.dump  (asks first; stops Sift).
  autostart  on | off: start Sift at every Windows sign-in, or never (installs/removes the task).

Nothing here prints passwords or keys: the database password is read from .env and handed
to pg_dump / pg_restore through the environment only.
#>
param(
    [Parameter(Position = 0)][ValidateSet("start", "stop", "restart", "status", "logs", "update", "backup", "restore", "autostart", "help")]
    [string]$Command = "help",
    [Parameter(Position = 1)][string]$Arg,
    [switch]$SkipWeb,
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$task = "Sift"
$logDir = Join-Path $root "logs"
$backupDir = Join-Path $root "backups"
$keepBackups = 14

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Ok($text) { Say "  OK    $text" "Green" }
function Bad($text) { Say "  !!    $text" "Red" }
function Info($text) { Say "  ..    $text" "DarkGray" }

function Get-SiftTask { Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }

function Get-SiftProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' or Name = 'powershell.exe' or Name = 'pwsh.exe'" |
        Where-Object { $_.CommandLine -match '-m (uvicorn app\.main:app|app\.worker|app\.scheduler)\b' -or $_.CommandLine -match 'run-local\.ps1' }
}

function Test-Health($url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 8
        return ($r.Content | ConvertFrom-Json)
    } catch { return $null }
}

function Read-DotEnv {
    $values = @{}
    $file = Join-Path $root ".env"
    if (-not (Test-Path $file)) { throw ".env not found at $file" }
    foreach ($line in Get-Content $file) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $values[$Matches[1]] = $Matches[2].Trim('"', "'") }
    }
    return $values
}

function Get-DbParts {
    # DATABASE_URL=postgresql+psycopg://user:password@host:port/name
    $url = (Read-DotEnv)["DATABASE_URL"]
    if (-not $url -or $url -notmatch '^postgresql(\+\w+)?://(?<user>[^:@/]+)(:(?<pw>[^@/]*))?@(?<host>[^:/]+)(:(?<port>\d+))?/(?<db>[^?]+)') {
        throw "DATABASE_URL in .env isn't a postgresql:// address this script understands"
    }
    return @{ User = $Matches.user; Password = [uri]::UnescapeDataString("$($Matches.pw)"); Host = $Matches.host
              Port = $(if ($Matches.port) { $Matches.port } else { "5432" }); Db = $Matches.db }
}

function Find-PgTool($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$name.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    throw "$name not found. Install PostgreSQL's command line tools or add its bin folder to PATH."
}

function Invoke-Pg($tool, [string[]]$arguments) {
    $db = Get-DbParts
    $env:PGPASSWORD = $db.Password  # for this child only; never printed
    try {
        & (Find-PgTool $tool) -h $db.Host -p $db.Port -U $db.User @arguments
        if ($LASTEXITCODE -ne 0) { throw "$tool failed (exit $LASTEXITCODE)" }
    } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}

function Stop-Sift {
    $t = Get-SiftTask
    if ($t) {
        if ($t.State -ne "Disabled") { Disable-ScheduledTask -TaskName $task | Out-Null }  # the watchdog must not bring it back
        Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    }
    $procs = @(Get-SiftProcesses)
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 20 -and @(Get-SiftProcesses).Count; $i++) { Start-Sleep -Milliseconds 500 }
    if (@(Get-SiftProcesses).Count) { Bad "some Sift processes are still running; run 'status'" } else { Ok "Sift stopped$(if ($t) { ' (autostart paused until you run start)' })" }
}

function Start-Sift {
    $t = Get-SiftTask
    if (-not $t) {
        Info "no autostart task yet: installing it (starts Sift at every sign-in)"
        & (Join-Path $PSScriptRoot "install-autostart.ps1") | Out-Null
        $t = Get-SiftTask
    }
    if ($t.State -eq "Disabled") { Enable-ScheduledTask -TaskName $task | Out-Null }
    if (@(Get-SiftProcesses | Where-Object { $_.CommandLine -match 'uvicorn' }).Count -eq 0) { Start-ScheduledTask -TaskName $task }
    Info "waiting for Sift to answer..."
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        $h = Test-Health "http://localhost:8000/health"
        if ($h -and $h.status -eq "ok") { Ok "Sift is running: http://localhost:8000/app/"; return }
    }
    Bad "Sift didn't answer within a minute. Look at: scripts\sift.ps1 logs api"
}

function Show-Status {
    Say "Sift status" "White"
    $t = Get-SiftTask
    if (-not $t) { Bad "autostart task: not installed (scripts\sift.ps1 autostart on)" }
    elseif ($t.State -eq "Disabled") { Info "autostart task: OFF (stopped with 'stop'; 'start' turns it back on)" }
    else { Ok "autostart task: on ($($t.State.ToString().ToLower()))" }

    $procs = @(Get-SiftProcesses)
    foreach ($name in @(@("api", "uvicorn app\.main"), @("worker", "app\.worker"), @("scheduler", "app\.scheduler"))) {
        $n = @($procs | Where-Object { $_.CommandLine -match $name[1] }).Count
        if ($n) { Ok "$($name[0]) running" } else { Bad "$($name[0]) not running" }
    }
    $local = Test-Health "http://localhost:8000/health"
    if ($local) { Ok "local health: database $($local.database), mail checks $($local.mail_checks), queue $($local.queue)" } else { Bad "local health: no answer on http://localhost:8000/health" }

    $public = (Read-DotEnv)["PUBLIC_BASE_URL"]
    if ($public -and $public -notmatch 'localhost|127\.0\.0\.1') {
        $h = Test-Health "$($public.TrimEnd('/'))/health"
        if ($h) { Ok "public: $public answers" } else { Bad "public: $public doesn't answer (tunnel or server down)" }
    }
    $tunnel = Get-Service -Name Cloudflared -ErrorAction SilentlyContinue
    if ($tunnel) { if ($tunnel.Status -eq "Running") { Ok "Cloudflare tunnel service running" } else { Bad "Cloudflare tunnel service: $($tunnel.Status)" } }
    $pg = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pg) { if ($pg.Status -eq "Running") { Ok "PostgreSQL service running" } else { Bad "PostgreSQL service: $($pg.Status)" } }

    $latest = Get-ChildItem $backupDir -Filter "sift-*.dump" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) { Info "latest backup: $($latest.Name) ($([math]::Round($latest.Length / 1MB, 1)) MB, $($latest.LastWriteTime))" } else { Info "no backups yet (scripts\sift.ps1 backup)" }
    foreach ($log in "api", "worker", "scheduler") {
        $file = Join-Path $logDir "$log.log"
        if (Test-Path $file) {
            $errs = @(Get-Content $file -Tail 400 | Where-Object { $_ -match ' (ERROR|CRITICAL) |Traceback' })
            if ($errs.Count) { Bad "$log.log: $($errs.Count) error line(s) recently; last: $($errs[-1].Substring(0, [math]::Min(140, $errs[-1].Length)))" }
        }
    }
    $sup = Join-Path $logDir "supervisor.log"
    if (Test-Path $sup) { $last = Get-Content $sup -Tail 1; if ($last) { Info "last restart by the supervisor: $last" } }
}

switch ($Command) {
    "start" { Start-Sift }
    "stop" { Stop-Sift }
    "restart" { Stop-Sift; Start-Sift }
    "status" { Show-Status }
    "logs" {
        $which = if ($Arg) { $Arg } else { "api" }
        if ($which -notin "api", "worker", "scheduler", "supervisor") { throw "logs takes api, worker, scheduler or supervisor" }
        $file = Join-Path $logDir "$which.log"
        if (-not (Test-Path $file)) { throw "no $file yet" }
        Say "Following $file (Ctrl+C to leave)" "White"
        Get-Content $file -Tail 40 -Wait
    }
    "update" {
        Stop-Sift
        Push-Location $backend
        try {
            Info "installing Python packages"
            & $py -m pip install -q -r requirements.txt
            if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
            Info "migrating the database"
            & $py -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) { throw "migration failed: Sift stays stopped; fix it, then run start" }
        } finally { Pop-Location }
        if (-not $SkipWeb) {
            Push-Location (Join-Path $root "web")
            try {
                Info "building the web app"
                npm ci --no-audit --no-fund --loglevel=error
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
                npm run build --silent
                if ($LASTEXITCODE -ne 0) { throw "web build failed" }
            } finally { Pop-Location }
        }
        Ok "updated"
        Start-Sift
    }
    "backup" {
        New-Item -ItemType Directory -Force $backupDir | Out-Null
        $file = Join-Path $backupDir ("sift-{0}.dump" -f (Get-Date -Format "yyyy-MM-dd-HHmm"))
        Info "backing up the database (Sift keeps running)"
        Invoke-Pg "pg_dump" @("-d", (Get-DbParts).Db, "--format=custom", "--no-owner", "--file", $file)
        Ok "saved $file ($([math]::Round((Get-Item $file).Length / 1MB, 1)) MB). Keep a copy off this laptop too, with your .env (ENCRYPTION_KEYS)."
        Get-ChildItem $backupDir -Filter "sift-*.dump" | Sort-Object LastWriteTime -Descending | Select-Object -Skip $keepBackups |
            ForEach-Object { Remove-Item $_.FullName; Info "removed old backup $($_.Name)" }
    }
    "restore" {
        if (-not $Arg) {
            Say "Backups:" "White"
            Get-ChildItem $backupDir -Filter "sift-*.dump" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | ForEach-Object { Say "  $($_.FullName)" }
            throw "say which one: scripts\sift.ps1 restore <file>"
        }
        $file = (Resolve-Path $Arg).Path
        if (-not $Yes) {
            $answer = Read-Host "This replaces everything in the database with $([IO.Path]::GetFileName($file)). Type RESTORE to go on"
            if ($answer -ne "RESTORE") { Say "Nothing changed."; return }
        }
        Stop-Sift
        Info "restoring"
        Invoke-Pg "pg_restore" @("-d", (Get-DbParts).Db, "--clean", "--if-exists", "--no-owner", $file)
        Ok "restored from $file"
        Start-Sift
    }
    "autostart" {
        switch ($Arg) {
            "on" { & (Join-Path $PSScriptRoot "install-autostart.ps1"); Enable-ScheduledTask -TaskName $task | Out-Null }
            "off" { Stop-Sift; & (Join-Path $PSScriptRoot "install-autostart.ps1") -Remove }
            default { throw "autostart takes on or off" }
        }
    }
    default { (Get-Content $PSCommandPath -TotalCount 24) -replace '^<#|^#>', '' | Select-Object -Skip 1 | ForEach-Object { Write-Host $_ } }
}
