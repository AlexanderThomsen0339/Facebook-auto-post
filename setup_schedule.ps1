# Opretter en daglig opgave i Windows Opgavestyring, der starter content-agenten.
# Agenten spørger stadig om godkendelse, før den poster.
#
# Brug (i PowerShell, i repo-mappen):
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1              # hver dag kl. 09:00
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Time 08:30
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Remove      # fjern opgaven

param(
    [string]$Time = "09:00",
    [switch]$Remove
)

$TaskName = "Historisk Kapital content-agent"
$Dir = $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Opgaven '$TaskName' er fjernet."
    exit
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python blev ikke fundet i PATH. Installer Python med 'Add to PATH' først." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$Dir\.env")) {
    Write-Host "Der mangler en .env-fil i $Dir" -ForegroundColor Red
    exit 1
}

$Action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Dir\run_agent.bat`"" -WorkingDirectory $Dir
$Trigger   = New-ScheduledTaskTrigger -Daily -At $Time
# Kør kun når du er logget ind, så vinduet med godkendelsen kan vises
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
# StartWhenAvailable: hvis computeren var slukket kl. $Time, køres den når du logger ind
$Settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
             -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force | Out-Null

Write-Host "Opgaven '$TaskName' kører nu hver dag kl. $Time." -ForegroundColor Green
Write-Host "Test den med:  Start-ScheduledTask -TaskName '$TaskName'"
