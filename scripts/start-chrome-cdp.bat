@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "PROFILE=%CD%\data\chrome_cdp_profile"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo Chrome nao encontrado. Instale o Google Chrome ou ajuste o caminho no .bat
  pause
  exit /b 1
)

if not exist "%PROFILE%" mkdir "%PROFILE%"

echo.
echo === Chrome CDP para Shopee ===
echo Perfil: %PROFILE%
echo Porta:  9222
echo.
echo IMPORTANTE ao logar:
echo   - Use E-MAIL ou TELEFONE da Shopee
echo   - NAO use "Continuar com Google" (da erro 400 do Google)
echo   - NAO use Facebook se pedir conta Google
echo.
echo Feche o Chrome normal antes de continuar.
pause

start "" "%CHROME%" ^
  --remote-debugging-port=9222 ^
  --remote-allow-origins=* ^
  --user-data-dir="%PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  "https://shopee.com.br/buyer/login"

echo Chrome iniciado. Faca login e deixe a janela aberta.
endlocal
