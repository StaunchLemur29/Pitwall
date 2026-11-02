@echo off
rem Start Pitwall for Assetto Corsa and open the dashboard on the vertical monitor.
rem Extra options pass straight through, e.g.:
rem   start.bat --record "%USERPROFILE%\Desktop\spa.pwrec"     (save raw telemetry)
rem   start.bat --game demo                                    (no game needed)
cd /d "%~dp0\..\rig"
uv run --extra input pitwall-rig run --open %*
echo.
echo Pitwall stopped.
pause
