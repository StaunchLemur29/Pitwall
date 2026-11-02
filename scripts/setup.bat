@echo off
rem One-time setup on the rig PC. Needs uv (Python) and Node.js:
rem   winget install astral-sh.uv
rem   winget install OpenJS.NodeJS.LTS
setlocal
cd /d "%~dp0\.."

echo === Installing the rig service (Python) ===
pushd rig
uv sync --extra input || goto :fail
popd

echo === Building the dashboard ===
pushd dashboard
call npm ci || goto :fail
call npm run build || goto :fail
popd

echo.
echo Done. Start Pitwall with scripts\start.bat
exit /b 0

:fail
echo.
echo Setup failed - see the error above.
exit /b 1
