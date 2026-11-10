@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Double-click launcher for PDF-to-Novel. Paths are relative to this CMD,
rem not to the current working directory. No file is uploaded anywhere.
set "REPO_ROOT=%~dp0.."
set "PDF_DIR=%~dp0PDFs"
set "NOVEL_DIR=%~dp0Novels"
rem Environment overrides below are used by the isolated Windows CI smoke test.
if defined PDF_NOVEL_PDFS_DIR set "PDF_DIR=%PDF_NOVEL_PDFS_DIR%"
if defined PDF_NOVEL_NOVELS_DIR set "NOVEL_DIR=%PDF_NOVEL_NOVELS_DIR%"
if not exist "%PDF_DIR%" mkdir "%PDF_DIR%"
if not exist "%NOVEL_DIR%" mkdir "%NOVEL_DIR%"

pushd "%REPO_ROOT%"
if errorlevel 1 (
  echo ERROR: Cannot find the Novel_Library repository root.
  goto :failed_before_push
)

set "PY_CMD=py -3"
py -3 -c "import sys" >nul 2>&1
if errorlevel 1 (
  set "PY_CMD=python"
  python -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python 3 was not found. Install Python and enable the py launcher.
    goto :failed
  )
)

%PY_CMD% -c "import fitz, PIL" >nul 2>&1
if errorlevel 1 (
  echo Installing the free local PDF converter dependencies...
  %PY_CMD% -m pip install -r "requirements-pdf.txt"
  if errorlevel 1 (
    echo ERROR: Python dependencies could not be installed.
    goto :failed
  )
)

if not "%PDF_NOVEL_ASSUME_RIGHTS%"=="1" (
  echo.
  echo Convert only PDFs you are allowed to archive for personal use.
  choice /C YN /N /M "Proceed? [Y/N] "
  if errorlevel 2 (
    echo Cancelled. No PDF files were converted.
    goto :completed
  )
)

echo.
echo Converting PDFs to reader-compatible ZIPs...
%PY_CMD% -m tools.pdf_batch --pdf-dir "%PDF_DIR%" --output-dir "%NOVEL_DIR%" --confirm-rights
if errorlevel 1 goto :failed

goto :completed

:failed
set "EXIT_STATUS=1"
popd
goto :finish

:completed
set "EXIT_STATUS=0"
popd
goto :finish

:failed_before_push
set "EXIT_STATUS=1"

:finish
echo.
if "%EXIT_STATUS%"=="0" (echo Finished.) else (echo Finished with errors; review the messages above.)
if not "%PDF_NOVEL_NO_PAUSE%"=="1" pause
exit /b %EXIT_STATUS%