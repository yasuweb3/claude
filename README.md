# TG 日程提醒机器人（首版）

这是一个单用户 Telegram 提醒工具，核心能力：

- 支持单次 / 每天 / 每周（含工作日）提醒
- 支持提前提醒（默认 10 分钟）
- 新建后支持按钮快速切换提前提醒（无提前 / 10 分钟 / 30 分钟）
- 到点后支持按钮操作：`完成` / `稍后 10 分钟` / `稍后 30 分钟` / `稍后 1 小时`
- 到点后 30 分钟未完成，会额外催办一次（只催一次）
- 每天 10:00 自动发送“今日提醒总览”（按时间排序）
- 固定 chat_id，仅允许绑定的主账号操作
- 支持自然语言建提醒（接入 DeepSeek，先确认后创建）

> 当前版本先做 Telegram 端。网页端后续可在同一数据库上直接扩展，实现同步管理。

---

## 1. 环境准备

1) 复制环境变量文件：

```bash
cp .env.example .env
```

2) 编辑 `.env`：

```env
TG_BOT_TOKEN=你的机器人token
TG_CHAT_ID=你的主账号chat_id
DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/reminder_bot
TIMEZONE=Asia/Shanghai
DAILY_SUMMARY_TIME=10:00
POLL_INTERVAL_SECONDS=15
DEEPSEEK_API_KEY=你的deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

---

## 2. 启动方式

### 方式 0：Mac mini 一键安装 + 开机自启（推荐）

如果你在 Mac mini 上部署，直接执行一条命令：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/yasuweb3/claude/cursor/cursor-bdaf/scripts/bootstrap_mac.sh)"
```

脚本会自动完成：
- 拉取/更新代码到 `~/apps/tg-reminder`
- 安装 Python 依赖
- 引导填写 `TG_BOT_TOKEN / TG_CHAT_ID / DeepSeek Key`
- 生成 launchd 配置并启动服务
- 设置开机自启

### 方式 A：Docker Compose（推荐）

```bash
docker compose up -d --build
docker compose logs -f bot
```

### 方式 B：本地 Python 运行

先确保你有可用的 PostgreSQL，然后：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## 3. TG 命令

### 新增提醒

```text
/add_daily HH:MM 标题 [--pre 10]
/add_weekly 工作日 HH:MM 标题 [--pre 10]
/add_weekly Mon,Wed,Fri HH:MM 标题 [--pre 10]
/add_once YYYY-MM-DD HH:MM 标题 [--pre 10]
```

示例：

```text
/add_weekly 工作日 18:00 打扫卫生
/add_daily 10:30 喝水
/add_once 2026-03-18 09:00 提交报告
```

### 自然语言新增（DeepSeek）

直接给机器人发一句话，例如：

```text
每个工作日下午6点提醒我打扫卫生
明天早上9点提醒我提交日报，提前20分钟
每天晚上11点提醒我关灯
每天早上10点提醒喝水，中午1点再提醒喝水
```

机器人会返回 AI 解析结果，你点击“确认创建”后才会真正写入提醒。  
如果一句话里有多个提醒，会一次性批量创建。

### 管理提醒

```text
/list
/delete ID
/pause ID
/resume ID
/edit_time ID HH:MM
/edit_time ID YYYY-MM-DD HH:MM      (单次提醒)
/edit_rule ID daily|workday|Mon,Wed,Fri
/edit_rule ID once YYYY-MM-DD HH:MM
/edit_pre ID 分钟
```

`/list` 现已支持交互式视图：
- 今天（默认）
- 仅待触发
- 暂停
- 全部

并支持分页按钮，不会频繁刷屏。

---

## 4. 交互逻辑（已按需求实现）

- 点击 `完成`：只完成当前这一次触发，不影响下一次周期提醒
- 点击 `稍后`：按选择的分钟数再次提醒
- 到点后未完成：30 分钟后自动催一次（仅一次）
- 每天 10:00：发送今天全部提醒，展示状态（待提醒 / 已完成 / 已过未完成 / 已暂停）

---

## 5. 后续扩展建议

- 增加 Web 管理页（增删改查提醒），与 TG 共用 PostgreSQL 实现实时同步
- 增加登录态（例如 magic link）
- 增加节假日规则、iCal 导入导出
