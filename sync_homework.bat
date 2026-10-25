@echo off
chcp 65001 > nul
echo ========================================================
echo       IoT 2569 Homework PR Checklist Synchronizer
echo ========================================================
echo.
python "%~dp0sync_homework.py"
echo.
pause
