#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌ 此脚本仅支持 macOS。"
  exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/yasuweb3/claude.git}"
BRANCH="${BRANCH:-cursor/cursor-bdaf}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/apps/tg-reminder}"
# 可选：ENABLE_PROXY=1 PROXY_URL=... ALL_PROXY_URL=... NO_PROXY_LIST=...

command -v git >/dev/null 2>&1 || {
  echo "❌ 缺少 git，请先安装 Xcode Command Line Tools。"
  exit 1
}

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "ℹ️ 检测到已有目录，正在更新代码..."
  git -C "$INSTALL_DIR" fetch origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" pull origin "$BRANCH"
else
  echo "ℹ️ 正在克隆仓库到 $INSTALL_DIR ..."
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
bash "$INSTALL_DIR/scripts/install_mac.sh"
