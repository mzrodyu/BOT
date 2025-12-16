# CatieBot 运行环境部署指南

## 方式一：1Panel Python 项目部署（推荐）

### 1. 准备工作

1. 安装 1Panel 面板
2. 在 1Panel 应用商店安装 **运行环境 → Python**
3. 确保安装 Python 3.10+

### 2. 上传代码

```bash
cd /opt
git clone https://github.com/mzrodyu/BOT.git catiebot
cd catiebot
```

### 3. 创建配置文件

```bash
cp .env.example .env
nano .env
```

填写以下内容：

```env
DISCORD_BOT_TOKEN=你的Discord机器人Token
ADMIN_PASSWORD=你的后台密码
LLM_API_KEY=你的LLM API密钥
LLM_BASE_URL=https://api.openai.com/v1
```

### 4. 在 1Panel 创建 Python 项目

进入 **网站 → 运行环境 → Python**，点击 **创建运行环境**

#### 后端项目（Backend）

- **名称**: catiebot-backend
- **运行目录**: `/opt/catiebot`
- **版本**: Python 3.10+
- **启动命令**: `python run_backend.py --port 8000`
- **外部端口**: 8000

#### Bot项目

- **名称**: catiebot-bot
- **运行目录**: `/opt/catiebot`
- **版本**: Python 3.10+
- **启动命令**: `python run_bot.py`

### 5. 安装依赖

在项目详情页点击 **安装依赖** 或命令行执行：

```bash
cd /opt/catiebot
pip install -r requirements.txt
```

### 6. 启动项目

在 1Panel 中启动两个项目：

1. 先启动 `catiebot-backend`
2. 再启动 `catiebot-bot`

### 7. 访问后台

打开浏览器访问：`http://你的服务器IP:8000/admin`

---

## 方式二：Docker 部署

### 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com | bash
```

### 2. 下载代码

```bash
cd /www/wwwroot
git clone https://github.com/mzrodyu/BOT.git catiebot
cd catiebot
```

### 3. 创建配置文件

```bash
cp .env.example .env
nano .env
```

### 4. 启动

```bash
docker-compose up -d
```

### 5. 查看日志

```bash
docker-compose logs -f
```

---

## 常见问题

### Q: 启动报错 `ValidationError: Extra inputs are not permitted`

**A**: 代码版本太旧，执行 `git pull` 更新代码后重启。

### Q: 后台打不开

**A**: 检查：

1. 后端是否正常运行（看日志）
2. 防火墙是否放行端口（8000）
3. 1Panel 防火墙是否放行（主机 → 防火墙）

### Q: Bot 不回复

**A**: 检查：

1. `.env` 中的 `DISCORD_BOT_TOKEN` 是否正确
2. Bot 是否有发送消息权限
3. 频道是否在白名单中

### Q: 如何更新代码

```bash
cd /opt/catiebot
git pull
# 然后在 1Panel 重启两个项目
```

### Q: 如何查看日志

在 1Panel 运行环境中，点击项目查看日志。

---

## 端口说明

| 服务    | 默认端口 | 说明                    |
| ------- | -------- | ----------------------- |
| Backend | 8000     | Web后台和API            |
| Bot     | 无       | 连接Discord，不需要端口 |

---

## 文件结构

```
catiebot/
├── .env              # 配置文件（需要创建）
├── catiebot.db       # 数据库（自动生成）
├── run_backend.py    # 后端启动脚本
├── run_bot.py        # Bot启动脚本
├── requirements.txt  # Python依赖
└── ...
```
