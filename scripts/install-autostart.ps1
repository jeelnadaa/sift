# Start Sift automatically when you sign in to Windows (Task Scheduler, current user, no admin needed).
# The task runs scripts\run-local.ps1 hidden and restarts it every minute if it stops.
#   install:    powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
#   remove:     powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Remove
#   control:    Start-ScheduledTask Sift / Stop-ScheduledTask Sift / Get-ScheduledTask Sift
# Logs: logs\api.log, logs\worker.log, logs\scheduler.log
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "Sift"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed the '$name' task. Sift no longer starts at sign-in."
    } else {
        Write-Host "No '$name' task installed."
    }
    return
}

$script = Join-Path $PSScriptRoot "run-local.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$atLogOn = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Description "Sift mail assistant: API, worker and scheduler (scripts\run-local.ps1)" `
    -Action $action -Trigger @($atLogOn, $watchdog) -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Installed the '$name' task: Sift starts hidden at every sign-in; a 5-minute watchdog restarts it if it stops."
Write-Host "Start it now with: Start-ScheduledTask $name"
