@echo off
REM Explicitly start/resume the local v3 pipeline; no Codex or API is involved.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\axis-generic-training.ps1" -Start
set "axis_exit=%errorlevel%"
echo.
echo Exit code: %axis_exit%  [0=done, 2=data not ready, 130=interrupted]
echo Status and logs: N:\YGO-Kito\data\axis_generic\v3\automatic-full18-20261110-002
pause
exit /b %axis_exit%
