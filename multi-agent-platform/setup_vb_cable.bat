@echo off
setlocal ENABLEDELAYEDEXPANSION
title Install VB-Audio Virtual Cable (Bot Audio Routing)

:: Check for Administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo =======================================================
    echo Requesting Administrative Privileges...
    echo VB-Cable driver installation requires Administrator rights.
    echo =======================================================
    powershell -Command "Start-Process '%~0' -Verb RunAs"
    exit /b
)

echo =======================================================
echo Downloading and Installing VB-Audio Virtual Cable
echo =======================================================

:: Define variables
set "URL=https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
set "TEMP_DIR=%TEMP%\VBCable_Setup"
set "ZIP_FILE=%TEMP_DIR%\VBCABLE.zip"

:: Clean up old temp dir if exists
if exist "%TEMP_DIR%" rd /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo.
echo [1/3] Downloading VB-Cable Driver Pack...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP_FILE%'"
if not exist "%ZIP_FILE%" (
    echo [ERROR] Failed to download VB-Cable. Please check your internet connection.
    pause
    exit /b 1
)

echo.
echo [2/3] Extracting Driver Files...
powershell -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%TEMP_DIR%' -Force"

echo.
echo [3/3] Installing Driver Silently...
cd /d "%TEMP_DIR%"

:: Run 64-bit installer with silent install (-i) and hidden (-h) flags
VBCABLE_Setup_x64.exe -i -h

if %errorLevel% equ 0 (
    echo.
    echo =======================================================
    echo [SUCCESS] VB-Audio Virtual Cable Installed Successfully!
    echo.
    echo Attempting to register the new audio devices without 
    echo a system reboot by restarting Windows Audio services...
    echo =======================================================
    echo.
    echo Stopping Audio Services...
    net stop AudioEndpointBuilder /y
    
    echo Starting Audio Services...
    net start AudioEndpointBuilder
    net start Audiosrv
    
    echo.
    echo Audio services restarted. The CABLE Input/Output devices 
    echo should now be available to your bot.
    echo =======================================================
) else (
    echo.
    echo [WARNING] The installer returned code %errorLevel%.
    echo You may need to run VBCABLE_Setup_x64.exe manually.
)

echo.
echo Cleaning up temporary files...
cd /d "%~dp0"
rd /s /q "%TEMP_DIR%"

echo.
pause
