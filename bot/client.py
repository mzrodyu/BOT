import discord
from discord.ext import commands
from discord import app_commands
import httpx
import json
import os
from config import get_settings
from typing import Optional, List

settings = get_settings()

# 直接从环境变量读取，作为备用
BACKEND_URL = os.getenv("BACKEND_URL", settings.backend_url).rstrip('/')
BOT_ID = os.getenv("BOT_ID", settings.bot_id)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", settings.admin_password)

print(f"[Config] BACKEND_URL={BACKEND_URL}, BOT_ID={BOT_ID}", flush=True)


class CatieBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self._synced = False
    
    async def setup_hook(self):
        await self.add_cog(MessageHandler(self))
        await self.add_cog(AdminCommands(self))
        await self.add_cog(PublicAPICommands(self))
        # 全局同步斜杠命令
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands globally", flush=True)
        except Exception as e:
            print(f"Failed to sync commands: {e}", flush=True)
    
    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})", flush=True)
        print(f"Connected to {len(self.guilds)} guilds", flush=True)
        
        # 启动时清理服务器级别的重复命令，只保留全局命令
        if not self._synced:
            self._synced = True
            for guild in self.guilds:
                try:
                    # 清空服务器级别命令，避免与全局命令重复
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    print(f"Cleared guild commands for {guild.name}", flush=True)
                except Exception as e:
                    print(f"Failed to clear commands for {guild.name}: {e}", flush=True)
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="@我 来聊天"
            )
        )
        # 上报频道列表到后端
        await self.report_channels()
    
    async def report_channels(self):
        """上报Bot可见的所有频道到后端"""
        try:
            channels_data = []
            for guild in self.guilds:
                guild_data = {
                    "guild_id": str(guild.id),
                    "guild_name": guild.name,
                    "channels": []
                }
                
                for channel in guild.channels:
                    # 文字频道、论坛
                    if isinstance(channel, discord.TextChannel):
                        channel_info = {
                            "channel_id": str(channel.id),
                            "channel_name": channel.name,
                            "type": "text",
                            "parent_id": str(channel.category_id) if channel.category_id else None
                        }
                        guild_data["channels"].append(channel_info)
                    elif isinstance(channel, discord.ForumChannel):
                        channel_info = {
                            "channel_id": str(channel.id),
                            "channel_name": channel.name,
                            "type": "forum",
                            "parent_id": str(channel.category_id) if channel.category_id else None
                        }
                        guild_data["channels"].append(channel_info)
                        
                        # 获取Forum频道中的活跃帖子(threads)
                        try:
                            async for thread in channel.archived_threads(limit=50):
                                thread_info = {
                                    "channel_id": str(thread.id),
                                    "channel_name": thread.name,
                                    "type": "thread",
                                    "parent_id": str(channel.id)
                                }
                                guild_data["channels"].append(thread_info)
                        except:
                            pass
                
                # 获取所有活跃的threads（包括Forum帖子）
                for thread in guild.threads:
                    # 检查是否已添加
                    existing_ids = {ch["channel_id"] for ch in guild_data["channels"]}
                    if str(thread.id) not in existing_ids:
                        thread_info = {
                            "channel_id": str(thread.id),
                            "channel_name": thread.name,
                            "type": "thread",
                            "parent_id": str(thread.parent_id) if thread.parent_id else None
                        }
                        guild_data["channels"].append(thread_info)
                
                channels_data.append(guild_data)
            
            await self.http_client.post(
                f"{BACKEND_URL}/api/admin/bot-channels",
                json={
                    "bot_id": BOT_ID,
                    "guilds": channels_data
                },
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            print(f"Reported {sum(len(g['channels']) for g in channels_data)} channels to backend", flush=True)
        except Exception as e:
            print(f"Error reporting channels: {e}", flush=True)
    
    async def close(self):
        await self.http_client.aclose()
        await super().close()


class MessageHandler(commands.Cog):
    def __init__(self, bot: CatieBot):
        self.bot = bot
        self._config_cache = {}
        self._config_cache_time = 0
    
    async def get_bot_config(self) -> dict:
        """获取Bot配置（带缓存，5分钟）"""
        import time
        if time.time() - self._config_cache_time < 300 and self._config_cache:
            return self._config_cache
        
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/admin/bot-config/{BOT_ID}",
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            if resp.status_code == 200:
                self._config_cache = resp.json()
                self._config_cache_time = time.time()
        except Exception as e:
            print(f"Error getting bot config: {e}")
        return self._config_cache
    
    async def is_channel_allowed(self, channel_id: str) -> bool:
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/admin/channels/check/{BOT_ID}/{channel_id}"
            )
            data = resp.json()
            return data.get("is_whitelisted", False)
        except Exception as e:
            print(f"Error checking channel: {e}")
            return True
    
    async def should_respond(self, message: discord.Message) -> bool:
        # 检查是否是机器人发送的消息
        if message.author.bot:
            # 获取配置，检查是否允许响应其他机器人
            config = await self.get_bot_config()
            if not config.get("respond_to_bot", False):
                return False
            # 允许响应其他机器人时，只响应@提及
            if self.bot.user.mentioned_in(message):
                return True
            return False
        
        if self.bot.user.mentioned_in(message):
            return True
        
        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            if ref_msg.author == self.bot.user:
                return True
        
        return False
    
    async def get_context_messages(self, channel: discord.TextChannel, limit: int) -> List[dict]:
        messages = []
        async for msg in channel.history(limit=limit):
            # 判断消息角色
            if msg.author == self.bot.user:
                # 自己的消息作为 assistant
                role = "assistant"
                content = msg.content
                # 清理Bot回复中的统计信息
                import re
                content = re.sub(r'\n?-# Time:.*$', '', content, flags=re.MULTILINE)
                content = re.sub(r'\n?`Time:.*$', '', content, flags=re.MULTILINE)
                # 清理表情格式残留
                content = re.sub(r'<a?:[^:]+:\d+>', '', content)
            elif msg.author.bot:
                # 其他Bot的消息作为 user（带Bot标记）
                role = "user"
                import re
                content = re.sub(r'<@!?\d+>', '', msg.content).strip()
                if content:
                    content = f"[Bot:{msg.author.display_name}]: {content}"
            else:
                # 普通用户的消息
                role = "user"
                import re
                content = re.sub(r'<@!?\d+>', '', msg.content).strip()
                if content:
                    content = f"[{msg.author.display_name}]: {content}"
            
            if content.strip():
                messages.append({"role": role, "content": content})
        
        return list(reversed(messages[1:]))
    
    async def get_pinned_messages(self, channel: discord.TextChannel) -> List[str]:
        try:
            pinned = await channel.pins()
            return [f"[{p.author.display_name}]: {p.content}" for p in pinned[:5]]
        except:
            return []
    
    def get_guild_emojis(self, guild: discord.Guild) -> str:
        """获取服务器表情列表"""
        if not guild or not guild.emojis:
            return ""
        emoji_list = [f":{e.name}:" for e in guild.emojis[:50]]
        return "可用表情: " + " ".join(emoji_list)
    
    async def get_reply_content(self, message: discord.Message) -> Optional[str]:
        if message.reference and message.reference.resolved:
            ref = message.reference.resolved
            return f"[{ref.author.display_name}]: {ref.content}"
        return None
    
    async def get_image_urls(self, message: discord.Message) -> List[str]:
        """获取图片并转为base64 data URL（因为Discord CDN有访问限制）"""
        import base64
        import io
        urls = []
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
        
        def convert_gif_to_png(image_data: bytes) -> tuple[bytes, str]:
            """将GIF转换为PNG（提取第一帧），因为大多数AI模型不支持GIF"""
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(image_data))
                # 转换为RGB模式（处理透明度）
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGBA')
                    # 创建白色背景
                    background = Image.new('RGBA', img.size, (255, 255, 255, 255))
                    background.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                    img = background.convert('RGB')
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                output = io.BytesIO()
                img.save(output, format='PNG')
                return output.getvalue(), 'image/png'
            except ImportError:
                print("[MessageHandler] PIL not installed, cannot convert GIF")
                return image_data, 'image/gif'
            except Exception as e:
                print(f"[MessageHandler] GIF conversion failed: {e}")
                return image_data, 'image/gif'
        
        # 从附件获取图片
        for attachment in message.attachments:
            is_image = False
            content_type = attachment.content_type or "image/png"
            if content_type.startswith("image/"):
                is_image = True
            elif attachment.filename.lower().endswith(image_extensions):
                is_image = True
                # 根据扩展名推断content_type
                ext = attachment.filename.lower().split('.')[-1]
                content_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
            
            if is_image:
                try:
                    # 下载图片并转为base64
                    image_data = await attachment.read()
                    
                    # 如果是GIF，转换为PNG
                    if content_type == 'image/gif' or attachment.filename.lower().endswith('.gif'):
                        print(f"[MessageHandler] Converting GIF to PNG: {attachment.filename}")
                        image_data, content_type = convert_gif_to_png(image_data)
                    
                    b64_data = base64.b64encode(image_data).decode('utf-8')
                    data_url = f"data:{content_type};base64,{b64_data}"
                    urls.append(data_url)
                    print(f"[MessageHandler] Image converted to base64: {attachment.filename} ({len(image_data)} bytes)")
                except Exception as e:
                    print(f"[MessageHandler] Failed to download image {attachment.filename}: {e}")
        
        # 从embed获取图片（需要通过HTTP下载）
        for embed in message.embeds:
            for img_url in [embed.image and embed.image.url, embed.thumbnail and embed.thumbnail.url]:
                if img_url:
                    try:
                        async with self.bot.http_client.stream("GET", img_url, timeout=10.0) as resp:
                            if resp.status_code == 200:
                                image_data = await resp.aread()
                                # 从URL或content-type推断类型
                                ct = resp.headers.get("content-type", "image/png")
                                b64_data = base64.b64encode(image_data).decode('utf-8')
                                data_url = f"data:{ct};base64,{b64_data}"
                                urls.append(data_url)
                                print(f"[MessageHandler] Embed image converted to base64: {len(image_data)} bytes")
                    except Exception as e:
                        print(f"[MessageHandler] Failed to download embed image: {e}")
        
        return urls
    
    def process_content(self, content: str, guild: discord.Guild) -> str:
        content = content.replace(f"<@{self.bot.user.id}>", "").strip()
        content = content.replace(f"<@!{self.bot.user.id}>", "").strip()
        return content
    
    async def send_streaming_response(self, message: discord.Message, request_data: dict):
        import time
        start_time = time.time()
        reply_msg = await message.reply("💭 思考中...", mention_author=False)
        full_response = ""
        last_update = 0
        update_interval = 0.8  # 每0.8秒更新一次，减少卡顿
        
        try:
            async with self.bot.http_client.stream(
                "POST",
                f"{BACKEND_URL}/api/chat/stream",
                json=request_data,
                timeout=120.0
            ) as response:
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    
                    while "\n\n" in buffer:
                        line, buffer = buffer.split("\n\n", 1)
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                content = data.get("content", "")
                                
                                if content.startswith("[BLOCKED]"):
                                    await reply_msg.edit(content=f"⚠️ {content[9:]}")
                                    return
                                elif content.startswith("[ERROR]"):
                                    await reply_msg.edit(content=f"❌ 发生错误: {content[7:]}")
                                    return
                                elif content.startswith("[STATS]"):
                                    # 解析统计信息
                                    stats_data = content[7:].split("|")
                                    if len(stats_data) >= 2:
                                        request_data["_input_tokens"] = int(stats_data[0]) if stats_data[0] else 0
                                        request_data["_output_tokens"] = int(stats_data[1]) if stats_data[1] else 0
                                    continue
                                
                                full_response += content
                                
                                # 按时间间隔更新，减少API调用
                                current_time = time.time()
                                if current_time - last_update >= update_interval:
                                    display = full_response[:1900] + "..." if len(full_response) > 1900 else full_response
                                    try:
                                        await reply_msg.edit(content=display or "思考中...")
                                    except:
                                        pass
                                    last_update = current_time
                            except json.JSONDecodeError:
                                continue
                
                if full_response:
                    # 清理模型可能输出的内部格式前缀
                    import re
                    # 匹配 (回复[xxx]) 或 （回复【xxx】）等各种变体
                    full_response = re.sub(r'^[\s\n]*[\(（]回复[\[【][^\]】]*[\]】][\)）][\s\n]*', '', full_response)
                    full_response = re.sub(r'^[\s\n]*\[回复[^\]]*\][\s\n]*', '', full_response)
                    full_response = re.sub(r'^[\s\n]*回复[\[【][^\]】]*[\]】][：:]\s*', '', full_response)
                    
                    # 处理服务器表情
                    full_response = await self.process_emojis(full_response, message.guild)
                    
                    # 计算统计信息（小字体格式）
                    elapsed = time.time() - start_time
                    input_t = request_data.get("_input_tokens", 0)
                    output_t = request_data.get("_output_tokens", 0)
                    stats = f"\n-# Time: {elapsed:.1f}s | Input: {input_t}t | Output: {output_t}t"
                    
                    if len(full_response) > 2000 - len(stats):
                        chunks = [full_response[i:i+1950] for i in range(0, len(full_response), 1950)]
                        await reply_msg.edit(content=chunks[0])
                        for i, chunk in enumerate(chunks[1:]):
                            if i == len(chunks) - 2:  # 最后一条加统计
                                chunk += stats
                            await message.channel.send(chunk)
                    else:
                        await reply_msg.edit(content=full_response + stats)
                else:
                    await reply_msg.edit(content="抱歉，我没有生成回复。")
                    
        except Exception as e:
            print(f"Streaming error: {e}")
            await reply_msg.edit(content=f"❌ 发生错误，请稍后再试")
    
    async def process_emojis(self, content: str, guild: discord.Guild) -> str:
        """将文本中的表情标记替换为服务器表情"""
        import re
        
        if not guild:
            return content
        
        # 匹配 :emoji_name: 格式（但不匹配已经是Discord格式的表情）
        emoji_pattern = re.compile(r'(?<![<a]):([a-zA-Z0-9_]+):(?!\d)')
        
        def replace_emoji(match):
            emoji_name = match.group(1)
            # 在当前服务器找
            for emoji in guild.emojis:
                if emoji.name.lower() == emoji_name.lower():
                    # 返回正确的Discord表情格式
                    if emoji.animated:
                        return f"<a:{emoji.name}:{emoji.id}>"
                    else:
                        return f"<:{emoji.name}:{emoji.id}>"
            # 找不到返回原文
            return match.group(0)
        
        return emoji_pattern.sub(replace_emoji, content)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not await self.should_respond(message):
            return
        
        if not await self.is_channel_allowed(str(message.channel.id)):
            return
        
        content = self.process_content(message.content, message.guild)
        if not content and not message.attachments:
            return
        
        context_messages = await self.get_context_messages(
            message.channel, 
            settings.context_limit
        )
        pinned_messages = await self.get_pinned_messages(message.channel)
        reply_content = await self.get_reply_content(message)
        image_urls = await self.get_image_urls(message)
        if image_urls:
            print(f"[MessageHandler] Found {len(image_urls)} images: {image_urls}")
        guild_emojis = self.get_guild_emojis(message.guild)
        
        request_data = {
            "bot_id": BOT_ID,
            "discord_id": str(message.author.id),
            "username": message.author.display_name,
            "channel_id": str(message.channel.id),
            "message": content,
            "context_messages": context_messages,
            "pinned_messages": pinned_messages,
            "reply_content": reply_content,
            "image_urls": image_urls,
            "guild_emojis": guild_emojis
        }
        
        try:
            async with message.channel.typing():
                await self.send_streaming_response(message, request_data)
        except discord.Forbidden:
            # 没有typing权限时直接发送，不显示"正在输入"
            await self.send_streaming_response(message, request_data)


DEVELOPER_ID = 1373778569154658426


class AdminCommands(commands.Cog):
    def __init__(self, bot: CatieBot):
        self.bot = bot
        self._admin_ids_cache = set()
        self._cache_time = 0
    
    async def get_admin_ids(self) -> set:
        """从后台获取管理员ID列表（带缓存）"""
        import time
        # 缓存5分钟
        if time.time() - self._cache_time < 300 and self._admin_ids_cache:
            return self._admin_ids_cache
        
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/admin/bot-config",
                params={"bot_id": BOT_ID},
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            if resp.status_code == 200:
                config = resp.json()
                admin_str = config.get("admin_ids", "")
                if admin_str:
                    self._admin_ids_cache = set(int(x.strip()) for x in admin_str.split(",") if x.strip().isdigit())
                self._cache_time = time.time()
        except:
            pass
        return self._admin_ids_cache
    
    async def is_admin(self, interaction: discord.Interaction) -> bool:
        # 开发者永远是管理员
        if interaction.user.id == DEVELOPER_ID:
            return True
        # 检查后台配置的管理员
        admin_ids = await self.get_admin_ids()
        if interaction.user.id in admin_ids:
            return True
        # Discord服务器管理员
        if interaction.user.guild_permissions.administrator:
            return True
        return False
    
    @app_commands.command(name="ban", description="将用户加入黑名单")
    @app_commands.describe(
        user="要拉黑的用户",
        reason="拉黑原因",
        duration="时长(分钟)，留空为永久"
    )
    async def ban_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = None,
        duration: int = None
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/admin/blacklist",
                json={
                    "discord_id": str(user.id),
                    "username": user.display_name,
                    "reason": reason,
                    "banned_by": str(interaction.user.id),
                    "is_permanent": duration is None,
                    "duration_minutes": duration
                },
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                duration_text = f"{duration}分钟" if duration else "永久"
                await interaction.response.send_message(
                    f"✅ 已将 {user.mention} 加入黑名单 ({duration_text})",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 操作失败", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="unban", description="将用户从黑名单移除")
    @app_commands.describe(user="要解禁的用户")
    async def unban_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.delete(
                f"{BACKEND_URL}/api/admin/blacklist/{user.id}",
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                await interaction.response.send_message(
                    f"✅ 已将 {user.mention} 从黑名单移除",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 用户不在黑名单中", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="blacklist", description="查看黑名单列表")
    async def show_blacklist(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/admin/blacklist",
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                blacklist = resp.json()
                if not blacklist:
                    await interaction.response.send_message("📋 黑名单为空", ephemeral=True)
                    return
                
                lines = []
                for ban in blacklist[:20]:
                    status = "永久" if ban["is_permanent"] else f"到期: {ban.get('expires_at', 'N/A')}"
                    lines.append(f"• <@{ban['discord_id']}> - {status}")
                
                await interaction.response.send_message(
                    f"📋 **黑名单** ({len(blacklist)}人)\n" + "\n".join(lines),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 获取失败", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="addchannel", description="将当前频道加入白名单")
    async def add_channel(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/admin/channels",
                json={
                    "bot_id": BOT_ID,
                    "channel_id": str(interaction.channel_id),
                    "guild_id": str(interaction.guild_id),
                    "channel_name": interaction.channel.name,
                    "added_by": str(interaction.user.id)
                },
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                await interaction.response.send_message(
                    f"✅ 已将 {interaction.channel.mention} 加入白名单",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 操作失败", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="removechannel", description="将当前频道从白名单移除")
    async def remove_channel(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.delete(
                f"{BACKEND_URL}/api/admin/channels/{BOT_ID}/{interaction.channel_id}",
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                await interaction.response.send_message(
                    f"✅ 已将 {interaction.channel.mention} 从白名单移除",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 频道不在白名单中", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="channels", description="查看频道白名单")
    async def show_channels(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/admin/channels",
                params={"bot_id": BOT_ID, "guild_id": str(interaction.guild_id)},
                headers={"X-Admin-Secret": ADMIN_PASSWORD}
            )
            
            if resp.status_code == 200:
                channels = resp.json()
                if not channels:
                    await interaction.response.send_message(
                        "📋 白名单为空（所有频道可用）",
                        ephemeral=True
                    )
                    return
                
                lines = [f"• <#{ch['channel_id']}>" for ch in channels]
                await interaction.response.send_message(
                    f"📋 **频道白名单** ({len(channels)}个)\n" + "\n".join(lines),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ 获取失败", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 错误: {e}", ephemeral=True)
    
    @app_commands.command(name="warn", description="警告用户（大字报）")
    @app_commands.describe(user="要警告的用户", message="自定义警告内容（可选）")
    async def warn_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        message: str = None
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        default_msg = "能别这么恶俗吗，把小头挂在自己大头的产物上很有趣吗？公开发表请至少遵守公序良俗。"
        warning_content = message or default_msg
        
        warning_message = f"""# ⚠️ 警告 {user.mention}

{warning_content}"""
        
        await interaction.response.send_message(warning_message)
    
    @app_commands.command(name="howtoask", description="提示用户如何正确提问")
    @app_commands.describe(user="要提示的用户")
    async def how_to_ask(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        guide_message = f"""# 📸 {user.mention} 提问请发送酒馆插头截图+酒馆后台截图

插头清晰可见，不可打码。"""
        
        await interaction.response.send_message(guide_message)
    
    @app_commands.command(name="delmsg", description="删除Bot发送的指定消息")
    @app_commands.describe(message_link="消息链接")
    async def delete_bot_message(
        self,
        interaction: discord.Interaction,
        message_link: str
    ):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        import re
        # 解析消息链接: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}
        pattern = r'https://(?:ptb\.|canary\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.match(pattern, message_link)
        
        if not match:
            await interaction.response.send_message("❌ 无效的消息链接格式", ephemeral=True)
            return
        
        guild_id, channel_id, message_id = match.groups()
        
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                channel = await self.bot.fetch_channel(int(channel_id))
            
            message = await channel.fetch_message(int(message_id))
            
            # 检查是否是Bot自己的消息
            if message.author.id != self.bot.user.id:
                await interaction.response.send_message("❌ 只能删除Bot自己发送的消息", ephemeral=True)
                return
            
            await message.delete()
            await interaction.response.send_message(f"✅ 已删除消息", ephemeral=True)
            
        except discord.NotFound:
            await interaction.response.send_message("❌ 消息不存在或已被删除", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 没有权限删除该消息", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 删除失败: {e}", ephemeral=True)
    
    @app_commands.command(name="sync", description="同步斜杠命令到当前服务器（立即生效）")
    async def sync_commands(self, interaction: discord.Interaction):
        if not await self.is_admin(interaction):
            await interaction.response.send_message("❌ 你没有权限执行此操作", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild = interaction.guild
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            await interaction.followup.send(f"✅ 已同步 {len(synced)} 个命令到此服务器", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 同步失败: {e}", ephemeral=True)


class PublicAPICommands(commands.Cog):
    """公益站命令"""
    
    def __init__(self, bot: CatieBot):
        self.bot = bot
    
    @app_commands.command(name="公益站", description="公益站 - 注册账号、查看用量")
    @app_commands.describe(action="选择操作")
    @app_commands.choices(action=[
        app_commands.Choice(name="📝 注册账号", value="register"),
        app_commands.Choice(name="📊 查看用量", value="usage"),
        app_commands.Choice(name="🔑 查看密钥", value="key"),
    ])
    async def public_api(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str]
    ):
        await interaction.response.defer(ephemeral=True)
        
        try:
            if action.value == "register":
                await self._handle_register(interaction)
            elif action.value == "usage":
                await self._handle_usage(interaction)
            elif action.value == "key":
                await self._handle_key(interaction)
        except Exception as e:
            await interaction.followup.send(f"❌ 发生错误: {e}", ephemeral=True)
    
    async def _handle_register(self, interaction: discord.Interaction):
        """处理注册"""
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/register",
                json={
                    "bot_id": BOT_ID,
                    "discord_id": str(interaction.user.id),
                    "discord_username": interaction.user.display_name
                }
            )
            
            data = resp.json()
            
            if data.get("success"):
                # 注册成功
                embed = discord.Embed(
                    title="✅ 注册成功",
                    color=discord.Color.green()
                )
                embed.add_field(name="用户名", value=f"`{data.get('username')}`", inline=True)
                embed.add_field(name="密码", value=f"||`{data.get('password')}`||", inline=True)
                embed.add_field(name="API Key", value=f"||`{data.get('api_key', '生成中...')}`||", inline=False)
                embed.set_footer(text="⚠️ 请妥善保存密码，此信息仅显示一次")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                error = data.get("error", "未知错误")
                if "已经注册" in error:
                    # 已注册，显示现有信息
                    embed = discord.Embed(
                        title="ℹ️ 您已注册",
                        description="您之前已经注册过了",
                        color=discord.Color.blue()
                    )
                    if data.get("username"):
                        embed.add_field(name="用户名", value=f"`{data.get('username')}`", inline=True)
                    if data.get("api_key"):
                        embed.add_field(name="API Key", value=f"||`{data.get('api_key')}`||", inline=False)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ 注册失败: {error}", ephemeral=True)
                    
        except Exception as e:
            await interaction.followup.send(f"❌ 请求失败: {e}", ephemeral=True)
    
    async def _handle_usage(self, interaction: discord.Interaction):
        """处理查看用量"""
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/public/usage/{BOT_ID}/{interaction.user.id}"
            )
            
            data = resp.json()
            
            if data.get("success"):
                embed = discord.Embed(
                    title="📊 用量统计",
                    color=discord.Color.blue()
                )
                embed.add_field(name="用户名", value=f"`{data.get('username')}`", inline=True)
                
                # 格式化金额显示
                quota = data.get("quota")
                used = data.get("used")
                remain = data.get("remain")
                
                if isinstance(quota, (int, float)):
                    embed.add_field(name="总额度", value=f"${quota:.4f}", inline=True)
                    embed.add_field(name="已使用", value=f"${used:.4f}", inline=True)
                    embed.add_field(name="剩余", value=f"${remain:.4f}", inline=True)
                else:
                    embed.add_field(name="额度", value=str(quota), inline=True)
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                error = data.get("error", "未知错误")
                if "未注册" in error:
                    await interaction.followup.send("❌ 您还未注册，请先使用 `/公益站 注册账号`", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ 查询失败: {error}", ephemeral=True)
                    
        except Exception as e:
            await interaction.followup.send(f"❌ 请求失败: {e}", ephemeral=True)
    
    async def _handle_key(self, interaction: discord.Interaction):
        """处理查看密钥"""
        try:
            resp = await self.bot.http_client.get(
                f"{BACKEND_URL}/api/public/check/{BOT_ID}/{interaction.user.id}"
            )
            
            data = resp.json()
            
            if data.get("registered"):
                embed = discord.Embed(
                    title="🔑 您的API密钥",
                    color=discord.Color.gold()
                )
                embed.add_field(name="用户名", value=f"`{data.get('username')}`", inline=True)
                embed.add_field(name="API Key", value=f"||`{data.get('api_key', '无')}`||", inline=False)
                embed.set_footer(text="点击黑条查看密钥")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ 您还未注册，请先使用 `/公益站 注册账号`", ephemeral=True)
                    
        except Exception as e:
            await interaction.followup.send(f"❌ 请求失败: {e}", ephemeral=True)
    
    @app_commands.command(name="抽奖", description="查看并参与抽奖活动")
    async def lottery(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.get(f"{BACKEND_URL}/api/public/lottery/{BOT_ID}")
            lotteries = resp.json()
            
            if not lotteries:
                await interaction.followup.send("📭 暂无进行中的抽奖活动", ephemeral=True)
                return
            
            # 创建选择菜单
            embed = discord.Embed(title="🎁 抽奖活动", color=discord.Color.purple())
            for l in lotteries[:5]:
                status = "🔴 已结束" if l.get("is_ended") else "🟢 进行中"
                embed.add_field(
                    name=f"{l['title']} {status}",
                    value=f"奖品额度: {l['prize_quota']} | {l['winner_count']}人中奖 | {l['participant_count']}人参与\n使用 `/参与抽奖 {l['id']}` 参与",
                    inline=False
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 获取抽奖列表失败: {e}", ephemeral=True)
    
    @app_commands.command(name="参与抽奖", description="参与指定抽奖活动")
    @app_commands.describe(lottery_id="抽奖活动ID")
    async def join_lottery(self, interaction: discord.Interaction, lottery_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/lottery/join",
                json={
                    "bot_id": BOT_ID,
                    "lottery_id": lottery_id,
                    "discord_id": str(interaction.user.id),
                    "discord_username": interaction.user.display_name
                }
            )
            data = resp.json()
            if data.get("success"):
                await interaction.followup.send(f"✅ 参与成功！当前已有 {data.get('participant_count', '?')} 人参与", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {data.get('error', '参与失败')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 参与失败: {e}", ephemeral=True)
    
    @app_commands.command(name="红包", description="查看并领取红包")
    async def redpacket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.get(f"{BACKEND_URL}/api/public/redpacket/{BOT_ID}")
            packets = resp.json()
            
            if not packets:
                await interaction.followup.send("📭 暂无可领取的红包", ephemeral=True)
                return
            
            embed = discord.Embed(title="🧧 红包列表", color=discord.Color.red())
            for p in packets[:5]:
                rtype = "🎲 拼手气" if p.get("is_random") else "💰 普通"
                embed.add_field(
                    name=f"{rtype} 红包 #{p['id']}",
                    value=f"剩余: {p['remaining_count']}/{p['total_count']} 个\n使用 `/领红包 {p['id']}` 领取",
                    inline=False
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 获取红包列表失败: {e}", ephemeral=True)
    
    @app_commands.command(name="领红包", description="领取指定红包")
    @app_commands.describe(red_packet_id="红包ID")
    async def claim_redpacket(self, interaction: discord.Interaction, red_packet_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/redpacket/claim",
                json={
                    "bot_id": BOT_ID,
                    "red_packet_id": red_packet_id,
                    "discord_id": str(interaction.user.id),
                    "discord_username": interaction.user.display_name
                }
            )
            data = resp.json()
            if data.get("success"):
                quota = data.get("quota", 0)
                usd = quota / 500000
                await interaction.followup.send(f"🎉 恭喜领到 **{quota}** 额度 (约 ${usd:.4f})！剩余 {data.get('remaining_count', 0)} 个", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {data.get('error', '领取失败')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 领取失败: {e}", ephemeral=True)
    
    # ========== 管理员公开发布命令 ==========
    @app_commands.command(name="发起抽奖", description="【管理员】发起一个公开抽奖活动")
    @app_commands.describe(
        title="抽奖标题",
        prize="奖品额度(NewAPI单位，1美元=500000)",
        winners="中奖人数"
    )
    async def publish_lottery(
        self, 
        interaction: discord.Interaction, 
        title: str,
        prize: int = 500000,
        winners: int = 1
    ):
        # 检查管理员权限
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 只有管理员可以发起抽奖", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # 创建抽奖
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/lottery",
                json={
                    "bot_id": BOT_ID,
                    "title": title,
                    "prize_quota": prize,
                    "winner_count": winners,
                    "created_by": str(interaction.user.id)
                },
                headers={"X-Admin-Secret": os.getenv("ADMIN_PASSWORD", "")}
            )
            data = resp.json()
            
            if data.get("success"):
                lottery_id = data.get("lottery_id")
                usd = prize / 500000
                
                embed = discord.Embed(
                    title=f"🎁 {title}",
                    description=f"点击下方按钮参与抽奖！\n\n**奖品**: {prize} 额度 (约 ${usd:.2f})\n**中奖人数**: {winners} 人",
                    color=discord.Color.purple()
                )
                embed.set_footer(text=f"抽奖ID: {lottery_id} | 由 {interaction.user.display_name} 发起")
                
                view = LotteryView(self.bot, lottery_id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(f"❌ 创建失败: {data.get('error')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 发起抽奖失败: {e}", ephemeral=True)
    
    @app_commands.command(name="发红包", description="【管理员】发一个公开红包")
    @app_commands.describe(
        total="总额度(NewAPI单位，1美元=500000)",
        count="红包个数",
        random="是否拼手气(随机金额)"
    )
    async def publish_redpacket(
        self, 
        interaction: discord.Interaction, 
        total: int = 500000,
        count: int = 10,
        random: bool = True
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 只有管理员可以发红包", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/redpacket",
                json={
                    "bot_id": BOT_ID,
                    "total_quota": total,
                    "total_count": count,
                    "is_random": random,
                    "created_by": str(interaction.user.id)
                },
                headers={"X-Admin-Secret": os.getenv("ADMIN_PASSWORD", "")}
            )
            data = resp.json()
            
            if data.get("success"):
                rp_id = data.get("red_packet_id")
                usd = total / 500000
                rtype = "🎲 拼手气红包" if random else "💰 普通红包"
                
                embed = discord.Embed(
                    title=f"🧧 {rtype}",
                    description=f"点击下方按钮领取红包！\n\n**总额度**: {total} (约 ${usd:.2f})\n**红包个数**: {count} 个",
                    color=discord.Color.red()
                )
                embed.set_footer(text=f"红包ID: {rp_id} | 由 {interaction.user.display_name} 发放")
                
                view = RedPacketView(self.bot, rp_id, count)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(f"❌ 创建失败: {data.get('error')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 发红包失败: {e}", ephemeral=True)
    
    @app_commands.command(name="开奖", description="【管理员】对指定抽奖进行开奖")
    @app_commands.describe(lottery_id="抽奖活动ID")
    async def draw_lottery(self, interaction: discord.Interaction, lottery_id: int):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 只有管理员可以开奖", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/lottery/{lottery_id}/draw",
                headers={"X-Admin-Secret": os.getenv("ADMIN_PASSWORD", "")}
            )
            data = resp.json()
            
            if data.get("success"):
                winners = data.get("winners", [])
                if winners:
                    winner_mentions = ", ".join([f"<@{w['discord_id']}>" for w in winners])
                    embed = discord.Embed(
                        title="🎉 开奖结果",
                        description=f"恭喜以下用户中奖！\n\n{winner_mentions}\n\n每人获得 **{data.get('prize_per_winner', 0)}** 额度！",
                        color=discord.Color.gold()
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send("⚠️ 没有人参与抽奖")
            else:
                await interaction.followup.send(f"❌ 开奖失败: {data.get('error')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 开奖失败: {e}", ephemeral=True)


# ========== 按钮交互视图 ==========
class LotteryView(discord.ui.View):
    def __init__(self, bot, lottery_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.lottery_id = lottery_id
    
    @discord.ui.button(label="🎁 参与抽奖", style=discord.ButtonStyle.primary, custom_id="join_lottery")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/lottery/join",
                json={
                    "bot_id": BOT_ID,
                    "lottery_id": self.lottery_id,
                    "discord_id": str(interaction.user.id),
                    "discord_username": interaction.user.display_name
                }
            )
            data = resp.json()
            if data.get("success"):
                await interaction.followup.send(f"✅ 参与成功！当前已有 **{data.get('participant_count', '?')}** 人参与", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {data.get('error', '参与失败')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 参与失败: {e}", ephemeral=True)


class RedPacketView(discord.ui.View):
    def __init__(self, bot, rp_id: int, total_count: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.rp_id = rp_id
        self.total_count = total_count
        self.claimed_count = 0
    
    @discord.ui.button(label="🧧 领取红包", style=discord.ButtonStyle.danger, custom_id="claim_redpacket")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            resp = await self.bot.http_client.post(
                f"{BACKEND_URL}/api/public/redpacket/claim",
                json={
                    "bot_id": BOT_ID,
                    "red_packet_id": self.rp_id,
                    "discord_id": str(interaction.user.id),
                    "discord_username": interaction.user.display_name
                }
            )
            data = resp.json()
            if data.get("success"):
                quota = data.get("quota", 0)
                usd = quota / 500000
                remaining = data.get("remaining_count", 0)
                await interaction.followup.send(f"🎉 恭喜领到 **{quota}** 额度 (约 ${usd:.4f})！", ephemeral=True)
                
                # 更新按钮显示
                if remaining == 0:
                    button.label = "🧧 已领完"
                    button.disabled = True
                    await interaction.message.edit(view=self)
            else:
                await interaction.followup.send(f"❌ {data.get('error', '领取失败')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 领取失败: {e}", ephemeral=True)
