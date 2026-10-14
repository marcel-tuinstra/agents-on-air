@echo off
cd /d "%~dp0"
py -3 start_studio.py %*
if errorlevel 1 pause
