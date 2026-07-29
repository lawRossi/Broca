@echo off
chcp 65001 >nul
REM ============================================================================
REM Broca - Windows 安装入口（从 cmd.exe 启动 PowerShell 安装脚本）
REM ============================================================================
REM 用法:
REM   install.bat             以当前用户身份安装
REM   install.bat admin       以管理员身份安装（会弹出 UAC 提权窗口）
REM ============================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PS1_PATH=%SCRIPT_DIR%install.ps1"

REM ---- 检查 PowerShell 是否可用 ----
where powershell >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 未找到 PowerShell，请确保 Windows 已安装 PowerShell 5.1+。
    echo         https://aka.ms/powershell
    pause
    exit /b 1
)

REM ---- 检查 install.ps1 是否存在 ----
if not exist "%PS1_PATH%" (
    echo [ERROR] 未找到 %PS1_PATH%
    echo         请确保 install.bat 与 install.ps1 在同一目录。
    pause
    exit /b 1
)

REM ---- 处理管理员提权 ----
if /i "%~1"=="admin" goto :RUN_AS_ADMIN

REM 正常模式：在当前目录运行
echo [INFO] 正在启动 Broca Windows 安装程序...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% neq 0 (
    echo.
    echo [INFO] 安装未完整完成（退出码: %EXIT_CODE%）
    echo        如遇权限问题，请尝试以管理员身份运行:
    echo          右键 install.bat ^> 以管理员身份运行
    echo          或执行: install.bat admin
    pause
)
exit /b %EXIT_CODE%

:RUN_AS_ADMIN
REM 以管理员身份重新启动（通过 PowerShell 触发 UAC）
echo [INFO] 正在以管理员身份启动 Broca 安装程序...
echo.
powershell -Command ^
    "Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%PS1_PATH%\"' -Verb RunAs -Wait"
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% neq 0 (
    echo.
    echo [INFO] 管理员安装已完成或已取消（退出码: %EXIT_CODE%）
    pause
)
exit /b %EXIT_CODE%
