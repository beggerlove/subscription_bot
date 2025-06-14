# Telegram 订阅管理机器人

一个用于管理机场订阅的 Telegram 机器人，支持自动检查流量和到期时间。

## 功能特点

- 📝 管理多个订阅
- 🔄 自动检查流量使用情况
- ⏰ 定时自动检查（可配置时间）
- 📊 显示剩余流量和到期时间
- 💬 支持为每个订阅添加备注
- 🔔 异常情况提醒

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/beggerlove/subscription_bot.git
cd subscription-bot
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置机器人：
   - 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
   - 创建新机器人并获取 TOKEN
   - 复制 `config.example.json` 为 `config.json`
   - 修改 `config.json` 中的配置：
     ```json
     {
         "bot_token": "YOUR_BOT_TOKEN",
         "chat_id": "YOUR_CHAT_ID",
         "check_hour": 9
     }
     ```

## 使用方法

启动机器人：
```bash
python subscription_bot.py
```

### 可用命令

- `/start` - 显示欢迎信息
- `/help` - 显示帮助信息
- `/add <名称> <URL> [备注]` - 添加订阅
- `/remove <名称>` - 删除订阅
- `/list` - 列出所有订阅
- `/check` - 检查所有订阅状态
- `/message <名称> <备注>` - 更新订阅备注
- `/setchecktime <小时>` - 设置每日定时检查时间（0-23）

## 配置说明

- `bot_token`: Telegram 机器人 Token
- `chat_id`: 接收消息的聊天 ID
- `check_hour`: 每日自动检查的时间（24小时制）

## 依赖

- python-telegram-bot==22.1
- requests==2.31.0
- pytz==2024.1

## 注意事项

1. 请勿将包含 TOKEN 的配置文件提交到代码仓库
2. 建议将 `config.json` 添加到 `.gitignore` 文件中
3. 确保订阅链接支持 `subscription-userinfo` 头部信息
