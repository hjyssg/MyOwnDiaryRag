@echo off
REM 一键启动日记 Web 系统（在 webapp-backend 目录下运行）
cd /d "%~dp0"
python app.py
pause
