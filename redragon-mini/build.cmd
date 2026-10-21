@echo off
setlocal
cd /d "%~dp0"
set "REDRAGON_CSC=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%REDRAGON_CSC%" set "REDRAGON_CSC=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%REDRAGON_CSC%" (
  echo Compilador do .NET Framework nao encontrado. Requer .NET Framework 4.8.
  exit /b 1
)
if not exist dist mkdir dist
"%REDRAGON_CSC%" /nologo /target:winexe /optimize+ /platform:anycpu /out:dist\RedragonMini.exe /win32manifest:src\app.manifest /reference:System.dll,System.Core.dll,System.Windows.Forms.dll,System.Drawing.dll,System.Runtime.Serialization.dll,System.Xml.dll src\*.cs
if errorlevel 1 exit /b 1
copy /y src\RedragonMini.exe.config dist\RedragonMini.exe.config >nul
echo Pronto: dist\RedragonMini.exe
