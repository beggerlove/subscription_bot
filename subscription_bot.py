import logging
import json
import os
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import asyncio
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
import base64
import re
import time
import subprocess
import sys
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, parse_qs

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
CHAT_IDS = config.get("chat_ids", [])  # 改为列表存储多个群组ID
CHECK_HOUR = config.get("check_hour", 9)
ADMIN_ID = config.get("admin_id")

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
            # 首先尝试使用parse_subscription_info方法
            result = self.parse_subscription_info(url)
            if 'error' not in result:
                result['name'] = name
                return result

            # 如果parse_subscription_info失败，尝试从响应头获取信息
            response = self.session.get(url)
            response.raise_for_status()
            userinfo = response.headers.get('subscription-userinfo')
            if not userinfo:
                return {'name': name, 'error': "无法获取订阅信息"}
            
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
            return {'name': name, 'error': f"检查失败: {str(e)}"}

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

    def parse_subscription_info(self, url: str) -> dict:
        try:
            response = self.session.get(url)
            response.raise_for_status()
            
            # 首先尝试从响应头获取信息
            userinfo = response.headers.get('subscription-userinfo')
            if userinfo:
                print(f"找到 subscription-userinfo: {userinfo}")
                info = self.parse_userinfo(userinfo)
                upload = info.get('upload', 0)
                download = info.get('download', 0)
                total = info.get('total', 0)
                expire = info.get('expire', 0)
                remaining = total - (upload + download)
                used = upload + download
                expire_date = datetime.fromtimestamp(expire).strftime('%Y-%m-%d')
                return {
                    'name': "temp",
                    'remaining': self.format_size(remaining),
                    'used': self.format_size(used),
                    'expire_date': expire_date
                }
            
            # 如果没有 subscription-userinfo 头，尝试从响应内容解析
            content = response.text
            print(f"原始内容: {content[:200]}")  # 打印前200个字符
            
            try:
                # 尝试 base64 解码
                content = base64.b64decode(content).decode('utf-8')
                print(f"Base64解码后: {content[:200]}")  # 打印前200个字符
            except Exception as e:
                print(f"Base64解码失败: {str(e)}")

            # 解析流量信息
            info = {
                "upload": 0,
                "download": 0,
                "total": 0,
                "expire": 0
            }

            # 从内容中提取信息
            lines = content.split('\n')
            print(f"总行数: {len(lines)}")
            
            # 检查是否是 SS 链接
            if any(line.startswith('ss://') for line in lines):
                print("检测到 SS 链接")
                # 获取第一个有效的 SS 链接
                ss_link = next((line for line in lines if line.startswith('ss://')), None)
                if ss_link:
                    try:
                        # 解析 SS 链接
                        ss_parts = ss_link.split('@')
                        if len(ss_parts) == 2:
                            # 获取服务器地址和端口
                            server = ss_parts[1].split('#')[0]
                            print(f"服务器信息: {server}")
                            
                            # 尝试从服务器获取流量信息
                            try:
                                # 尝试不同的 API 路径
                                api_paths = [
                                    '/user/info',
                                    '/api/user/info',
                                    '/api/v1/user/info',
                                    '/api/v1/user/traffic',
                                    '/api/user/traffic'
                                ]
                                
                                for path in api_paths:
                                    try:
                                        server_url = f"http://{server}{path}"
                                        print(f"尝试获取服务器信息: {server_url}")
                                        server_response = self.session.get(server_url, timeout=5)
                                        if server_response.status_code == 200:
                                            server_info = server_response.json()
                                            if isinstance(server_info, dict):
                                                # 尝试不同的字段名
                                                info["upload"] = server_info.get('u', server_info.get('upload', 0))
                                                info["download"] = server_info.get('d', server_info.get('download', 0))
                                                info["total"] = server_info.get('transfer_enable', server_info.get('total', 0))
                                                info["expire"] = server_info.get('expire', 0)
                                                print(f"从服务器获取到信息: {server_info}")
                                                break
                                    except Exception as e:
                                        print(f"尝试 {path} 失败: {str(e)}")
                                        continue
                                
                                # 如果所有 API 都失败，尝试从 URL 参数获取
                                if all(v == 0 for v in info.values()):
                                    try:
                                        from urllib.parse import urlparse, parse_qs
                                        parsed_url = urlparse(url)
                                        params = parse_qs(parsed_url.query)
                                        print(f"URL参数: {params}")
                                        
                                        if "upload" in params:
                                            info["upload"] = int(params["upload"][0])
                                        if "download" in params:
                                            info["download"] = int(params["download"][0])
                                        if "total" in params:
                                            info["total"] = int(params["total"][0])
                                        if "expire" in params:
                                            info["expire"] = int(params["expire"][0])
                                    except Exception as e:
                                        print(f"解析 URL 参数失败: {str(e)}")
                            except Exception as e:
                                print(f"获取服务器信息失败: {str(e)}")
                    except Exception as e:
                        print(f"解析 SS 链接失败: {str(e)}")

            # 从内容中提取信息
            for line in lines:
                line = line.lower()
                print(f"处理行: {line[:100]}")  # 打印前100个字符
                
                if "upload=" in line:
                    info["upload"] = int(line.split("=")[1].strip())
                    print(f"找到上传: {info['upload']}")
                elif "download=" in line:
                    info["download"] = int(line.split("=")[1].strip())
                    print(f"找到下载: {info['download']}")
                elif "total=" in line:
                    info["total"] = int(line.split("=")[1].strip())
                    print(f"找到总量: {info['total']}")
                elif "expire=" in line:
                    info["expire"] = int(line.split("=")[1].strip())
                    print(f"找到到期: {info['expire']}")
                # 处理其他常见格式
                elif "upload:" in line:
                    info["upload"] = int(line.split(":")[1].strip())
                    print(f"找到上传: {info['upload']}")
                elif "download:" in line:
                    info["download"] = int(line.split(":")[1].strip())
                    print(f"找到下载: {info['download']}")
                elif "total:" in line:
                    info["total"] = int(line.split(":")[1].strip())
                    print(f"找到总量: {info['total']}")
                elif "expire:" in line:
                    info["expire"] = int(line.split(":")[1].strip())
                    print(f"找到到期: {info['expire']}")
                # 处理特殊格式
                elif "剩余流量" in line:
                    remaining = line.split("剩余流量")[1].strip()
                    print(f"找到剩余: {remaining}")
                elif "总流量" in line:
                    info["total"] = int(line.split("总流量")[1].strip())
                    print(f"找到总量: {info['total']}")
                elif "已用流量" in line:
                    used = line.split("已用流量")[1].strip()
                    print(f"找到已用: {used}")

            # 计算流量
            used = info["upload"] + info["download"]
            remaining = info["total"] - used
            expire_date = datetime.fromtimestamp(info["expire"]).strftime('%Y-%m-%d') if info["expire"] > 0 else "未知"
            
            print(f"计算结果: 上传={info['upload']}, 下载={info['download']}, 总量={info['total']}, 剩余={remaining}, 到期={expire_date}")

            return {
                'name': "temp",
                'remaining': self.format_size(remaining),
                'used': self.format_size(used),
                'expire_date': expire_date
            }
        except Exception as e:
            print(f"解析过程出错: {str(e)}")
            return {'error': f"解析失败: {str(e)}"}

    def check_all_subscriptions(self) -> list:
        results = []
        for sub in self.subscriptions:
            result = self.check_subscription(sub['name'], sub['url'])
            if 'custom_message' in sub and sub['custom_message']:
                result['custom_message'] = sub['custom_message']
            results.append(result)
        return results

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
        # 如果未指定chat_id，则发送到所有群组
        if CHAT_IDS:  # 只有在配置了chat_ids时才发送到所有群组
            for cid in CHAT_IDS:
                try:
                    message = await context.bot.send_message(
                        chat_id=cid, 
                        text=text,
                        parse_mode='HTML'
                    )
                    # 启动异步任务删除消息
                    asyncio.create_task(delete_message_after_delay(context, cid, message.message_id))
                except Exception as e:
                    logging.error(f"发送消息到群组 {cid} 失败: {str(e)}")
        else:
            # 如果没有配置chat_ids，则发送到当前聊天
            try:
                message = await context.bot.send_message(
                    chat_id=context.effective_chat.id, 
                    text=text,
                    parse_mode='HTML'
                )
                # 启动异步任务删除消息
                asyncio.create_task(delete_message_after_delay(context, context.effective_chat.id, message.message_id))
            except Exception as e:
                logging.error(f"发送消息失败: {str(e)}")
    else:
        try:
            message = await context.bot.send_message(
                chat_id=chat_id, 
                text=text,
                parse_mode='HTML'
            )
            # 启动异步任务删除消息
            asyncio.create_task(delete_message_after_delay(context, chat_id, message.message_id))
        except Exception as e:
            logging.error(f"发送消息失败: {str(e)}")

def escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

async def check_admin(update: Update) -> bool:
    """检查用户是否是管理员"""
    if not ADMIN_ID:
        return False
    return str(update.effective_user.id) == str(ADMIN_ID)

async def check_group_permission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """检查群组是否有权限使用机器人"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        return True  # 私聊始终允许
    
    chat_id = str(update.effective_chat.id)
    if not CHAT_IDS:  # 如果没有配置任何群组，则不允许在任何群组中使用
        return False
    return chat_id in CHAT_IDS

async def group_permission_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理需要群组权限的命令"""
    if not await check_group_permission(update, context):
        await send_message(context, "此群组未授权使用机器人，请联系管理员添加群组。", update.effective_chat.id)
        return False
    return True

async def admin_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理需要管理员权限的命令"""
    if not await check_admin(update):
        await send_message(context, "此命令仅限管理员使用", update.effective_chat.id)
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

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
    # 先检查管理员权限
    is_admin = await check_admin(update)
    
    # 如果在群组中，检查群组权限
    if update.effective_chat.type in ['group', 'supergroup']:
        if not await check_group_permission(update, context):
            if not is_admin:  # 如果不是管理员，显示未授权消息
                await send_message(context, "此群组未授权使用机器人，请联系管理员添加群组。", update.effective_chat.id)
                return
            # 如果是管理员，继续执行
    
    # 根据用户权限显示不同的帮助信息
    if is_admin:
        help_text = (
            "订阅管理机器人使用帮助：\n\n"
            "管理员命令：\n"
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
            "   例如：/setchecktime 9\n\n"
            "7. 添加群组：\n"
            "   /addgroup\n"
            "   在群组中使用此命令将当前群组添加到机器人\n\n"
            "8. 移除群组：\n"
            "   /removegroup\n"
            "   在群组中使用此命令将当前群组从机器人中移除\n\n"
            "9. 查看群组列表：\n"
            "   /listgroups\n"
            "   显示所有已添加的群组\n\n"
            "所有用户可用命令：\n"
            "1. 检查订阅链接：\n"
            "   /sub &lt;链接&gt;\n"
            "   或回复包含链接的消息，发送 /sub\n"
            "   例如：/sub https://example.com/sub\n\n"
            "注意：\n"
            "- 管理员命令仅限管理员使用\n"
            "- 群组管理命令只能在群组中使用\n"
            "- 所有消息将在60秒后自动删除"
        )
    else:
        help_text = (
            "订阅管理机器人使用帮助：\n\n"
            "可用命令：\n"
            "1. 检查订阅链接：\n"
            "   /sub &lt;链接&gt;\n"
            "   或回复包含链接的消息，发送 /sub\n"
            "   例如：/sub https://example.com/sub\n\n"
            "注意：\n"
            "- 所有消息将在60秒后自动删除"
        )
    
    await send_message(context, help_text, update.effective_chat.id)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /add 命令"""
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

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
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

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
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

    subscriptions = subscription_manager.subscriptions
    if not subscriptions:
        await send_message(context, "当前没有订阅！", update.effective_chat.id)
        return

    text = "当前订阅列表：\n\n"
    for sub in subscriptions:
        text += f"名称：{escape_html(sub['name'])}\n"
        text += f"URL：<tg-spoiler>{escape_html(sub['url'])}</tg-spoiler>\n"
        if sub.get("custom_message"):
            text += f"备注：{escape_html(sub['custom_message'])}\n"
        text += "-------------------\n"
    
    # 如果在群组中使用，发送到私聊
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            # 先发送提示消息到群组
            await send_message(context, "已将订阅列表发送到私聊，请查看与机器人的私聊消息。", update.effective_chat.id)
            # 然后发送完整列表到私聊
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=text,
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"发送私聊消息失败: {str(e)}")
            await send_message(context, "无法发送私聊消息，请先与机器人开始私聊。", update.effective_chat.id)
    else:
        # 在私聊中直接发送
        await send_message(context, text, update.effective_chat.id)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /check 命令"""
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

    # 发送初始消息并保存消息ID
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="开始检查所有订阅..."
    )
    message_id = message.message_id

    final_output = ''
    headers = {
        'User-Agent': 'ClashforWindows/0.18.1'
    }

    for sub in subscription_manager.subscriptions:
        url = sub['url']
        try:
            res = requests.get(url, headers=headers, timeout=5)
            while res.status_code in [301, 302]:
                url = res.headers['location']
                res = requests.get(url, headers=headers, timeout=5)
        except:
            final_output += f'订阅：{escape_markdown(sub["name"])}\n连接错误\n\n'
            continue

        if res.status_code == 200:
            try:
                info = res.headers['subscription-userinfo']
                info_num = re.findall(r'\d+', info)
                time_now = int(time.time())
                
                # 转义所有特殊字符
                safe_url = escape_markdown(url)
                airport_name = escape_markdown(sub["name"])
                upload = escape_markdown(StrOfSize(int(info_num[0])))
                download = escape_markdown(StrOfSize(int(info_num[1])))
                remaining = escape_markdown(StrOfSize(int(info_num[2]) - int(info_num[1]) - int(info_num[0])))
                total = escape_markdown(StrOfSize(int(info_num[2])))
                
                output_text_head = (
                    f'订阅：{airport_name}\n'
                    f'已用上行：{upload}\n'
                    f'已用下行：{download}\n'
                    f'剩余：{remaining}\n'
                    f'总共：{total}'
                )
                
                if len(info_num) >= 4:
                    timeArray = time.localtime(int(info_num[3]) + 28800)
                    dateTime = time.strftime("%Y-%m-%d", timeArray)
                    if time_now <= int(info_num[3]):
                        lasttime = int(info_num[3]) - time_now
                        output_text = f"{output_text_head}\n此订阅将于 {escape_markdown(dateTime)} 过期，剩余 {escape_markdown(sec_to_data(lasttime))}"
                    else:
                        output_text = f"{output_text_head}\n此订阅已于 {escape_markdown(dateTime)} 过期！"
                else:
                    output_text = f"{output_text_head}\n到期时间：未知"

                if sub.get('custom_message'):
                    output_text += f"\n备注：{escape_markdown(sub['custom_message'])}"
            except:
                safe_url = escape_markdown(url)
                airport_name = escape_markdown(sub["name"])
                output_text = f'订阅：{airport_name}\n无流量信息'
                if sub.get('custom_message'):
                    output_text += f"\n备注：{escape_markdown(sub['custom_message'])}"
        else:
            output_text = f'订阅：{escape_markdown(sub["name"])}\n无法访问'
            if sub.get('custom_message'):
                output_text += f"\n备注：{escape_markdown(sub['custom_message'])}"
        
        final_output += output_text + '\n\n'

    # 更新消息内容
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=message_id,
        text=final_output,
        parse_mode='MarkdownV2'
    )

    # 60秒后删除消息
    asyncio.create_task(delete_message_after_delay(context, update.effective_chat.id, message_id))

async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /message 命令"""
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

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
    if not await group_permission_required(update, context):
        return
    if not await admin_required(update, context):
        return

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

async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /sub 命令，临时解析订阅链接"""
    if not await group_permission_required(update, context):
        return
    
    # 获取消息文本
    message_text = None
    if update.message.reply_to_message:
        message_text = update.message.reply_to_message.text or update.message.reply_to_message.caption
    elif context.args:
        message_text = context.args[0]
    
    if not message_text:
        await send_message(context, "请提供订阅链接，格式：/sub <链接> 或回复包含链接的消息", update.effective_chat.id)
        return

    # 查找订阅链接
    url_list = re.findall("https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]", message_text)
    
    if not url_list:
        await send_message(context, "未找到有效的订阅链接，请确保消息中包含正确的链接", update.effective_chat.id)
        return

    url = url_list[0]  # 只处理第一个找到的链接
    # 发送初始消息
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="正在解析订阅链接..."
    )
    message_id = message.message_id

    try:
        headers = {
            'User-Agent': 'ClashforWindows/0.18.1'
        }
        res = requests.get(url, headers=headers, timeout=5)
        while res.status_code in [301, 302]:
            url = res.headers['location']
            res = requests.get(url, headers=headers, timeout=5)

        if res.status_code == 200:
            try:
                info = res.headers['subscription-userinfo']
                info_num = re.findall(r'\d+', info)
                time_now = int(time.time())
                
                # 转义所有特殊字符
                safe_url = escape_markdown(url)
                airport_name = escape_markdown(get_filename_from_url(url))
                upload = escape_markdown(StrOfSize(int(info_num[0])))
                download = escape_markdown(StrOfSize(int(info_num[1])))
                remaining = escape_markdown(StrOfSize(int(info_num[2]) - int(info_num[1]) - int(info_num[0])))
                total = escape_markdown(StrOfSize(int(info_num[2])))
                
                output_text_head = (
                    f'订阅链接：{safe_url}\n'
                    f'机场名：{airport_name}\n'
                    f'已用上行：{upload}\n'
                    f'已用下行：{download}\n'
                    f'剩余：{remaining}\n'
                    f'总共：{total}'
                )
                
                if len(info_num) >= 4:
                    timeArray = time.localtime(int(info_num[3]) + 28800)
                    dateTime = time.strftime("%Y-%m-%d", timeArray)
                    if time_now <= int(info_num[3]):
                        lasttime = int(info_num[3]) - time_now
                        output_text = f"{output_text_head}\n此订阅将于 {escape_markdown(dateTime)} 过期，剩余 {escape_markdown(sec_to_data(lasttime))}"
                    else:
                        output_text = f"{output_text_head}\n此订阅已于 {escape_markdown(dateTime)} 过期！"
                else:
                    output_text = f"{output_text_head}\n到期时间：未知"
            except:
                safe_url = escape_markdown(url)
                airport_name = escape_markdown(get_filename_from_url(url))
                output_text = f'订阅链接：{safe_url}\n机场名：{airport_name}\n无流量信息'
        else:
            output_text = '无法访问该链接，请检查链接是否正确'
        
        # 更新消息内容
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=message_id,
            text=output_text,
            parse_mode='MarkdownV2'
        )
    except requests.exceptions.RequestException as e:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=message_id,
            text=f"连接失败：{str(e)}\n请检查链接是否正确或稍后重试"
        )
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=message_id,
            text=f"解析失败：{str(e)}\n请确保链接格式正确"
        )

    # 60秒后删除消息
    asyncio.create_task(delete_message_after_delay(context, update.effective_chat.id, message_id))

async def add_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /addgroup 命令，添加群组ID"""
    if not await admin_required(update, context):
        return

    if not update.effective_chat.type in ['group', 'supergroup']:
        await send_message(context, "请在群组中使用此命令", update.effective_chat.id)
        return

    chat_id = str(update.effective_chat.id)
    if chat_id in CHAT_IDS:
        await send_message(context, "此群组已在列表中", update.effective_chat.id)
        return

    CHAT_IDS.append(chat_id)
    config["chat_ids"] = CHAT_IDS
    save_config(config)
    await send_message(context, f"群组 {update.effective_chat.title} 已添加到列表", update.effective_chat.id)

async def remove_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /removegroup 命令，移除群组ID"""
    if not await admin_required(update, context):
        return

    if not update.effective_chat.type in ['group', 'supergroup']:
        await send_message(context, "请在群组中使用此命令", update.effective_chat.id)
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in CHAT_IDS:
        await send_message(context, "此群组不在列表中", update.effective_chat.id)
        return

    CHAT_IDS.remove(chat_id)
    config["chat_ids"] = CHAT_IDS
    save_config(config)
    await send_message(context, f"群组 {update.effective_chat.title} 已从列表中移除", update.effective_chat.id)

async def list_groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /listgroups 命令，列出所有群组"""
    if not await admin_required(update, context):
        return

    if not CHAT_IDS:
        await send_message(context, "当前没有添加任何群组", update.effective_chat.id)
        return

    text = "当前群组列表：\n\n"
    for chat_id in CHAT_IDS:
        try:
            chat = await context.bot.get_chat(chat_id)
            text += f"群组：{escape_html(chat.title)}\n"
            text += f"ID：{escape_html(chat_id)}\n"
            text += "-------------------\n"
        except Exception as e:
            text += f"ID：{escape_html(chat_id)} (无法获取群组信息)\n"
            text += "-------------------\n"
    
    await send_message(context, text, update.effective_chat.id)

def check_and_install_requirements():
    """检查并安装必要的依赖"""
    requirements = {
        'python-telegram-bot': 'telegram',
        'requests': 'requests',
        'beautifulsoup4': 'bs4'
    }
    
    missing_packages = []
    for package, import_name in requirements.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        logging.info(f"正在安装缺失的依赖: {', '.join(missing_packages)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_packages])
            logging.info("依赖安装完成")
        except Exception as e:
            logging.error(f"安装依赖失败: {str(e)}")
            sys.exit(1)
    else:
        logging.info("所有依赖已安装")

# 检查并安装依赖
check_and_install_requirements()

def escape_markdown(text):
    """转义 MarkdownV2 特殊字符"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_filename_from_url(url):
    if "sub?target=" in url:
        pattern = r"url=([^&]*)"
        match = re.search(pattern, url)
        if match:
            encoded_url = match.group(1)
            decoded_url = unquote(encoded_url)
            return get_filename_from_url(decoded_url)
    elif "api/v1/client/subscribe?token" in url:
        if "&flag=clash" not in url:
            url = url + "&flag=clash"
        try:
            response = requests.get(url)
            header = response.headers.get('Content-Disposition')
            if header:
                pattern = r"filename\*=UTF-8''(.+)"
                result = re.search(pattern, header)
                if result:
                    filename = result.group(1)
                    filename = unquote(filename)
                    airport_name = filename.replace("%20", " ").replace("%2B", "+")
                    return airport_name
        except:
            return '未知'
    else:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (HTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        }
        try:
            pattern = r'(https?://)([^/]+)'
            match = re.search(pattern, url)
            base_url = None
            if match:
                base_url = match.group(1) + match.group(2)
            response = requests.get(url=base_url + '/auth/login', headers=headers, timeout=10)
            if response.status_code != 200:
                response = requests.get(base_url, headers=headers, timeout=1)
            html = response.content
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string
            title = str(title).replace('登录 — ', '')
            if "Attention Required! | Cloudflare" in title:
                title = '该域名仅限国内IP访问'
            elif "Access denied" in title or "404 Not Found" in title:
                title = '该域名非机场面板域名'
            elif "Just a moment" in title:
                title = '该域名开启了5s盾'
            return title
        except:
            return '未知'

def convert_time_to_str(ts):
    return str(ts).zfill(2)

def sec_to_data(y):
    h = int(y // 3600 % 24)
    d = int(y // 86400)
    h = convert_time_to_str(h)
    d = convert_time_to_str(d)
    return d + "天" + h + "小时"

def StrOfSize(size):
    def strofsize(integer, remainder, level):
        if integer >= 1024:
            remainder = integer % 1024
            integer //= 1024
            level += 1
            return strofsize(integer, remainder, level)
        elif integer < 0:
            integer = 0
            return strofsize(integer, remainder, level)
        else:
            return integer, remainder, level

    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    integer, remainder, level = strofsize(size, 0, 0)
    if level + 1 > len(units):
        level = -1
    return ('{}.{:>03d} {}'.format(integer, remainder, units[level]))

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
        application.add_handler(CommandHandler("sub", sub_command))
        # 添加群组管理命令
        application.add_handler(CommandHandler("addgroup", add_group_command))
        application.add_handler(CommandHandler("removegroup", remove_group_command))
        application.add_handler(CommandHandler("listgroups", list_groups_command))

        # 设置定时任务
        application.job_queue.run_daily(
            check_command,
            time=dtime(hour=config.get("check_hour", 9), tzinfo=TIMEZONE),
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