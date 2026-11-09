@echo off
setlocal
cd /d "%~dp0"
echo Downloading completed novel archives from GitHub Actions...
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\download_all_artifacts.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
  echo Download complete. See the Downloaded_Novels folder.
) else (
  echo Download finished with errors (exit code %RESULT%).
  echo Check the messages above and any failed-downloads.txt file.
)
echo.
pause
exit /b %RESULT%
