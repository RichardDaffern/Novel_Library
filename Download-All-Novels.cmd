@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Novel Library - Download Completed Novels
cd /d "%~dp0"
set "RESULT=1"

echo ====================================================
echo  Novel Library - Download completed GitHub archives
echo ====================================================
echo.
echo Current folder: %CD%
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: Windows PowerShell was not found.
    goto finished
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\download_all_artifacts.ps1" %*
set "RESULT=%ERRORLEVEL%"

:finished
echo.
if "%RESULT%"=="0" (
    echo SUCCESS: Finished downloading available novels.
) else (
    echo ERROR: Downloader exited with code %RESULT%.
    echo Please read the error messages above.
)
echo.
echo Last-run log, if created: "%~dp0download-last-run.log"
echo Local novels folder: "%~dp0Downloaded_Novels"
echo.
echo Press any key to close this window.
pause >nul
exit /b %RESULT%
