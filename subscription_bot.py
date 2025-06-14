import logging
import json
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import asyncio
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('subscription_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 配置文件
CONFIG_FILE = "config.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
TIMEZONE = ZoneInfo("Asia/Shanghai")

# ------------------ 配置管理 ------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    raise FileNotFoundError(f"配置文件 {CONFIG_FILE} 不存在，请复制 config.example.json 并修改配置")

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# 加载配置
config = load_config()
BOT_TOKEN = config["bot_token"]
CHAT_ID = config["chat_id"]
CHECK_HOUR = config.get("check_hour", 9)

# ------------------ 订阅管理类 ------------------
class SubscriptionManager:
    def __init__(self):
        self.session = requests.Session()
        self.load_subscriptions()

    def load_subscriptions(self):
        if os.path.exists(SUBSCRIPTIONS_FILE):
            with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                self.subscriptions = json.load(f)
        else:
            self.subscriptions = []
            self.save_subscriptions()

    def save_subscriptions(self):
        with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)

    def add_subscription(self, name: str, url: str, custom_message: str = "") -> bool:
        if any(sub['name'] == name for sub in self.subscriptions):
            return False
        self.subscriptions.append({
            'name': name,
            'url': url,
            'custom_message': custom_message
        })
        self.save_subscriptions()
        return True

    def remove_subscription(self, name: str) -> bool:
        initial_length = len(self.subscriptions)
        self.subscriptions = [sub for sub in self.subscriptions if sub['name'] != name]
        if len(self.subscriptions) < initial_length:
            self.save_subscriptions()
            return True
        return False

    def update_custom_message(self, name: str, custom_message: str) -> bool:
        for sub in self.subscriptions:
            if sub['name'] == name:
                sub['custom_message'] = custom_message
                self.save_subscriptions()
                return True
        return False

    def format_size(self, bytes_size: int) -> str:
        gb = bytes_size / (1024 ** 3)
        return f"{gb:.2f} GB"

    def parse_userinfo(self, userinfo: str) -> dict:
        result = {}
        for item in userinfo.split(';'):
            if '=' in item:
                key, value = item.split('=')
                result[key.strip()] = int(value.strip())
        return result

    def check_subscription(self, name: str, url: str) -> dict:
        try:
            response = self.session.get(url)
            response.raise_for_status()
            userinfo = response.headers.get('subscription-userinfo')
            if not userinfo:
                return {'error': f"未找到 {name} 的 subscription-userinfo 字段"}
            info = self.parse_userinfo(userinfo)
            upload = info.get('upload', 0)
            download = info.get('download', 0)
            total = info.get('total', 0)
            expire = info.get('expire', 0)
            remaining = total - (upload + download)
            used = upload + download
            expire_date = datetime.fromtimestamp(expire).strftime('%Y-%m-%d')
            return {
                'name': name,
                'remaining': self.format_size(remaining),
                'used': self.format_size(used),
                'expire_date': expire_date
            }
        except Exception as e:
            return {'error': f"{name} 检查失败: {str(e)}"}

    def check_all_subscriptions(self) -> list:
        results = []
        for sub in self.subscriptions:
            result = self.check_subscription(sub['name'], sub['url'])
            if 'custom_message' in sub and sub['custom_message']:
                result['custom_message'] = sub['custom_message']
            results.append(result)
        return results

    def format_status_message(self, results: list) -> str:
        if not results:
            return "❌ 没有订阅需要检查"
        message = "📊 订阅状态报告\n\n"
        for result in results:
            if 'error' in result:
                message += f"❌ {result['name']}: {result['error']}\n"
            else:
                message += f"🔹 {result['name']}\n"
                message += f"📥 剩余流量: {result['remaining']}\n"
                message += f"📤 已用流量: {result['used']}\n"
                message += f"📅 到期时间: {result['expire_date']}\n"
                if 'custom_message' in result and result['custom_message']:
                    message += f"💬 备注: {result['custom_message']}\n"
            message += "➖➖➖➖➖➖➖➖➖➖\n"
        return message

# ------------------ 订阅实例 ------------------
subscription_manager = SubscriptionManager()

# ------------------ 机器人命令 ------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 欢迎使用订阅管理机器人！\n\n"
        "命令列表：\n"
        "/add <名称> <URL> [备注]\n"
        "/remove <名称>\n"
        "/list\n"
        "/check\n"
        "/message <名称> <备注>\n"
        "/setchecktime <小时>（设置每日定时检查时间）\n"
        "/help"
    )
    await update.message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ 用法：/add 名称 URL [备注]")
        return
    name = context.args[0]
    url = context.args[1]
    custom_message = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    if subscription_manager.add_subscription(name, url, custom_message):
        await update.message.reply_text(f"✅ 添加订阅成功：{name}")
    else:
        await update.message.reply_text(f"❌ 已存在同名订阅：{name}")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ 用法：/remove 名称")
        return
    name = context.args[0]
    if subscription_manager.remove_subscription(name):
        await update.message.reply_text(f"✅ 删除订阅成功：{name}")
    else:
        await update.message.reply_text(f"❌ 未找到订阅：{name}")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = subscription_manager.subscriptions
    if not subs:
        await update.message.reply_text("📭 当前没有订阅")
        return
    msg = "📝 当前订阅列表：\n\n"
    for sub in subs:
        msg += f"🔹 {sub['name']}\n🔗 {sub['url']}\n"
        if sub.get("custom_message"):
            msg += f"💬 备注: {sub['custom_message']}\n"
        msg += "➖➖➖➖➖➖➖➖➖➖\n"
    await update.message.reply_text(msg)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 正在检查订阅状态...")
    results = subscription_manager.check_all_subscriptions()
    msg = subscription_manager.format_status_message(results)
    await update.message.reply_text(msg)

async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ 用法：/message 名称 备注")
        return
    name = context.args[0]
    custom_message = " ".join(context.args[1:])
    if subscription_manager.update_custom_message(name, custom_message):
        await update.message.reply_text(f"✅ 备注更新成功：{name}")
    else:
        await update.message.reply_text(f"❌ 未找到订阅：{name}")

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    results = subscription_manager.check_all_subscriptions()
    msg = subscription_manager.format_status_message(results)
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)

async def setchecktime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ 用法：/setchecktime <小时>（0-23）")
        return
    hour = int(context.args[0])
    if hour < 0 or hour > 23:
        await update.message.reply_text("❌ 小时必须在 0 到 23 之间")
        return

    config["check_hour"] = hour
    save_config(config)
    await update.message.reply_text(f"✅ 已设置每天 {hour}:00 自动检查订阅")

# ------------------ 主函数 ------------------
def main():
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        application.job_queue.scheduler.configure(timezone=TIMEZONE)

        # 命令处理器
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("add", add_command))
        application.add_handler(CommandHandler("remove", remove_command))
        application.add_handler(CommandHandler("list", list_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("message", message_command))
        application.add_handler(CommandHandler("setchecktime", setchecktime_command))

        # 设置定时任务
        application.job_queue.run_daily(
            scheduled_check,
            time=time(hour=config.get("check_hour", 9), tzinfo=TIMEZONE),
            name="daily_check"
        )

        logging.info("机器人已启动")
        application.run_polling()

    except Exception as e:
        logging.error(f"启动机器人时出错: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("程序已停止")
    except Exception as e:
        logging.error(f"运行时发生错误: {str(e)}")
