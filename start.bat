@echo off
setlocal
cd /d "%~dp0"
title Watermark Remover

where uv >nul 2>nul
if not errorlevel 1 goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" goto addpath
echo [1/2] Installing the uv installer - first run only...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
:addpath
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

:run
echo [2/2] Starting. The first run downloads about 700 MB, please wait...
echo       Keep this window open while you use the program.
uv run --python 3.11 --extra full --extra app wmremover-app
if errorlevel 1 (
  echo.
  echo Something went wrong. Take a screenshot of this window and send it.
  pause
)
