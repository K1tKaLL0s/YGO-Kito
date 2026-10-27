param(
  [ValidateSet('Start','Status','Stop','Resume')][string]$Action='Status',
  [ValidateSet('fusion','comparison','course')][string]$Job='fusion',
  [string]$RunId='foundation-fusion-001',
  [string]$Distro='Chaos-Ubuntu-26.04'
)
$ErrorActionPreference='Stop'
if ($RunId -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid local run identity' }
$projectBase=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runDirectory=Join-Path $projectBase "reports\local-training\$RunId"
$statusPath=Join-Path $runDirectory 'status.json'
function Convert-ToWslPath([string]$path) {
  if ($path -notmatch '^([A-Za-z]):\\(.*)$') { throw 'Expected a local drive path' }
  return '/mnt/'+$Matches[1].ToLower()+'/'+$Matches[2].Replace('\','/')
}
$linuxBase=Convert-ToWslPath $projectBase
if ($Action -eq 'Status') {
  if (-not (Test-Path -LiteralPath $statusPath)) { Write-Output 'No status exists for this run.'; return }
  $running=(& "$env:WINDIR\System32\wsl.exe" --list --running --quiet) -replace "`0",''
  if (@($running | ForEach-Object { $_.Trim() }) -contains $Distro) {
    & "$env:WINDIR\System32\wsl.exe" -d $Distro --exec ($linuxBase+'/venv-linux/bin/python') ($linuxBase+'/source/scripts/local_training_status.py') --base $linuxBase --run-id $RunId
    if ($LASTEXITCODE -ne 0) { throw 'Live status lookup failed; no training process was started.' }
  } else {
    $saved=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $saved | Add-Member -NotePropertyName process_identity_verified -NotePropertyValue $false -Force
    $saved | Add-Member -NotePropertyName distro_running -NotePropertyValue $false -Force
    $saved | Add-Member -NotePropertyName observation_only_no_worker_started -NotePropertyValue $true -Force
    $saved | ConvertTo-Json -Depth 12
  }
  return
}
if ($Action -eq 'Stop') {
  if (-not (Test-Path -LiteralPath $runDirectory)) { throw 'Unknown run; no stop request written' }
  [IO.File]::WriteAllText((Join-Path $runDirectory 'stop.request'),"Safe stop at the next complete learning boundary.`n")
  Write-Output 'Safe stop requested; inspect Status for the saved boundary.'
  return
}
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$entry=$linuxBase+'/source/scripts/local_training_worker.py'
$python=$linuxBase+'/venv-linux/bin/python'
$arguments=@('-d',$Distro,'--exec','/usr/bin/setsid','--wait',$python,'-u',$entry,'--base',$linuxBase,'--run-id',$RunId,'--job',$Job)
if ($Action -eq 'Resume') { $arguments+='--resume' }
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$process=Start-Process -FilePath "$env:WINDIR\System32\wsl.exe" -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $projectBase -RedirectStandardOutput (Join-Path $runDirectory "console-$stamp.log") -RedirectStandardError (Join-Path $runDirectory "stderr-$stamp.log") -PassThru
$receipt=@{run_id=$RunId;job=$Job;windows_wsl_pid=$process.Id;launched_utc=[DateTime]::UtcNow.ToString('o');distro=$Distro;startup_file=$entry;launch_mode='hidden-independent-process-setsid-wait';resume=($Action -eq 'Resume')}
[IO.File]::WriteAllText((Join-Path $runDirectory "launch-$stamp.json"),($receipt|ConvertTo-Json))
$receipt|ConvertTo-Json
