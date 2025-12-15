import discord
from discord.ext import commands
from discord import app_commands
import httpx
import json
from config import get_settings
from typing import Optional, List

settings = get_settings()


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
    
    async def setup_hook(self):
        await self.add_cog(MessageHandler(self))
        await self.add_cog(AdminCommands(self))
        await self.tree.sync()
        print(f"Synced slash commands")
    
    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} guilds")
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
                    # 文字频道、论坛、帖子
                    if isinstance(channel, (discord.TextChannel, discord.ForumChannel, discord.Thread)):
                        channel_info = {
                            "channel_id": str(channel.id),
                            "channel_name": channel.name,
                            "type": "text" if isinstance(channel, discord.TextChannel) else 
                                   "forum" if isinstance(channel, discord.ForumChannel) else "thread",
                            "parent_id": str(channel.parent_id) if hasattr(channel, 'parent_id') and channel.parent_id else None
                        }
                        guild_data["channels"].append(channel_info)
                
                channels_data.append(guild_data)
            
            await self.http_client.post(
                f"{settings.backend_url}/api/admin/bot-channels",
                json={
                    "bot_id": settings.bot_id,
                    "guilds": channels_data
                },
                headers={"X-Admin-Secret": settings.admin_password}
            )
            print(f"Reported {sum(len(g['channels']) for g in channels_data)} channels to backend")
        except Exception as e:
            print(f"Error reporting channels: {e}")
    
    async def close(self):
        await self.http_client.aclose()
        await super().close()


class MessageHandler(commands.Cog):
    def __init__(self, bot: CatieBot):
        self.bot = bot
    
    async def is_channel_allowed(self, channel_id: str) -> bool:
        try:
            resp = await self.bot.http_client.get(
                f"{settings.backend_url}/api/admin/channels/check/{settings.bot_id}/{channel_id}"
            )
            data = resp.json()
            return data.get("is_whitelisted", False)
        except Exception as e:
            print(f"Error checking channel: {e}")
            return True
    
    async def should_respond(self, message: discord.Message) -> bool:
        if message.author.bot:
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
            if msg.author.bot and msg.author != self.bot.user:
                continue
            
            role = "assistant" if msg.author == self.bot.user else "user"
            content = msg.content
            if role == "user":
                content = f"[{msg.author.display_name}]: {content}"
            
            messages.append({"role": role, "content": content})
        
        return list(reversed(messages[1:]))
    
    async def get_pinned_messages(self, channel: discord.TextChannel) -> List[str]:
        try:
            pinned = await channel.pins()
            return [f"[{p.author.display_name}]: {p.content}" for p in pinned[:5]]
        except:
            return []
    
    async def get_reply_content(self, message: discord.Message) -> Optional[str]:
        if message.reference and message.reference.resolved:
            ref = message.reference.resolved
            return f"[{ref.author.display_name}]: {ref.content}"
        return None
    
    async def get_image_urls(self, message: discord.Message) -> List[str]:
        urls = []
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                urls.append(attachment.url)
        return urls
    
    def process_content(self, content: str, guild: discord.Guild) -> str:
        content = content.replace(f"<@{self.bot.user.id}>", "").strip()
        content = content.replace(f"<@!{self.bot.user.id}>", "").strip()
        return content
    
    async def send_streaming_response(self, message: discord.Message, request_data: dict):
        reply_msg = await message.reply("思考中...", mention_author=False)
        full_response = ""
        
        try:
            async with self.bot.http_client.stream(
                "POST",
                f"{settings.backend_url}/api/chat/stream",
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
                                
                                full_response += content
                                
                                if len(full_response) % 50 == 0 or len(full_response) < 100:
                                    display = full_response[:1900] + "..." if len(full_response) > 1900 else full_response
                                    await reply_msg.edit(content=display or "...")
                            except json.JSONDecodeError:
                                continue
                
                if full_response:
                    if len(full_response) > 2000:
                        chunks = [full_response[i:i+1990] for i in range(0, len(full_response), 1990)]
                        await reply_msg.edit(content=chunks[0])
                        for chunk in chunks[1:]:
                            await message.channel.send(chunk)
                    else:
                        await reply_msg.edit(content=full_response)
                else:
                    await reply_msg.edit(content="抱歉，我没有生成回复。")
                    
        except Exception as e:
            print(f"Streaming error: {e}")
            await reply_msg.edit(content=f"❌ 发生错误，请稍后再试")
    
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
        
        request_data = {
            "bot_id": settings.bot_id,
            "discord_id": str(message.author.id),
            "username": message.author.display_name,
            "channel_id": str(message.channel.id),
            "message": content,
            "context_messages": context_messages,
            "pinned_messages": pinned_messages,
            "reply_content": reply_content,
            "image_urls": image_urls
        }
        
        async with message.channel.typing():
            await self.send_streaming_response(message, request_data)


DEVELOPER_ID = 1373778569154658426


class AdminCommands(commands.Cog):
    def __init__(self, bot: CatieBot):
        self.bot = bot
    
    async def is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == DEVELOPER_ID:
            return True
        if interaction.user.guild_permissions.administrator:
            return True
        if interaction.user.guild_permissions.manage_guild:
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
                f"{settings.backend_url}/api/admin/blacklist",
                json={
                    "discord_id": str(user.id),
                    "username": user.display_name,
                    "reason": reason,
                    "banned_by": str(interaction.user.id),
                    "is_permanent": duration is None,
                    "duration_minutes": duration
                },
                headers={"X-Admin-Secret": settings.admin_password}
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
                f"{settings.backend_url}/api/admin/blacklist/{user.id}",
                headers={"X-Admin-Secret": settings.admin_password}
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
                f"{settings.backend_url}/api/admin/blacklist",
                headers={"X-Admin-Secret": settings.admin_password}
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
                f"{settings.backend_url}/api/admin/channels",
                json={
                    "bot_id": settings.bot_id,
                    "channel_id": str(interaction.channel_id),
                    "guild_id": str(interaction.guild_id),
                    "channel_name": interaction.channel.name,
                    "added_by": str(interaction.user.id)
                },
                headers={"X-Admin-Secret": settings.admin_password}
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
                f"{settings.backend_url}/api/admin/channels/{settings.bot_id}/{interaction.channel_id}",
                headers={"X-Admin-Secret": settings.admin_password}
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
                f"{settings.backend_url}/api/admin/channels",
                params={"bot_id": settings.bot_id, "guild_id": str(interaction.guild_id)},
                headers={"X-Admin-Secret": settings.admin_password}
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
