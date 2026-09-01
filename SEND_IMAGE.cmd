@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "SENDER=%PROJECT_DIR%scripts\send_image.py"

if "%~1"=="" (
  echo.
  echo ESL Simple Image Sender
  echo =======================
  echo Drag and drop one 250 x 132 PNG image onto SEND_IMAGE.cmd.
  echo.
  echo Opening this file alone does not write to the ESL.
  echo.
  pause
  exit /b 2
)

if not exist "%PYTHON%" (
  echo.
  echo ERROR: The project Python environment was not found.
  echo See the Environment section in the HTML specification.
  echo.
  pause
  exit /b 2
)

set "IMAGE_FILE=%~f1"

if not exist "%IMAGE_FILE%" (
  echo.
  echo ERROR: The selected image file was not found.
  echo.
  pause
  exit /b 2
)

pushd "%PROJECT_DIR%"
"%PYTHON%" "%SENDER%" "%IMAGE_FILE%"
set "SEND_RESULT=%ERRORLEVEL%"
popd

echo.
if "%SEND_RESULT%"=="0" (
  echo The operation finished.
) else (
  echo The operation did not complete. Read the message above.
)
echo.
pause
exit /b %SEND_RESULT%
