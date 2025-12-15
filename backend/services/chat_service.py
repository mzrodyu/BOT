from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from config import get_settings
from .user_service import UserService
from .memory_service import MemoryService
from .knowledge_service import KnowledgeService
from .blacklist_service import BlacklistService
from .content_filter import ContentFilter
from .config_service import ConfigService
from typing import List, Dict, AsyncGenerator, Optional

settings = get_settings()

DEFAULT_SYSTEM_PROMPT = """你是 CatieBot，一个友好、有趣的AI助手。

性格特点：
- 友善、热情、乐于助人
- 有时会用一些可爱的语气词
- 善于倾听和理解用户需求

行为准则：
- 永远保持礼貌和尊重
- 不生成有害、违法或不适当的内容
- 如果不确定，诚实地表达不确定性
- 可以使用服务器表情来增加表达力"""


class ChatService:
    def __init__(self, db: AsyncSession, bot_id: str = "default"):
        self.db = db
        self.bot_id = bot_id
        self.user_service = UserService(db)
        self.memory_service = MemoryService(db)
        self.knowledge_service = KnowledgeService(db)
        self.blacklist_service = BlacklistService(db)
        self.content_filter = ContentFilter(db)
        self.config_service = ConfigService(db)
        self._client = None
        self._llm_config = None
    
    async def get_client(self) -> AsyncOpenAI:
        """获取LLM客户端（使用数据库中的配置）"""
        llm_config = await self.config_service.get_llm_config()
        return AsyncOpenAI(
            base_url=llm_config["base_url"],
            api_key=llm_config["api_key"]
        )
    
    async def get_model(self) -> str:
        """获取模型名称"""
        llm_config = await self.config_service.get_llm_config()
        return llm_config["model"]
    
    async def get_system_prompt(self) -> str:
        """获取Bot的系统提示词"""
        bot_config = await self.config_service.get_bot_config(self.bot_id)
        if bot_config and bot_config.system_prompt:
            return bot_config.system_prompt
        return DEFAULT_SYSTEM_PROMPT
    
    async def check_user_allowed(self, discord_id: str) -> tuple[bool, Optional[str]]:
        is_banned, reason = await self.blacklist_service.is_banned(discord_id)
        if is_banned:
            return False, reason or "您已被禁止使用此服务"
        return True, None
    
    async def build_messages(
        self,
        user_message: str,
        context_messages: List[Dict],
        pinned_messages: List[str],
        reply_content: str,
        user_memory: str,
        knowledge_results: List[str],
        image_urls: List[str],
        guild_emojis: str = None
    ) -> List[Dict]:
        messages = []
        
        system_content = await self.get_system_prompt()
        
        if user_memory:
            system_content += f"\n\n关于当前用户的记忆：\n{user_memory}"
        
        if knowledge_results:
            kb_text = "\n---\n".join(knowledge_results)
            system_content += f"\n\n相关知识参考：\n{kb_text}"
        
        if pinned_messages:
            pinned_text = "\n".join(pinned_messages)
            system_content += f"\n\n频道置顶/标注消息（可用作答疑参考）：\n{pinned_text}"
        
        if guild_emojis:
            system_content += f"\n\n{guild_emojis}\n你可以在回复中使用这些表情，格式如 :表情名:"
        
        messages.append({"role": "system", "content": system_content})
        
        for msg in context_messages:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        if reply_content:
            user_message = f"[回复消息: {reply_content}]\n{user_message}"
        
        if image_urls:
            content = [{"type": "text", "text": user_message}]
            for url in image_urls:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})
        
        return messages
    
    async def chat(
        self,
        discord_id: str,
        username: str,
        channel_id: str,
        message: str,
        context_messages: List[Dict] = None,
        pinned_messages: List[str] = None,
        reply_content: str = None,
        image_urls: List[str] = None,
        guild_emojis: str = None
    ) -> Dict:
        allowed, block_reason = await self.check_user_allowed(discord_id)
        if not allowed:
            return {
                "success": False,
                "is_blocked": True,
                "block_reason": block_reason
            }
        
        is_safe, filter_reason = await self.content_filter.check_content(message)
        if not is_safe:
            return {
                "success": False,
                "is_blocked": True,
                "block_reason": filter_reason
            }
        
        user = await self.user_service.get_or_create_user(discord_id, username)
        
        memory = await self.memory_service.get_user_memory(user.id)
        user_memory = memory.summary if memory else None
        
        kb_results = await self.knowledge_service.search(message)
        knowledge_texts = [f"【{kb.title}】\n{kb.content}" for kb in kb_results]
        
        messages = await self.build_messages(
            user_message=message,
            context_messages=context_messages or [],
            pinned_messages=pinned_messages or [],
            reply_content=reply_content,
            user_memory=user_memory,
            knowledge_results=knowledge_texts,
            image_urls=image_urls or [],
            guild_emojis=guild_emojis
        )
        
        try:
            client = await self.get_client()
            model = await self.get_model()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096
            )
            
            assistant_message = response.choices[0].message.content
            
            await self.memory_service.save_conversation(user.id, channel_id, "user", message)
            await self.memory_service.save_conversation(user.id, channel_id, "assistant", assistant_message)
            
            return {
                "success": True,
                "response": assistant_message
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def chat_stream(
        self,
        discord_id: str,
        username: str,
        channel_id: str,
        message: str,
        context_messages: List[Dict] = None,
        pinned_messages: List[str] = None,
        reply_content: str = None,
        image_urls: List[str] = None,
        guild_emojis: str = None
    ) -> AsyncGenerator[str, None]:
        allowed, block_reason = await self.check_user_allowed(discord_id)
        if not allowed:
            yield f"[BLOCKED]{block_reason}"
            return
        
        is_safe, filter_reason = await self.content_filter.check_content(message)
        if not is_safe:
            yield f"[BLOCKED]{filter_reason}"
            return
        
        user = await self.user_service.get_or_create_user(discord_id, username)
        
        memory = await self.memory_service.get_user_memory(user.id)
        user_memory = memory.summary if memory else None
        
        kb_results = await self.knowledge_service.search(message)
        knowledge_texts = [f"【{kb.title}】\n{kb.content}" for kb in kb_results]
        
        messages = await self.build_messages(
            user_message=message,
            context_messages=context_messages or [],
            pinned_messages=pinned_messages or [],
            reply_content=reply_content,
            user_memory=user_memory,
            knowledge_results=knowledge_texts,
            image_urls=image_urls or [],
            guild_emojis=guild_emojis
        )
        
        try:
            client = await self.get_client()
            model = await self.get_model()
            full_response = ""
            
            print(f"[ChatService] Using model: {model}")
            print(f"[ChatService] Messages count: {len(messages)}")
            
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        content = delta.content
                        full_response += content
                        yield content
                    # 处理思考模型的reasoning内容
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        pass  # 跳过reasoning，只输出content
            
            print(f"[ChatService] Full response length: {len(full_response)}")
            if full_response:
                await self.memory_service.save_conversation(user.id, channel_id, "user", message)
                await self.memory_service.save_conversation(user.id, channel_id, "assistant", full_response)
            
        except Exception as e:
            import traceback
            print(f"[ChatService] Error: {str(e)}")
            print(f"[ChatService] Traceback: {traceback.format_exc()}")
            yield f"[ERROR]{str(e)}"
