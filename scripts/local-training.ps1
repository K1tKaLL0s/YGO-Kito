param(
 [ValidateSet('Start','Status','Stop','Resume')][string]$Action='Status',
 [ValidateSet('fusion','comparison','course','supervisor')][string]$Job='course',
 [string]$RunId='local-course-001',
 [string]$Distro='Chaos-Ubuntu-26.04'
)
$ErrorActionPreference='Stop'
if ($RunId -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid local run identity' }
$projectBase=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runDirectory=Join-Path $projectBase "reports\local-training\$RunId"
function Convert-ToWslPath([string]$path) {
 if ($path -notmatch '^([A-Za-z]):\\(.*)$') { throw 'Expected a local drive path' }
 return '/mnt/'+$Matches[1].ToLower()+'/'+$Matches[2].Replace('\','/')
}
$linuxBase=Convert-ToWslPath $projectBase
$python=$linuxBase+'/venv-linux/bin/python'
$policy=$linuxBase+'/reports/design-supervision-policy.json'
if ($Action -eq 'Status') {
 $statusPath=Join-Path $runDirectory 'status.json'
 if (-not (Test-Path -LiteralPath $statusPath)) { Write-Output 'No status exists for this run.'; return }
 $running=(& "$env:WINDIR\System32\wsl.exe" --list --running --quiet) -replace "`0",''
 if ($LASTEXITCODE -ne 0) { throw 'WSL state is unknown; no process was started.' }
 if (@($running | ForEach-Object {$_.Trim()}) -contains $Distro) {
  if ($Job -eq 'supervisor') {
   & "$env:WINDIR\System32\wsl.exe" -d $Distro --exec $python ($linuxBase+'/source/scripts/design_supervisor.py') --base $linuxBase --run-id $RunId --policy $policy --status
  } else {
   & "$env:WINDIR\System32\wsl.exe" -d $Distro --exec $python ($linuxBase+'/source/scripts/local_training_status.py') --base $linuxBase --run-id $RunId
  }
  if ($LASTEXITCODE -ne 0) { throw 'Live status lookup failed; no process was started.' }
 } else {
  $saved=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
  $saved | Add-Member -NotePropertyName process_identity_verified -NotePropertyValue $false -Force
  $saved | Add-Member -NotePropertyName distro_running -NotePropertyValue $false -Force
  $saved | ConvertTo-Json -Depth 12
 }
 return
}
if ($Action -eq 'Stop') {
 if (-not (Test-Path -LiteralPath $runDirectory)) { throw 'Unknown run; no stop request written' }
 [IO.File]::WriteAllText((Join-Path $runDirectory 'stop.request'),"Safe stop at the next complete boundary.`n")
 Write-Output 'Safe stop requested; inspect Status for its saved boundary.';return
}
if ($Job -ne 'supervisor' -and (Test-Path -LiteralPath (Join-Path $projectBase 'reports\training.hold.json'))) { throw 'Training is held for repair integration; no worker was launched.' }
if ($Job -eq 'course') {
 & "$env:WINDIR\System32\wsl.exe" -d $Distro --exec $python ($linuxBase+'/source/scripts/local_design_supervision.py') --base $linuxBase
 if ($LASTEXITCODE -ne 0) { throw 'Start the independent supervisor first; no training worker was launched.' }
}
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
if ($Job -eq 'supervisor') {
 $entry=$linuxBase+'/source/scripts/design_supervisor.py'
 $arguments=@('-d',$Distro,'--exec','/usr/bin/setsid','--wait',$python,'-u',$entry,'--base',$linuxBase,'--run-id',$RunId,'--policy',$policy)
} else {
 $entry=$linuxBase+'/source/scripts/local_training_worker.py'
 $arguments=@('-d',$Distro,'--exec','/usr/bin/setsid','--wait',$python,'-u',$entry,'--base',$linuxBase,'--run-id',$RunId,'--job',$Job)
}
if ($Action -eq 'Resume') { $arguments+='--resume' }
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$process=Start-Process -FilePath "$env:WINDIR\System32\wsl.exe" -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $projectBase -RedirectStandardOutput (Join-Path $runDirectory "console-$stamp.log") -RedirectStandardError (Join-Path $runDirectory "stderr-$stamp.log") -PassThru
$receipt=@{run_id=$RunId;job=$Job;windows_wsl_pid=$process.Id;launched_utc=[DateTime]::UtcNow.ToString('o');distro=$Distro;startup_file=$entry;launch_mode='hidden-independent-process-setsid-wait';resume=($Action -eq 'Resume')}
[IO.File]::WriteAllText((Join-Path $runDirectory "launch-$stamp.json"),($receipt|ConvertTo-Json))
$receipt|ConvertTo-Json
