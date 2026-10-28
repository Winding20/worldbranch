#!/usr/bin/env bash
# WorldBranch 部署脚本（在本地执行，推到服务器）
#
#   ./deploy/deploy.sh user@host [/www/wwwroot/worldbranch]
#
# 做的事：
#   1. 本地跑一遍 CI（--skip-frontend 之外的检查），不过就不部署
#   2. 构建前端产物
#   3. rsync 后端源码、前端产物、工具与部署文件
#   4. 远端：建/更新 venv、装依赖、建表、播种（均幂等）
#   5. 远端：安装并重启 systemd 服务
#   6. 本机 curl 健康检查
#
# 前提（一次性，见 docs/部署说明.md）：
#   - 服务器已装 python3、nginx、systemd，已建好数据库
#   - 已在服务器上放好 backend/.env（含数据库连接串）
#   - 已把 deploy/worldbranch.service 装到 /etc/systemd/system/ 并 enable
#
# 注意：本脚本在本机无法实测（这台机器连不上服务器 22 端口），
# 首次使用请逐行看一遍输出，按需调整路径与用户名。

set -euo pipefail

REMOTE="${1:?用法: deploy.sh user@host [远端目录]}"
REMOTE_DIR="${2:-/www/wwwroot/worldbranch}"
LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 本地 CI"
cd "$LOCAL_ROOT"
python tools/ci.py

echo "==> 前端构建"
cd "$LOCAL_ROOT/frontend"
node build.mjs

echo "==> 同步文件到 $REMOTE:$REMOTE_DIR"
rsync -az --delete \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'instance' \
  --exclude '.env' \
  "$LOCAL_ROOT/backend/" "$REMOTE:$REMOTE_DIR/backend/"

rsync -az --delete "$LOCAL_ROOT/frontend/dist/" "$REMOTE:$REMOTE_DIR/frontend/dist/"
rsync -az "$LOCAL_ROOT/tools/" "$REMOTE:$REMOTE_DIR/tools/"

echo "==> 远端：依赖与数据"
ssh "$REMOTE" bash -s <<EOF
set -euo pipefail
cd $REMOTE_DIR
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
$REMOTE_DIR/.venv/bin/pip install --quiet --upgrade pip
$REMOTE_DIR/.venv/bin/pip install --quiet -r backend/requirements.txt waitress

cd $REMOTE_DIR/backend
export FLASK_APP=run.py
$REMOTE_DIR/.venv/bin/python -m flask init-db
$REMOTE_DIR/.venv/bin/python -m flask seed
EOF

echo "==> 远端：重启服务"
ssh "$REMOTE" "sudo systemctl restart worldbranch && sleep 2 && systemctl is-active worldbranch"

echo "==> 健康检查"
curl -fsS -m 10 "http://$REMOTE/api/health" || {
  echo "健康检查失败：请查看 journalctl -u worldbranch -n 50" >&2
  exit 1
}
echo
echo "✓ 部署完成"