# WorldBranch 开发环境引导脚本
# 用法:  . B:\新项目开发\tools\dev-env.ps1

$ErrorActionPreference = "Stop"

$Workspace = "B:\新项目开发"
$Venv = Join-Path $Workspace ".venv"
$Shim = Join-Path $Workspace "tools\pyshim"
$TmpDir = Join-Path $Workspace ".tmp"

# 1) 沙箱兼容 shim：让 pip / pytest / vevn 的临时目录可写
$env:PYTHONPATH = $Shim

# 2) 临时目录指向工作区（默认 TEMP 在沙箱下不可靠）
if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null }
$env:TMP = $TmpDir
$env:TEMP = $TmpDir
$env:TMPDIR = $TmpDir

# 3) pip 镜像与时区
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 4) 虚拟环境加入 PATH
$venvScripts = Join-Path $Venv "Scripts"
if (Test-Path $venvScripts) {
    $env:Path = "$venvScripts;$env:Path"
}

Write-Host "WorldBranch 开发环境已就绪" -ForegroundColor Green
Write-Host "  工作区   : $Workspace"
Write-Host "  虚拟环境 : $Venv"
Write-Host "  PYTHONPATH(shim) : $Shim"
Write-Host "  TEMP     : $TmpDir"
Write-Host "  pip 镜像 : $env:PIP_INDEX_URL"
if (Test-Path (Join-Path $venvScripts "python.exe")) {
    $v = & (Join-Path $venvScripts "python.exe") -c "import sys;print(sys.version.split()[0])"
    Write-Host "  python   : $v"
}