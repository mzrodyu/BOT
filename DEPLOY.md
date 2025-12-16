# CatieBot 运行环境部署指南

## 方式一：1Panel Python 项目部署（推荐）

### 1. 准备工作

1. 安装 1Panel 面板
2. 在 1Panel 应用商店安装 **运行环境 → Python**（版本 3.10+）

### 2. 上传代码

```bash
cd /www/wwwroot
git clone https://github.com/mzrodyu/BOT.git catiebot
```

### 3. 创建 Python 运行环境

进入 **网站 → 运行环境 → Python**，点击 **创建运行环境**

#### 后端项目（Backend）

| 配置项       | 值                                                                     |
| ------------ | ---------------------------------------------------------------------- |
| 名称         | catiebot-backend                                                       |
| 项目目录     | `/www/wwwroot/catiebot`                                                |
| 启动命令     | `pip install -r requirements.txt && python run_backend.py --port 8001` |
| 外部映射端口 | 8001→8001                                                              |

#### Bot项目

| 配置项   | 值                                                     |
| -------- | ------------------------------------------------------ |
| 名称     | catiebot-discord                                       |
| 项目目录 | `/www/wwwroot/catiebot`                                |
| 启动命令 | `pip install -r requirements.txt && python run_bot.py` |

#### 环境变量（两个项目都加这些）

在"环境变量"标签页添加：

| 变量名            | 值                      |
| ----------------- | ----------------------- |
| BOT_ID            | 自定义Bot标识（如 yu）  |
| ADMIN_PASSWORD    | 你的后台密码            |
| DISCORD_BOT_TOKEN | 你的Discord机器人Token  |
| BACKEND_URL       | <http://127.0.0.1:8001> |

> LLM 配置（API地址、密钥、模型）在后台界面 **API设置** 中配置，不需要环境变量

### 4. 启动项目

1. 先启动 `catiebot-backend`
2. 再启动 `catiebot-discord`

### 5. 放行端口

**主机 → 防火墙** 放行 8001 端口

### 6. 访问后台

打开浏览器访问：`http://你的服务器IP:8001/admin`

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
