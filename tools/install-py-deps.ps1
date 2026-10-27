# 安装 Python 依赖（带沙箱兼容与国内镜像）
# 用法:  . B:\新项目开发\tools\install-py-deps.ps1 -Packages flask,sqlalchemy

param(
    [string[]]$Packages = @("flask", "flask-cors", "sqlalchemy", "pymysql", "pytest", "python-dotenv")
)

$ErrorActionPreference = "Stop"
$Workspace = "B:\新项目开发"
$VenvPython = Join-Path $Workspace ".venv\Scripts\python.exe"
$Shim = Join-Path $Workspace "tools\pyshim"
$TmpDir = Join-Path $Workspace ".tmp"

if (-not (Test-Path $VenvPython)) { throw "虚拟环境不存在: $VenvPython" }
if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null }

$env:PYTHONPATH = $Shim
$env:TMP = $TmpDir
$env:TEMP = $TmpDir
$env:TMPDIR = $TmpDir
$env:PYTHONUTF8 = "1"

& $VenvPython -m pip install @Packages `
    -i "https://pypi.tuna.tsinghua.edu.cn/simple" `
    --disable-pip-version-check

exit $LASTEXITCODE