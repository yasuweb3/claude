# TG 日程提醒机器人（首版）

这是一个单用户 Telegram 提醒工具，核心能力：

- 支持单次 / 每天 / 每周（含工作日）提醒
- 支持提前提醒（默认 10 分钟）
- 到点后支持按钮操作：`完成` / `稍后 10 分钟` / `稍后 30 分钟` / `稍后 1 小时`
- 到点后 30 分钟未完成，会额外催办一次（只催一次）
- 每天 10:00 自动发送“今日提醒总览”（按时间排序）
- 固定 chat_id，仅允许绑定的主账号操作

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
```

---

## 2. 启动方式

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
- 增加节假日规则、自然语言建提醒、iCal 导入导出
