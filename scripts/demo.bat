@echo off
rem Run Pitwall with the built-in demo car (no game needed).
cd /d "%~dp0\..\rig"
uv run --extra input pitwall-rig run --game demo --open %*
echo.
echo Pitwall stopped.
pause
