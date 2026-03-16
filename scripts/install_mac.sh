#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌ 此脚本仅支持 macOS。"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
EXAMPLE_ENV_FILE="$PROJECT_DIR/.env.example"
LOG_DIR="$PROJECT_DIR/logs"
SERVICE_LABEL="com.tgreminder.bot"
PLIST_PATH="$HOME/Library/LaunchAgents/${SERVICE_LABEL}.plist"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

if [[ ! -f "$PROJECT_DIR/main.py" ]]; then
  echo "❌ 未检测到项目根目录（缺少 main.py）。"
  echo "   请在仓库目录中运行：bash scripts/install_mac.sh"
  exit 1
fi

command -v python3 >/dev/null 2>&1 || {
  echo "❌ 缺少 python3，请先安装 Python 3.11+。"
  exit 1
}

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ ! -f "$EXAMPLE_ENV_FILE" ]]; then
    echo "❌ 缺少 .env.example，无法初始化配置。"
    exit 1
  fi
  cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
  echo "✅ 已创建 .env"
fi

get_env_value() {
  python3 - "$ENV_FILE" "$1" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
if not env_path.exists():
    print("")
    raise SystemExit(0)
for line in env_path.read_text(encoding="utf-8").splitlines():
    if "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() == key:
        print(v.strip())
        break
else:
    print("")
PY
}

upsert_env() {
  python3 - "$ENV_FILE" "$@" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
pairs = sys.argv[2:]
values = {}
for pair in pairs:
    key, value = pair.split("=", 1)
    values[key] = value

lines = []
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()

seen = set()
result = []
for line in lines:
    if "=" not in line:
        result.append(line)
        continue
    key, _ = line.split("=", 1)
    key = key.strip()
    if key in values:
        result.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        result.append(line)

for key, value in values.items():
    if key not in seen:
        result.append(f"{key}={value}")

env_path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
PY
}

current_bot_token="$(get_env_value TG_BOT_TOKEN)"
current_chat_id="$(get_env_value TG_CHAT_ID)"
current_deepseek_key="$(get_env_value DEEPSEEK_API_KEY)"
current_timezone="$(get_env_value TIMEZONE)"
current_summary_time="$(get_env_value DAILY_SUMMARY_TIME)"
current_poll_interval="$(get_env_value POLL_INTERVAL_SECONDS)"

echo ""
echo "=== TG 提醒机器人一键安装（Mac）==="
echo "项目目录：$PROJECT_DIR"
echo ""

if [[ -n "$current_bot_token" && "$current_bot_token" != "your_telegram_bot_token" ]]; then
  read -r -p "TG_BOT_TOKEN（回车沿用当前值）: " input_bot_token
  TG_BOT_TOKEN="${input_bot_token:-$current_bot_token}"
else
  read -r -p "TG_BOT_TOKEN（必填）: " TG_BOT_TOKEN
fi

while [[ -z "${TG_BOT_TOKEN:-}" || "$TG_BOT_TOKEN" == "your_telegram_bot_token" ]]; do
  read -r -p "TG_BOT_TOKEN 不能为空，请重新输入: " TG_BOT_TOKEN
done

if [[ -n "$current_chat_id" && "$current_chat_id" != "123456789" ]]; then
  read -r -p "TG_CHAT_ID（回车沿用当前值）: " input_chat_id
  TG_CHAT_ID="${input_chat_id:-$current_chat_id}"
else
  read -r -p "TG_CHAT_ID（必填）: " TG_CHAT_ID
fi

while [[ -z "${TG_CHAT_ID:-}" || "$TG_CHAT_ID" == "123456789" ]]; do
  read -r -p "TG_CHAT_ID 不能为空，请重新输入: " TG_CHAT_ID
done

enable_deepseek_default="Y"
if [[ -z "$current_deepseek_key" ]]; then
  enable_deepseek_default="y"
fi
read -r -p "启用 DeepSeek 自然语言提醒？[Y/n] (默认 ${enable_deepseek_default}): " enable_deepseek
enable_deepseek="${enable_deepseek:-$enable_deepseek_default}"

DEEPSEEK_API_KEY="$current_deepseek_key"
if [[ "$enable_deepseek" =~ ^[Yy]$ ]]; then
  if [[ -n "$current_deepseek_key" ]]; then
    read -r -s -p "DEEPSEEK_API_KEY（回车沿用当前值）: " input_deepseek_key
    echo ""
    DEEPSEEK_API_KEY="${input_deepseek_key:-$current_deepseek_key}"
  else
    read -r -s -p "DEEPSEEK_API_KEY（必填）: " DEEPSEEK_API_KEY
    echo ""
  fi
fi

if [[ -z "$current_timezone" ]]; then
  current_timezone="Asia/Shanghai"
fi
if [[ -z "$current_summary_time" ]]; then
  current_summary_time="10:00"
fi
if [[ -z "$current_poll_interval" ]]; then
  current_poll_interval="15"
fi

read -r -p "TIMEZONE（默认 ${current_timezone}）: " input_timezone
TIMEZONE="${input_timezone:-$current_timezone}"

read -r -p "DAILY_SUMMARY_TIME（默认 ${current_summary_time}）: " input_summary_time
DAILY_SUMMARY_TIME="${input_summary_time:-$current_summary_time}"

read -r -p "POLL_INTERVAL_SECONDS（默认 ${current_poll_interval}）: " input_poll_interval
POLL_INTERVAL_SECONDS="${input_poll_interval:-$current_poll_interval}"

DATABASE_URL="sqlite+pysqlite:////Users/$(id -un)/apps/tg-reminder/reminder.db"
if [[ "$PROJECT_DIR" != "/Users/$(id -un)/apps/tg-reminder" ]]; then
  DATABASE_URL="sqlite+pysqlite:////${PROJECT_DIR#/}/reminder.db"
fi

if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi

"$PYTHON_BIN" -m pip install -U pip
"$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements.txt"

upsert_env \
  "TG_BOT_TOKEN=$TG_BOT_TOKEN" \
  "TG_CHAT_ID=$TG_CHAT_ID" \
  "DATABASE_URL=$DATABASE_URL" \
  "TIMEZONE=$TIMEZONE" \
  "DAILY_SUMMARY_TIME=$DAILY_SUMMARY_TIME" \
  "POLL_INTERVAL_SECONDS=$POLL_INTERVAL_SECONDS" \
  "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1" \
  "DEEPSEEK_MODEL=deepseek-chat" \
  "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY"

cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${SERVICE_LABEL}</string>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${PYTHON_BIN}</string>
      <string>${PROJECT_DIR}/main.py</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/err.log</string>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/${SERVICE_LABEL}"

echo ""
echo "✅ 安装完成，机器人已启动（并已设置开机自启）"
echo "服务名: ${SERVICE_LABEL}"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep ${SERVICE_LABEL}"
echo "  实时日志: tail -f ${LOG_DIR}/out.log"
echo "  错误日志: tail -f ${LOG_DIR}/err.log"
echo "  重启服务: launchctl kickstart -k gui/$(id -u)/${SERVICE_LABEL}"
