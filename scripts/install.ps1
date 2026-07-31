<#
.SYNOPSIS
    Broca - Windows 一键安装脚本 (PowerShell)
.DESCRIPTION
    本脚本会完成以下操作：
      1. 检查系统依赖 (Python 3.12+, Node.js/pnpm)
      2. 安装 broca Python 模块到虚拟环境
      3. 数据库迁移
      4. 配置 LLM 与用户配置
      5. 部署 Web 代码到 ~\.broca\web\
      6. 配置文件上传存储 (交互式，可跳过)
      7. 安装前端依赖并构建
      8. 打包 VS Code 插件
      9. 配置 Windows 服务 (NSSM) 或启动脚本
     10. 完成安装
.NOTES
    需要以管理员身份运行 (部分操作用于创建服务)。
    如果没有管理员权限，服务注册步骤会被跳过。

    从 cmd.exe 启动方式（推荐）:
      install.bat             普通模式
      install.bat admin       管理员模式（触发 UAC 提权）

    从 PowerShell 启动方式:
      powershell -ExecutionPolicy Bypass -File install.ps1
#>

#Requires -Version 5.1

# ---- 颜色 / 日志 ----
$Host.UI.RawUI.ForegroundColor = "White"
function Write-Info   { Write-Host "[INFO] " -ForegroundColor Green -NoNewline; Write-Host "$args" }
function Write-Warn   { Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host "$args" }
function Write-Error  { Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host "$args" }
function Write-Step   { Write-Host "`n==> " -ForegroundColor Blue -NoNewline; Write-Host "$args" }
function Write-Prompt { Write-Host "==> " -ForegroundColor Cyan -NoNewline }

# ---- 路径变量 ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."
$BrocaHome = "$env:USERPROFILE\.broca"
$BrocaVenv = "$BrocaHome\venv"
$BrocaWebDir = "$BrocaHome\web"
$BrocaDbDir = "$BrocaHome\data"
$BrocaConfigDir = "$BrocaHome\configs"
$BrocaLogDir = "$BrocaHome\logs"
$BrocaRunDir = "$BrocaHome\run"

# ---- 横幅 ----
Write-Host "===========================================" -ForegroundColor Blue
Write-Host "       Broca - Windows Installer" -ForegroundColor Blue
Write-Host "===========================================" -ForegroundColor Blue
Write-Host ""

# ============================================================================
# Step 1: 检查系统依赖
# ============================================================================
Write-Step "Step 1/9: 检查系统依赖..."

# --- Python ---
$Python = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match '(\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 12) {
                $Python = $cmd
                break
            }
        }
    } catch {}
}

if (-not $Python) {
    Write-Error "需要 Python >= 3.12，请先安装：https://www.python.org/downloads/"
    Write-Host "  安装时请确保勾选 'Add Python to PATH'"
    pause
    exit 1
}
$pyVersion = & $Python --version 2>&1
Write-Info "Python: $($pyVersion.Trim())"

# --- pip ---
try {
    $pipVer = & $Python -m pip --version 2>&1
    Write-Info "pip: $($pipVer.Split(' ')[1])"
} catch {
    Write-Error "pip 未安装，请先安装 pip。"
    pause
    exit 1
}

# --- Node.js / npm / pnpm ---
$UsePnpm = $false
$PnpmMajorVersion = 0
$HasNode = $false

# 先直接检测 node 本身（不依赖 npm/pnpm）
try {
    $nodeVer = node --version 2>&1
    $HasNode = $true
    Write-Info "Node.js: $($nodeVer.Trim())"
} catch {
    Write-Warn "未检测到 Node.js，将跳过前端构建和 VS Code 插件打包。"
    Write-Warn "如需前端页面或 VS Code 插件，请先安装 Node.js (推荐 v18+)：https://nodejs.org"
}

# 再分别检测 pnpm 和 npm
if ($HasNode) {
    # 检测 pnpm
    try {
        $pnpmVer = pnpm --version 2>&1
        $pnpmVerTrimmed = $pnpmVer.Trim()
        $PnpmMajorVersion = [int](($pnpmVerTrimmed -split '\.')[0])

        # pnpm v6 以下版本过旧
        $MinPnpmMajorVersion = 6
        if ($PnpmMajorVersion -ge $MinPnpmMajorVersion) {
            $UsePnpm = $true
            Write-Info "pnpm: $pnpmVerTrimmed (major v$PnpmMajorVersion)"
        } else {
            Write-Warn "pnpm: $pnpmVerTrimmed — 版本过旧 (v$PnpmMajorVersion)，最低要求 v$MinPnpmMajorVersion"
            Write-Info "尝试升级 pnpm..."
            $upgradeOutput = npm install -g pnpm@latest 2>&1
            if ($LASTEXITCODE -eq 0) {
                $newPnpmVer = (pnpm --version 2>&1).Trim()
                $newPnpmMajor = [int](($newPnpmVer -split '\.')[0])
                if ($newPnpmMajor -ge $MinPnpmMajorVersion) {
                    $UsePnpm = $true
                    $PnpmMajorVersion = $newPnpmMajor
                    Write-Info "pnpm 升级成功: $pnpmVerTrimmed → $newPnpmVer"
                } else {
                    Write-Warn "pnpm 升级后版本仍过低 (v$newPnpmMajor)，将回退到 npm"
                    $UsePnpm = $false
                }
            } else {
                Write-Warn "pnpm 自动升级失败，将回退到 npm"
                Write-Host $upgradeOutput
                $UsePnpm = $false
            }
        }
    } catch {
        # pnpm 未安装，属于正常情况，不用报错
        Write-Info "pnpm: 未安装，将使用 npm"
        $UsePnpm = $false
    }

    # 检测 npm
    if (-not $UsePnpm) {
        try {
            $npmVer = npm --version 2>&1
            $npmMajorVersion = [int]($npmVer.Trim() -split '\.')[0]
            Write-Info "npm: $($npmVer.Trim()) (major v$npmMajorVersion)"

            # 检查 npm 版本，如果低于最低要求则升级
            $MinNpmMajorVersion = 8
            if ($npmMajorVersion -lt $MinNpmMajorVersion) {
                Write-Warn "npm v$npmMajorVersion 版本过旧，最低要求 v$MinNpmMajorVersion，尝试升级..."
                $upgradeOutput = npm install -g npm@latest 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $newNpmVer = npm --version 2>&1
                    $newNpmMajor = [int]($newNpmVer.Trim() -split '\.')[0]
                    Write-Info "npm 升级成功: v$npmMajorVersion → v$($newNpmVer.Trim())"
                    $npmVer = $newNpmVer
                    $npmMajorVersion = $newNpmMajor
                } else {
                    Write-Warn "npm 自动升级失败，可之后手动执行: npm install -g npm@latest"
                    Write-Warn "将继续使用现有版本，如遇到依赖问题请手动升级 npm"
                }
            }
        } catch {
            Write-Warn "npm: 未检测到，虽然 Node.js 已安装但 npm 不可用"
            Write-Warn "请确保 npm 已正确安装或在 PATH 中"
        }
    }
}

# --- 管理员检测 ---
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Warn "未以管理员身份运行，服务注册步骤将被跳过。"
    Write-Warn "如需注册 Windows 服务，请以管理员身份重新运行此脚本。"
}

# ============================================================================
# Step 2: 安装 broca Python 模块（虚拟环境）
# ============================================================================
Write-Step "Step 2/9: 安装 broca Python 模块..."

Set-Location $ProjectRoot

# 检测是否已在虚拟环境中
$InVenv = $false
if ($env:VIRTUAL_ENV) {
    $InVenv = $true
    $BrocaVenv = $env:VIRTUAL_ENV
    Write-Info "检测到已激活的虚拟环境: $BrocaVenv"
}

if ($InVenv) {
    $BrocaPython = "$BrocaVenv\Scripts\python.exe"
    Write-Info "直接使用当前虚拟环境: $(& $BrocaPython --version 2>&1)"
} elseif (Test-Path "$BrocaVenv\Scripts\python.exe") {
    Write-Info "检测到已有的 broca 虚拟环境: $BrocaVenv"
    try {
        & "$BrocaVenv\Scripts\python.exe" --version 2>&1 | Out-Null
        & "$BrocaVenv\Scripts\python.exe" -m pip --version 2>&1 | Out-Null
        Write-Info "虚拟环境有效，复用: $BrocaVenv"
    } catch {
        Write-Warn "虚拟环境不完整，将重新创建..."
        Remove-Item -Recurse -Force $BrocaVenv -ErrorAction SilentlyContinue
        Write-Info "创建 broca 专属虚拟环境..."
        & $Python -m venv $BrocaVenv
        if (-not $?) { Write-Error "虚拟环境创建失败"; pause; exit 1 }
        Write-Info "虚拟环境创建成功"
    }
    $BrocaPython = "$BrocaVenv\Scripts\python.exe"
} else {
    Write-Info "创建 broca 专属虚拟环境: $BrocaVenv"
    $null = New-Item -ItemType Directory -Force -Path $BrocaVenv
    & $Python -m venv $BrocaVenv
    if (-not $?) { Write-Error "虚拟环境创建失败"; pause; exit 1 }
    Write-Info "虚拟环境创建成功"
    $BrocaPython = "$BrocaVenv\Scripts\python.exe"
}
Write-Info "使用虚拟环境 Python: $(& $BrocaPython --version 2>&1)"

# 升级 pip
Write-Info "升级 pip..."
& $BrocaPython -m pip install --upgrade pip setuptools wheel build 2>&1 | Out-Null
Write-Info "pip 升级完成"

# 安装 broca 模块
Write-Info "安装 broca 模块..."
$pipOutput = & $BrocaPython -m pip install $ProjectRoot 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "broca 模块安装失败"
    Write-Host $pipOutput
    pause
    exit 1
}
Write-Info "broca 模块安装完成"

# 安装后端依赖
Write-Info "安装后端依赖..."
$pipOutput = & $BrocaPython -m pip install "$ProjectRoot\broca-web\backend" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Info "后端依赖安装完成"
} else {
    Write-Warn "后端依赖安装失败，可之后手动执行: $BrocaPython -m pip install $ProjectRoot\broca-web\backend"
}

# 安装 TUI
$tuiDir = "$ProjectRoot\broca-tui"
if (Test-Path $tuiDir) {
    Write-Info "安装 TUI 依赖..."
    $pipOutput = & $BrocaPython -m pip install $tuiDir 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Info "TUI 依赖安装完成"
    } else {
        Write-Warn "TUI 依赖安装失败，可之后手动执行: $BrocaPython -m pip install $tuiDir"
    }
} else {
    Write-Warn "broca-tui 目录不存在，跳过 TUI 安装"
}

# 将 Python 指向虚拟环境的
$Python = $BrocaPython

# ============================================================================
# Step 3: 数据库迁移
# ============================================================================
Write-Step "Step 3/9: 数据库迁移..."

# Windows 中文系统默认编码为 GBK，强制 Python 使用 UTF-8 读取配置文件
$env:PYTHONUTF8 = 1

$null = New-Item -ItemType Directory -Force -Path $BrocaDbDir
Write-Info "数据库目录: $BrocaDbDir"

# 迁移1: broca 主数据库
Write-Info "迁移 broca 主数据库..."
Set-Location $ProjectRoot
$env:BROCA_DATABASE_DIR = $BrocaDbDir
$alembicOutput = & $Python -m alembic -c broca/alembic.ini upgrade head 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Info "broca 主数据库迁移完成"
} else {
    Write-Warn "broca 主数据库迁移失败（可之后手动执行: alembic -c broca/alembic.ini upgrade head）"
    Write-Host $alembicOutput
}

# 迁移2: 后端数据库
Write-Info "迁移后端数据库..."
$backendDb = "$BrocaDbDir\backend.db"
Set-Location "$ProjectRoot\broca-web\backend"
$env:SQLITE_DATABASE_PATH = "sqlite:///${backendDb}"
$alembicOutput = & $Python -m alembic upgrade head 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Info "后端数据库迁移完成"
} else {
    Write-Warn "后端数据库迁移失败（可之后手动执行: alembic upgrade head）"
    Write-Host $alembicOutput
}

Remove-Item Env:\BROCA_DATABASE_DIR -ErrorAction SilentlyContinue
Remove-Item Env:\SQLITE_DATABASE_PATH -ErrorAction SilentlyContinue
Remove-Item Env:\PYTHONUTF8 -ErrorAction SilentlyContinue
Set-Location $ProjectRoot

# ============================================================================
# Step 4: 配置 LLM 与用户配置
# ============================================================================
Write-Step "Step 4/9: 配置 LLM 与用户配置..."

$null = New-Item -ItemType Directory -Force -Path $BrocaConfigDir

# ---- 复制 configs.json ----
$configDst = "$BrocaConfigDir\configs.json"
$configSrc = "$ProjectRoot\configs\configs.json"
if (-not (Test-Path $configDst)) {
    if (Test-Path $configSrc) {
        Copy-Item $configSrc $configDst
        # 替换路径为 Windows 风格
        (Get-Content $configDst) `
            -replace '"database_dir":\s*"[^"]*"', ('"database_dir": "' + $BrocaDbDir.Replace('\', '\\') + '",') `
            -replace '"llm_config_file":\s*"[^"]*"', ('"llm_config_file": "' + $BrocaConfigDir.Replace('\', '\\') + '\\llm_config.json",') `
            -replace '"log_file":\s*"[^"]*"', ('"log_file": "' + $BrocaLogDir.Replace('\', '\\') + '\\agent.log"') `
        | Set-Content $configDst -Encoding UTF8
        Write-Info "已创建用户配置: $configDst"
    } else {
        Write-Warn "未找到默认配置: $configSrc"
    }
} else {
    Write-Info "用户配置已存在: $configDst（跳过）"
}

# ---- 复制 llm_config.json ----
$llmDst = "$BrocaConfigDir\llm_config_template.json"
$llmConfig = "$BrocaConfigDir\llm_config.json"
$llmSrc = "$ProjectRoot\configs\llm_config_template.json"
if (Test-Path $llmSrc) {
    Copy-Item $llmSrc $llmDst -Force
    if (-not (Test-Path $llmConfig)) {
        Copy-Item $llmSrc $llmConfig
        Write-Info "已创建用户 LLM 配置: $llmConfig"
    } else {
        Write-Info "用户 LLM 配置已存在: $llmConfig（跳过）"
    }
}

# ---- 复制 Agent 配置 ----
$agentsSrc = "$ProjectRoot\configs\agents"
$agentsDst = "$BrocaConfigDir\agents"
if (Test-Path $agentsSrc) {
    $null = New-Item -ItemType Directory -Force -Path $agentsDst
    Copy-Item "$agentsSrc\*" $agentsDst -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info "Agent 配置已更新: $agentsDst"
} else {
    Write-Warn "未找到 Agent 配置目录: $agentsSrc"
}

# ---- 复制 tool_permission_config.json ----
$permDst = "$BrocaConfigDir\tool_permission_config.json"
$permSrc = "$ProjectRoot\configs\tool_permission_config.json"
if (Test-Path $permSrc) {
    Copy-Item $permSrc $permDst -Force
    Write-Info "已创建工具权限配置: $permDst"
} else {
    Write-Warn "未找到默认工具权限配置: $permSrc"
}

# ---- 复制 Skills ----
$skillsDst = "$BrocaHome\skills"
$skillsSrc = "$ProjectRoot\skills"
if (Test-Path $skillsSrc) {
    $null = New-Item -ItemType Directory -Force -Path $skillsDst
    Copy-Item "$skillsSrc\*" $skillsDst -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info "Skills 已部署: $skillsDst"
} else {
    Write-Warn "未找到 Skills 目录: $skillsSrc"
}

Write-Host ""
Write-Host "  配置文件"
Write-Host "  ────────────────────────────────────────────"
Write-Host "  configs.json   → $BrocaConfigDir\configs.json"
Write-Host "  llm_config.json → $BrocaConfigDir\llm_config.json"
Write-Host ""
Write-Host "  首次安装会自动创建用户配置副本，之后你可安全地编辑它们。"
Write-Host "  单个 LLM Key 也可通过环境变量覆盖:"
Write-Host '    $env:BROCA_API_KEY_{PROVIDER} = "your-key"'
Write-Host "  ────────────────────────────────────────────"
Write-Host ""

# ============================================================================
# Step 5: 部署 Web 代码到 ~\.broca\web\
# ============================================================================
Write-Step "Step 5/9: 部署 Web 代码..."

$null = New-Item -ItemType Directory -Force -Path $BrocaWebDir

# 复制后端代码
$backendSrc = "$ProjectRoot\broca-web\backend"
$backendDst = "$BrocaWebDir\backend"
if (Test-Path $backendSrc) {
    if (Test-Path $backendDst) { Remove-Item $backendDst -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item $backendSrc $backendDst -Recurse -Force
    Write-Info "后端代码已部署: $backendDst"
} else {
    Write-Error "后端代码目录不存在: $backendSrc"
    pause
    exit 1
}

# 复制前端源码
$frontendSrc = "$ProjectRoot\broca-web\frontend"
$frontendDst = "$BrocaWebDir\frontend"
if (Test-Path $frontendSrc) {
    if (Test-Path $frontendDst) { Remove-Item $frontendDst -Recurse -Force -ErrorAction SilentlyContinue }
    # 排除 node_modules/dist/.env.*
    $exclude = @('node_modules', 'dist', '.env.*')
    Copy-Item $frontendSrc $frontendDst -Recurse -Force -Exclude $exclude
    Write-Info "前端源码已部署: $frontendDst"
} else {
    Write-Error "前端源码目录不存在: $frontendSrc"
    pause
    exit 1
}

# ============================================================================
# Step 6: 配置文件上传存储 (交互式)
# ============================================================================
Write-Step "Step 6/9: 配置文件上传存储..."

$envFile = "$frontendDst\.env.production"

function Has-StorageConfig {
    param([string]$path)
    if (-not (Test-Path $path)) { return $false }
    $content = Get-Content $path -Raw
    # Cloudflare R2
    if ($content -match 'VITE_CLOUDFLARE_ACCOUNT_ID=' -and $content -match 'VITE_CLOUDFLARE_ACCESS_KEY_ID=' -and $content -match 'VITE_CLOUDFLARE_SECRET_ACCESS_KEY=') {
        return $true
    }
    # Supabase S3
    if ($content -match 'VITE_SUPABASE_URL=' -and $content -match 'VITE_SUPABASE_S3_ACCESS_KEY_ID=' -and $content -match 'VITE_SUPABASE_S3_SECRET_ACCESS_KEY=') {
        return $true
    }
    return $false
}

if (Has-StorageConfig $envFile) {
    Write-Info "检测到文件上传存储已配置。如需要更改，请编辑 $envFile 后重新构建前端。"
} else {
    Write-Host ""
    Write-Host "  Broca 前端支持文件上传功能，需要配置 S3 兼容的存储后端。"
    Write-Host "  支持的存储后端："
    Write-Host "    (1) Cloudflare R2  — 推荐，免费额度高，全球加速"
    Write-Host "    (2) Supabase S3    — 如已使用 Supabase 可复用"
    Write-Host ""
    Write-Host "  你可以现在配置，也可以跳过（之后手动编辑 .env.production 再构建）。"
    Write-Host ""

    Write-Prompt "是否配置文件上传存储？(y/N) "
    $configureStorage = Read-Host
    if ($configureStorage -match '^[Yy]') {
        Write-Host ""
        Write-Host "  选择存储后端:"
        Write-Host "    (1) Cloudflare R2"
        Write-Host "    (2) Supabase S3"
        Write-Prompt "  请选择 (1 或 2): "
        $storageChoice = Read-Host

        switch ($storageChoice) {
            "1" {
                Write-Host ""
                Write-Host "  Cloudflare R2 配置"
                Write-Host "  ────────────────────────────────────────"
                Write-Host "  需要 R2 存储的以下信息（可在 Cloudflare Dashboard > R2 获取）："
                Write-Host ""

                Write-Prompt "  Account ID: "
                $cfAccountId = Read-Host

                Write-Prompt "  Access Key ID: "
                $cfAccessKey = Read-Host

                Write-Prompt "  Secret Access Key: "
                $cfSecret = Read-Host -AsSecureString
                $cfSecretPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($cfSecret))

                Write-Prompt "  Bucket 名称 [upload]: "
                $cfBucket = Read-Host
                if ([string]::IsNullOrWhiteSpace($cfBucket)) { $cfBucket = "upload" }

                Write-Prompt "  公开访问域名 (可选): "
                $cfPubUrl = Read-Host

                if (-not [string]::IsNullOrWhiteSpace($cfAccountId) -and -not [string]::IsNullOrWhiteSpace($cfAccessKey) -and -not [string]::IsNullOrWhiteSpace($cfSecretPlain)) {
                    # 写入 .env.production
                    @"
VITE_CLOUDFLARE_ACCOUNT_ID=$cfAccountId
VITE_CLOUDFLARE_ACCESS_KEY_ID=$cfAccessKey
VITE_CLOUDFLARE_SECRET_ACCESS_KEY=$cfSecretPlain
VITE_CLOUDFLARE_BUCKET=$cfBucket
"@ | Out-File $envFile -Encoding UTF8
                    if (-not [string]::IsNullOrWhiteSpace($cfPubUrl)) {
                        "VITE_CLOUDFLARE_PUBLIC_URL=$cfPubUrl" | Out-File $envFile -Append -Encoding UTF8
                    } else {
                        "# VITE_CLOUDFLARE_PUBLIC_URL=https://pub-xxxx.r2.dev" | Out-File $envFile -Append -Encoding UTF8
                    }
                    "# VITE_SUPABASE_URL=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_SUPABASE_S3_ACCESS_KEY_ID=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_SUPABASE_S3_SECRET_ACCESS_KEY=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_SUPABASE_BUCKET=" | Out-File $envFile -Append -Encoding UTF8
                    Write-Info "Cloudflare R2 存储配置已保存。"
                } else {
                    Write-Warn "配置不完整（Account ID、Access Key、Secret 为必填），已跳过。"
                    Write-Host "  可之后编辑 $envFile 手动配置。"
                }
                break
            }
            "2" {
                Write-Host ""
                Write-Host "  Supabase S3 配置"
                Write-Host "  ────────────────────────────────────────"
                Write-Host ""

                Write-Prompt "  Supabase URL: "
                $supabaseUrl = Read-Host

                Write-Prompt "  S3 Access Key ID: "
                $supabaseAccessKey = Read-Host

                Write-Prompt "  S3 Secret Access Key: "
                $supabaseSecret = Read-Host -AsSecureString
                $supabaseSecretPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($supabaseSecret))

                Write-Prompt "  Bucket 名称 [upload]: "
                $supabaseBucket = Read-Host
                if ([string]::IsNullOrWhiteSpace($supabaseBucket)) { $supabaseBucket = "upload" }

                if (-not [string]::IsNullOrWhiteSpace($supabaseUrl) -and -not [string]::IsNullOrWhiteSpace($supabaseAccessKey) -and -not [string]::IsNullOrWhiteSpace($supabaseSecretPlain)) {
                    @"
VITE_SUPABASE_URL=$supabaseUrl
VITE_SUPABASE_S3_ACCESS_KEY_ID=$supabaseAccessKey
VITE_SUPABASE_S3_SECRET_ACCESS_KEY=$supabaseSecretPlain
VITE_SUPABASE_BUCKET=$supabaseBucket
"@ | Out-File $envFile -Encoding UTF8
                    "# VITE_CLOUDFLARE_ACCOUNT_ID=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_CLOUDFLARE_ACCESS_KEY_ID=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_CLOUDFLARE_SECRET_ACCESS_KEY=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_CLOUDFLARE_BUCKET=" | Out-File $envFile -Append -Encoding UTF8
                    "# VITE_CLOUDFLARE_PUBLIC_URL=" | Out-File $envFile -Append -Encoding UTF8
                    Write-Info "Supabase S3 存储配置已保存。"
                } else {
                    Write-Warn "配置不完整（URL、Access Key、Secret 为必填），已跳过。"
                    Write-Host "  可之后编辑 $envFile 手动配置。"
                }
                break
            }
            default {
                Write-Warn "无效选择，跳过存储配置。"
                Write-Host "  可之后编辑 $envFile 手动配置。"
            }
        }
    } else {
        Write-Info "跳过文件上传存储配置。"
        Write-Host "  如需后续配置，请编辑 $envFile 后重新构建前端。"
    }
}

# API 基地址使用相对路径（由 nginx/IIS 代理）
"# VITE_API_BASE_URL=" | Out-File $envFile -Append -Encoding UTF8
"# VITE_BROCA_SOCKET_SERVER_URL=" | Out-File $envFile -Append -Encoding UTF8

# ============================================================================
# Step 7: 安装前端依赖并构建（需要 Node.js）
# ============================================================================
if ($HasNode) {
Write-Step "Step 7/9: 安装前端依赖并构建..."

Set-Location $frontendDst

# 根据 pnpm 版本生成 build 权限配置
function Write-PnpmBuildConfig {
    param([string]$dir, [int]$majorVer)
    if ($majorVer -ge 11) {
        @"
allowBuilds:
  esbuild: true
  msw: true
  vue-demi: true
"@ | Out-File "$dir\pnpm-workspace.yaml" -Encoding UTF8
    } else {
        @"
onlyBuiltDependencies[]=esbuild
onlyBuiltDependencies[]=msw
onlyBuiltDependencies[]=vue-demi
"@ | Out-File "$dir\.npmrc" -Encoding UTF8
    }
}

if ($UsePnpm) {
    Write-Info "使用 pnpm v$PnpmMajorVersion 安装前端依赖..."
    Write-PnpmBuildConfig $frontendDst $PnpmMajorVersion
    # 删除旧锁文件
    Remove-Item "$frontendDst\pnpm-lock.yaml" -Force -ErrorAction SilentlyContinue
    $buildOutput = pnpm install 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pnpm install 失败"
        Write-Host $buildOutput
        pause
        exit 1
    }
    Write-Host $buildOutput | Select-Object -Last 5
} else {
    # 尝试安装 pnpm
    Write-Info "正在安装 pnpm (项目依赖 pnpm 管理)..."
    $buildOutput = npm install -g pnpm 2>&1
    if ($LASTEXITCODE -eq 0) {
        $UsePnpm = $true
        $PnpmMajorVersion = [int]((pnpm --version 2>&1).Trim() -split '\.')[0]
        Write-Info "pnpm v$PnpmMajorVersion 安装成功"
        Write-PnpmBuildConfig $frontendDst $PnpmMajorVersion
        Remove-Item "$frontendDst\pnpm-lock.yaml" -Force -ErrorAction SilentlyContinue
        $buildOutput = pnpm install 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Error "pnpm install 失败"
            Write-Host $buildOutput
            pause
            exit 1
        }
        Write-Host $buildOutput | Select-Object -Last 5
    } else {
        Write-Warn "pnpm 安装失败，回退到 npm (使用 --legacy-peer-deps)..."
        $buildOutput = npm install --legacy-peer-deps 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Error "npm install 失败"
            Write-Host $buildOutput
            pause
            exit 1
        }
        Write-Host $buildOutput | Select-Object -Last 5
    }
}

Write-Info "构建前端 (production mode)..."
$buildOutput = npx vite build 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "前端构建失败"
    Write-Host $buildOutput
    pause
    exit 1
}
Write-Host $buildOutput | Select-Object -Last 10
Write-Info "前端构建完成: $frontendDst\dist"

} else {
    Write-Warn "跳过前端构建（未检测到 Node.js）"
}

# ============================================================================
# Step 8: 打包 VS Code 插件（需要 Node.js）
# ============================================================================
if ($HasNode) {
Write-Step "Step 8/9: 打包 VS Code 插件..."

$vscodeDir = "$ProjectRoot\broca-vscode"
if (Test-Path $vscodeDir) {
    Set-Location $vscodeDir
    Write-Info "使用 npm 安装 VS Code 插件依赖..."
    $buildOutput = npm install 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Info "打包 VS Code 插件..."
        $buildOutput = npm run package 2>&1
        if ($LASTEXITCODE -eq 0) {
            $vsixFile = Get-ChildItem "$vscodeDir\*.vsix" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($vsixFile) {
                Write-Info "VS Code 插件已打包: $($vsixFile.FullName)"
            } else {
                Write-Warn "未找到生成的 .vsix 文件"
            }
        } else {
            Write-Warn "VS Code 插件打包失败"
            Write-Host $buildOutput
        }
    } else {
        Write-Warn "npm install 失败"
        Write-Host $buildOutput
    }
} else {
    Write-Warn "未找到 VS Code 插件目录: $vscodeDir"
}

} else {
    Write-Warn "跳过 VS Code 插件打包（未检测到 Node.js）"
}

Set-Location $ProjectRoot

# ============================================================================
# Step 9: 创建启动脚本和服务配置
# ============================================================================
Write-Step "Step 9/9: 创建启动脚本和服务配置..."

$null = New-Item -ItemType Directory -Force -Path $BrocaRunDir, $BrocaLogDir

# ---- 生成启动脚本 ----
$startScript = "$BrocaHome\start-broca.ps1"
$startScriptContent = @"
# Broca - Windows 启动脚本
# 由 install.ps1 自动生成

# 后端
`$backProcess = Start-Process -NoNewWindow -PassThru -FilePath "$BrocaPython" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level info" -WorkingDirectory "$backendDst"
Write-Host "[INFO] 后端已启动 (PID: `$(`$backProcess.Id))"

"@

if ($HasNode) {
    $startScriptContent += @"

# 前端 (使用 Python 内置 http.server 提供静态文件)
`$frontProcess = Start-Process -NoNewWindow -PassThru -FilePath "$BrocaPython" -ArgumentList "-m http.server 5166 --directory $frontendDst\dist" -WorkingDirectory "$frontendDst\dist"
Write-Host "[INFO] 前端已启动 (PID: `$(`$frontProcess.Id))"

"@
}

$startScriptContent += @"
Write-Host ""
Write-Host "  Broca 服务已启动:"
"@

if ($HasNode) {
    $startScriptContent += @"
Write-Host "  前端: http://localhost:5166"
"@
}

$startScriptContent += @"
Write-Host "  后端: http://localhost:9000"
"@

if ($HasNode) {
    $startScriptContent += @"
Write-Host "  Socket.IO: ws://localhost:6868"
"@
}

$startScriptContent += @"
Write-Host ""
Write-Host "  按 Ctrl+C 停止所有服务"

# 等待进程结束
try {
    `$backProcess.WaitForExit()
} finally {
    if (-not `$backProcess.HasExited) { `$backProcess.Kill() }
"@

if ($HasNode) {
    $startScriptContent += @"
    if (-not `$frontProcess.HasExited) { `$frontProcess.Kill() }
"@
}

$startScriptContent += @"
}
"@

$startScriptContent | Out-File $startScript -Encoding UTF8
Write-Info "启动脚本已创建: $startScript"

# ---- 生成停止脚本 ----
$stopScript = "$BrocaHome\stop-broca.ps1"
# 构建停止脚本内容（根据是否有前端来条件包含）
$stopBody = @'
# Broca - Windows 停止脚本

try {
    $backPid = Get-CimInstance Win32_Process -Filter "name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "uvicorn.*app\.main" } |
        Select-Object -ExpandProperty ProcessId -First 1
} catch {
    $backPid = $null
}

if ($backPid) { Stop-Process -Id $backPid -Force; Write-Host "[INFO] 后端进程已停止 (PID: $backPid)" }
'@

if ($HasNode) {
    $stopBody += @'

try {
    $frontPid = Get-CimInstance Win32_Process -Filter "name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "http\.server.*5166" } |
        Select-Object -ExpandProperty ProcessId -First 1
} catch {
    $frontPid = $null
}

if ($frontPid) { Stop-Process -Id $frontPid -Force; Write-Host "[INFO] 前端进程已停止 (PID: $frontPid)" }
'@
}

if ($HasNode) {
    $stopBody += @"

if (-not `$backPid -and -not `$frontPid) {
    Write-Host "[INFO] 未发现运行中的 Broca 服务"
}
"@
} else {
    $stopBody += @"

if (-not `$backPid) {
    Write-Host "[INFO] 未发现运行中的 Broca 服务"
}
"@
}

$stopBody | Out-File $stopScript -Encoding UTF8

Write-Info "停止脚本已创建: $stopScript"

# 检测 nginx（前端需要）
$NginxFound = $false
if ($HasNode) {
    $nginxCmd = Get-Command nginx.exe -ErrorAction SilentlyContinue
    if ($nginxCmd) {
        Write-Info "nginx: $($nginxCmd.Source)"
        $NginxFound = $true
    } else {
        # 检查常见安装位置
        foreach ($p in @("$env:ProgramFiles\nginx\nginx.exe", "$env:LOCALAPPDATA\nginx\nginx.exe", "C:\nginx\nginx.exe")) {
            if (Test-Path $p) {
                Write-Info "nginx: $p"
                $NginxFound = $true
                break
            }
        }
        if (-not $NginxFound) {
            Write-Warn "未检测到 nginx，尝试自动安装..."
            try {
                $wingetOut = winget install --id Nginx.Nginx -e --accept-source-agreements --accept-package-agreements 2>&1
                Write-Host $wingetOut
                $nginxCmd = Get-Command nginx.exe -ErrorAction SilentlyContinue
                if ($nginxCmd) { $NginxFound = $true }
            } catch {
                Write-Warn "winget 安装 nginx 失败"
            }
        }
    }
    if ($NginxFound) {
        Write-Info "nginx 前端部署就绪（broca service start 时启用）"
    } else {
        Write-Warn "nginx 不可用，前端将无法部署。"
        Write-Warn "请手动安装 nginx for Windows: https://nginx.org/en/download.html"
        Write-Warn "  或运行: winget install Nginx.Nginx"
        Write-Warn "安装后重新运行 install.bat admin"
    }
} else {
    Write-Warn "未构建前端（未检测到 Node.js），跳过 nginx 配置"
}


# ---- 注册 Windows 服务 (NSSM) ----
if ($IsAdmin) {
    $nssmPath = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($nssmPath) {
        Write-Info "注册 Windows 服务..."

        # 后端服务
        & nssm.exe stop BrocaBackend 2>&1 | Out-Null
        & nssm.exe remove BrocaBackend confirm 2>&1 | Out-Null
        & nssm.exe install BrocaBackend "$BrocaPython" "-m uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level info" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend AppDirectory "$backendDst" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend DisplayName "Broca Backend Service" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend Description "Broca AI Agent 框架后端服务" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend Start SERVICE_AUTO_START 2>&1 | Out-Null
        & nssm.exe set BrocaBackend AppStdout "$BrocaLogDir\backend.out.log" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend AppStderr "$BrocaLogDir\backend.err.log" 2>&1 | Out-Null
        & nssm.exe set BrocaBackend AppEnvironmentExtra "PYTHONPATH=$backendDst" "BROCA_CONFIG=$BrocaConfigDir\configs.json" "BROCA_DATABASE_DIR=$BrocaDbDir" "BROCA_LLM_CONFIG=$BrocaConfigDir\llm_config.json" "BROCA_AGENTS_CONFIG_DIR=$BrocaConfigDir\agents" "BROCA_LOG_DIR=$BrocaLogDir" "SQLITE_DATABASE_PATH=sqlite:///$BrocaDbDir\backend.db" 2>&1 | Out-Null

        # 前端服务 (nginx，与 Linux 部署方式一致)
        if ($HasNode -and $NginxFound) {
            # 先准备 nginx 独立环境（复制 nginx.exe + 生成配置）
            Write-Info "准备 nginx 前端环境..."
            $nginxPrep = & $BrocaPython -c "from broca.service_manager import _win_prepare_nginx; ok, msg, exe = _win_prepare_nginx(); print(msg); import sys; sys.exit(0 if ok else 1)" 2>&1
            if ($LASTEXITCODE -eq 0) {
                $nginxExePath = "$BrocaHome\nginx\nginx.exe"
                Write-Info "nginx 环境就绪: $nginxExePath"

                & nssm.exe stop BrocaFrontend 2>&1 | Out-Null
                & nssm.exe remove BrocaFrontend confirm 2>&1 | Out-Null
                & nssm.exe install BrocaFrontend "$nginxExePath" "-p $BrocaHome\nginx\ -c conf\nginx.conf" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppDirectory "$BrocaHome\nginx" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend DisplayName "Broca Frontend Service (nginx)" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend Description "Broca AI Agent 框架前端服务 (nginx)" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend Start SERVICE_AUTO_START 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStdout "$BrocaLogDir\frontend.out.log" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStderr "$BrocaLogDir\frontend.err.log" 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStopMethodConsole 15000 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStopMethodWindow 15000 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStopMethodThreads 15000 2>&1 | Out-Null
                & nssm.exe set BrocaFrontend AppStopMethodKill 5000 2>&1 | Out-Null
                Write-Info "前端服务 (nginx) 已注册"
            } else {
                Write-Warn "nginx 环境准备失败，前端服务未注册"
                Write-Host $nginxPrep
            }
        } elseif ($HasNode) {
            Write-Warn "未检测到 nginx，前端服务未注册（请先安装 nginx）"
        }

        Write-Info "Windows 服务已注册"
        Write-Host "  服务管理命令:"
        Write-Host "    broca service start   # 启动所有服务"
        Write-Host "    broca service stop    # 停止所有服务"
        Write-Host "    services.msc          # 查看服务列表"
    } else {
        Write-Warn "未检测到 NSSM (Non-Sucking Service Manager)。"
        Write-Warn "服务注册已跳过，broca service start 将使用裸起进程管理。"
        Write-Host ""
        Write-Host "  如需注册 Windows 服务，请安装 NSSM:"
        Write-Host "    winget install NSSM 或 https://nssm.cc/download"
        Write-Host "  之后重新运行此脚本，或手动注册。"
    }
} else {
    Write-Warn "未以管理员身份运行，跳过 Windows 服务注册。"
    Write-Host "  broca service start 将使用裸起进程管理。"

    # 即使非管理员，也提示 NSSM 信息
    $nssmPath = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if (-not $nssmPath) {
        Write-Host "  如需注册 Windows 服务，请以管理员身份运行并安装 NSSM:"
        Write-Host "    winget install NSSM 或 https://nssm.cc/download"
    }
}

# ---- 服务管理（Windows 原生进程管理 + nginx 前端）----
$null = New-Item -ItemType Directory -Force -Path $BrocaRunDir, $BrocaLogDir
Write-Info "Windows 服务管理: 原生进程管理（uvicorn 后端 + nginx 前端）"

Write-Info "  启动: broca service start"
Write-Info "  停止: broca service stop"

# ---- 保存安装信息 ----
$installInfo = @{
    version         = "0.1.0"
    installed_at    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
    python          = (& $Python --version 2>&1).Trim()
    python_path     = $Python
    venv_path       = $BrocaVenv
    project_root    = $ProjectRoot
    has_node        = $HasNode
    frontend_mode   = $(if ($HasNode) { "static" } else { "none" })
    frontend_dist   = $(if ($HasNode) { "$frontendDst\dist" } else { $null })
    storage_configured = (Has-StorageConfig $envFile)
    backend_port    = 9000
    frontend_port   = $(if ($HasNode) { 5166 } else { $null })
}
$installInfo | ConvertTo-Json | Out-File "$BrocaHome\install.json" -Encoding UTF8

# ---- 创建 broca.cmd 快捷命令 ----
$brocaCmd = "$BrocaHome\broca.cmd"
@"
@echo off
REM Broca CLI - 由 install.ps1 自动生成
"%~dp0venv\Scripts\broca.exe" %*
"@ | Out-File $brocaCmd -Encoding ASCII
Write-Info "快捷命令已创建: $brocaCmd"

# 尝试加入 PATH（当前用户）
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BrocaHome*") {
    try {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$BrocaHome", "User")
        Write-Info "已将 $BrocaHome 添加到用户 PATH（下次打开终端生效）"
        Write-Host "  现在也可直接使用完整路径: $brocaCmd"
    } catch {
        Write-Warn "无法自动添加 PATH，请手动添加: $BrocaHome 到用户环境变量 Path"
    }
}

# ============================================================================
# 完成
# ============================================================================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Broca Windows 安装完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  虚拟环境:    $BrocaVenv"
Write-Host "  broca 命令:  $brocaCmd"
Write-Host "  日志目录:    $BrocaLogDir"
Write-Host ""

if ($HasNode) {
    if ($IsAdmin -and (Get-Command nssm.exe -ErrorAction SilentlyContinue)) {
        Write-Host "  服务状态:"
        Write-Host "    nssm start BrocaBackend   # 启动后端"
        Write-Host "    nssm start BrocaFrontend  # 启动前端"
        Write-Host "    nssm stop BrocaBackend    # 停止后端"
        Write-Host "    nssm stop BrocaFrontend   # 停止前端"
        Write-Host "    nssm status BrocaBackend  # 查看后端状态"
    } else {
        Write-Host "  启动方式:"
        Write-Host "    PowerShell -File $startScript   # 启动所有服务"
        Write-Host "    PowerShell -File $stopScript    # 停止所有服务"
    }
    Write-Host ""
    Write-Host "  访问:"
    Write-Host "    前端页面:   http://localhost:5166"
    Write-Host "    后端 API:   http://localhost:9000"
} else {
    Write-Host "  前端:       未构建（未检测到 Node.js）"
    Write-Host "  VS Code 插件: 未打包（需要 Node.js）"
    Write-Host ""
    Write-Host "  后端 API:   http://localhost:9000"
    Write-Host ""
    Write-Host "  如需前端页面或 VS Code 插件，请安装 Node.js 后重新运行此脚本"
}

# ---- 验证安装 ----
Write-Step "验证安装..."
try {
    $verOutput = & $BrocaPython -m broca --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Broca CLI 验证成功: $($verOutput.Trim())"
    } else {
        # broca 可能没有 --version，尝试 import
        $importOutput = & $BrocaPython -c "import broca; print('broca', broca.__version__ if hasattr(broca, '__version__') else '(import ok)')" 2>&1
        Write-Info "Broca 模块验证成功: $($importOutput.Trim())"
    }
} catch {
    Write-Warn "Broca 验证时出现异常: $_"
    Write-Warn "请尝试手动运行: & '$BrocaPython' -m broca --help"
}

Write-Host ""
Write-Host "  如果遇到问题，请查看日志: $BrocaLogDir"
Write-Host ""
pause
Write-Host ""
