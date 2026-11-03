@echo off
rem Start Pitwall for Assetto Corsa and open the dashboard on the vertical monitor.
rem Extra options pass straight through, e.g.:
rem   start.bat --record "%USERPROFILE%\pitwall-recordings\spa.pwrec"   (save raw telemetry)
rem   start.bat --game demo                                              (no game needed)
setlocal
cd /d "%~dp0\.."

rem Rebuild the dashboard so updates pulled from GitHub show up (takes a few seconds).
pushd dashboard
if not exist node_modules call npm ci --no-audit --no-fund
call npm run build --silent >nul || (echo Dashboard build failed - run scripts\setup.bat & popd & pause & exit /b 1)
popd

cd rig
uv run --extra input pitwall-rig run --open %*
echo.
echo Pitwall stopped.
pause
