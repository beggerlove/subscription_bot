# Telegram Subscription Bot

一个用于管理和监控订阅服务的Telegram机器人。

## 功能特点

- 自动检查订阅状态
- 支持多个订阅源
- 自定义提醒消息
- 群组权限管理
- 定时自动检查
- 流量使用统计

## 安装要求

- Python 3.8+
- pip (Python包管理器)
- Linux系统（推荐Ubuntu/Debian）

## Linux部署步骤

1. 克隆仓库到用户主目录
```bash
cd ~
git clone https://github.com/yourusername/subscription-bot.git
cd subscription-bot
```

2. 创建并激活虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置机器人
```bash
cp config.example.json config.json
```
编辑 `config.json` 文件，填入以下信息：
- `bot_token`: 从 @BotFather 获取的机器人token
- `admin_id`: 管理员的Telegram ID
- `chat_ids`: 允许使用机器人的群组ID列表
- `check_hour`: 每日自动检查的时间（24小时制）

5. 配置systemd服务
```bash
# 复制服务文件到systemd目录
sudo cp subscription-bot.service /etc/systemd/system/

# 重新加载systemd配置
sudo systemctl daemon-reload

# 启用并启动服务
sudo systemctl enable subscription-bot
sudo systemctl start subscription-bot
```

6. 检查服务状态
```bash
# 查看服务状态
sudo systemctl status subscription-bot

# 查看服务日志
sudo journalctl -u subscription-bot -f

# 查看应用日志
tail -f subscription_bot.log
```

## 使用说明

1. 启动机器人后，在Telegram中发送 `/start` 开始使用
2. 管理员命令：
   - `/add <名称> <订阅链接>` - 添加新订阅
   - `/remove <名称>` - 删除订阅
   - `/list` - 查看所有订阅
   - `/check` - 手动检查所有订阅状态
   - `/message <名称> <消息>` - 设置订阅的自定义消息
   - `/setchecktime <小时>` - 设置自动检查时间
   - `/addgroup <群组ID>` - 添加允许使用的群组
   - `/removegroup <群组ID>` - 移除群组权限
   - `/listgroups` - 查看所有允许的群组

3. 普通用户命令：
   - `/sub` - 查看订阅状态
   - `/help` - 获取帮助信息

## 服务管理命令

```bash
# 停止服务
sudo systemctl stop subscription-bot

# 重启服务
sudo systemctl restart subscription-bot

# 禁用开机自启
sudo systemctl disable subscription-bot

# 查看服务状态
sudo systemctl status subscription-bot
```

## 注意事项

1. 请确保配置文件中的敏感信息（如bot_token）不要泄露
2. 建议定期备份 `subscriptions.json` 文件
3. 如果遇到权限问题，请检查：
   - 项目目录的所有权
   - 虚拟环境的权限
   - 确保项目目录在用户主目录下

## 故障排除

如果遇到 "Unit has a bad unit file setting" 错误，请按以下步骤检查：

1. 检查服务文件权限
```bash
# 确保服务文件权限正确
sudo chmod 644 /etc/systemd/system/subscription-bot.service
```

2. 检查服务文件语法
```bash
# 检查服务文件语法
sudo systemd-analyze verify subscription-bot.service
```

3. 检查路径权限
```bash
# 确保项目目录权限正确
sudo chown -R $USER:$USER ~/subscription-bot
chmod -R 755 ~/subscription-bot
```

4. 检查虚拟环境
```bash
# 确保虚拟环境存在且可执行
ls -l ~/subscription-bot/venv/bin/python
```

5. 检查日志
```bash
# 查看详细的系统日志
sudo journalctl -xe
```

## 贡献

欢迎提交Issue和Pull Request来帮助改进这个项目。

