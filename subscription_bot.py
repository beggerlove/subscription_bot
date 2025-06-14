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
async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 60):
    """延迟删除消息"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.error(f"删除消息失败: {str(e)}")

async def send_message(context: ContextTypes.DEFAULT_TYPE, text: str, chat_id: int = None):
    """发送消息并在60秒后删除"""
    if chat_id is None:
        chat_id = CHAT_ID
    try:
        message = await context.bot.send_message(
            chat_id=chat_id, 
            text=text,
            parse_mode='HTML'  # 使用 HTML 格式
        )
        # 启动异步任务删除消息
        asyncio.create_task(delete_message_after_delay(context, chat_id, message.message_id))
    except Exception as e:
        logging.error(f"发送消息失败: {str(e)}")

def escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    welcome_text = (
        "欢迎使用订阅管理机器人！\n\n"
        "可用命令：\n"
        "/add <名称> <URL> [备注] - 添加订阅\n"
        "/remove <名称> - 删除订阅\n"
        "/list - 列出所有订阅\n"
        "/check - 检查所有订阅状态\n"
        "/message <名称> <备注> - 更新订阅备注\n"
        "/setchecktime <小时> - 设置每日定时检查时间（0-23）"
    )
    await send_message(context, welcome_text, update.effective_chat.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    help_text = (
        "订阅管理机器人使用帮助：\n\n"
        "1. 添加订阅：\n"
        "   /add 名称 URL [备注]\n"
        "   例如：/add 机场1 https://example.com/sub\n\n"
        "2. 删除订阅：\n"
        "   /remove 名称\n"
        "   例如：/remove 机场1\n\n"
        "3. 查看所有订阅：\n"
        "   /list\n\n"
        "4. 检查订阅状态：\n"
        "   /check\n\n"
        "5. 更新订阅备注：\n"
        "   /message 名称 新备注\n"
        "   例如：/message 机场1 这是新备注\n\n"
        "6. 设置检查时间：\n"
        "   /setchecktime 小时\n"
        "   例如：/setchecktime 9"
    )
    await send_message(context, help_text, update.effective_chat.id)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /add 命令"""
    if len(context.args) < 2:
        await send_message(context, "请提供订阅名称和URL，格式：/add <名称> <URL> [备注]", update.effective_chat.id)
        return

    name = context.args[0]
    url = context.args[1]
    message = " ".join(context.args[2:]) if len(context.args) > 2 else ""

    if subscription_manager.add_subscription(name, url, message):
        await send_message(context, f"订阅 {name} 添加成功！", update.effective_chat.id)
    else:
        await send_message(context, f"订阅 {name} 已存在！", update.effective_chat.id)

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /remove 命令"""
    if not context.args:
        await send_message(context, "请提供要删除的订阅名称，格式：/remove <名称>", update.effective_chat.id)
        return

    name = context.args[0]
    if subscription_manager.remove_subscription(name):
        await send_message(context, f"订阅 {name} 已删除！", update.effective_chat.id)
    else:
        await send_message(context, f"订阅 {name} 不存在！", update.effective_chat.id)

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /list 命令"""
    subscriptions = subscription_manager.subscriptions
    if not subscriptions:
        await send_message(context, "当前没有订阅！", update.effective_chat.id)
        return

    text = "当前订阅列表：\n\n"
    for sub in subscriptions:
        text += f"名称：{escape_html(sub['name'])}\n"
        # 使用 HTML 剧透标签
        text += f"URL：<tg-spoiler>{escape_html(sub['url'])}</tg-spoiler>\n"
        if sub.get("custom_message"):
            text += f"备注：{escape_html(sub['custom_message'])}\n"
        text += "-------------------\n"
    
    await send_message(context, text, update.effective_chat.id)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /check 命令"""
    # 发送初始消息并保存消息ID
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="开始检查所有订阅..."
    )
    message_id = message.message_id

    # 检查所有订阅
    results = subscription_manager.check_all_subscriptions()
    msg = subscription_manager.format_status_message(results)

    # 更新消息内容
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=message_id,
        text=msg
    )

    # 60秒后删除消息
    asyncio.create_task(delete_message_after_delay(context, update.effective_chat.id, message_id))

async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /message 命令"""
    if len(context.args) < 2:
        await send_message(context, "请提供订阅名称和新备注，格式：/message <名称> <备注>", update.effective_chat.id)
        return

    name = context.args[0]
    message = " ".join(context.args[1:])
    
    if subscription_manager.update_custom_message(name, message):
        await send_message(context, f"订阅 {name} 的备注已更新！", update.effective_chat.id)
    else:
        await send_message(context, f"订阅 {name} 不存在！", update.effective_chat.id)

async def set_check_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /setchecktime 命令"""
    if not context.args:
        await send_message(context, "请提供检查时间（0-23），格式：/setchecktime <小时>", update.effective_chat.id)
        return

    try:
        hour = int(context.args[0])
        if 0 <= hour <= 23:
            config["check_hour"] = hour
            save_config(config)
            await send_message(context, f"检查时间已设置为 {hour}:00", update.effective_chat.id)
        else:
            await send_message(context, "时间必须在 0-23 之间！", update.effective_chat.id)
    except ValueError:
        await send_message(context, "请输入有效的时间！", update.effective_chat.id)

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
        application.add_handler(CommandHandler("setchecktime", set_check_time_command))

        # 设置定时任务
        application.job_queue.run_daily(
            check_command,
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