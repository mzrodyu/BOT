from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from config import get_settings
from .user_service import UserService
from .memory_service import MemoryService
from .knowledge_service import KnowledgeService
from .blacklist_service import BlacklistService
from .content_filter import ContentFilter
from .config_service import ConfigService
from .llm_pool_service import LLMPoolService
from typing import List, Dict, AsyncGenerator, Optional

settings = get_settings()

DEFAULT_SYSTEM_PROMPT = """你是一个友好的AI助手。请根据后台配置的人设来回复用户。"""


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
    
    async def get_client_and_model(self) -> tuple[AsyncOpenAI, str, str]:
        """获取LLM客户端和模型（支持模型池轮流，主API也参与）
        返回: (client, model_name, source_name)
        """
        pool = await LLMPoolService.get_instance()
        if not pool.loaded:
            await pool.load_from_db(self.db)
        
        # 获取主API配置
        llm_config = await self.config_service.get_llm_config()
        
        # 构建完整的模型列表（模型池 + 主API）
        all_models = []
        
        # 添加模型池中启用的模型
        for m in pool.get_enabled_models():
            all_models.append({
                "base_url": m["base_url"],
                "api_key": m["api_key"],
                "model": m["model"],
                "name": m.get("name", "pool")
            })
        
        # 添加主API（如果配置了的话）
        if llm_config.get("base_url") and llm_config.get("api_key"):
            all_models.append({
                "base_url": llm_config["base_url"],
                "api_key": llm_config["api_key"],
                "model": llm_config["model"],
                "name": "主API"
            })
        
        if not all_models:
            raise ValueError("没有可用的模型配置")
        
        # 轮流选择
        config = pool.get_next_from_list(all_models)
        client = AsyncOpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"]
        )
        source = f"{config.get('name', 'unknown')}({config['base_url']})"
        return client, config["model"], source
    
    async def get_client(self) -> AsyncOpenAI:
        """获取LLM客户端（兼容旧代码）"""
        client, _, _ = await self.get_client_and_model()
        return client
    
    async def get_model(self) -> str:
        """获取模型名称（兼容旧代码）"""
        _, model, _ = await self.get_client_and_model()
        return model
    
    async def get_chat_mode(self) -> str:
        """获取对话模式"""
        config = await self.config_service.get_bot_config(self.bot_id)
        if config and hasattr(config, 'chat_mode') and config.chat_mode:
            return config.chat_mode
        return "chat"
    
    async def is_stream_enabled(self) -> bool:
        """获取是否启用流式传输"""
        llm_config = await self.config_service.get_llm_config()
        return llm_config.get("stream", True)
    
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
        guild_emojis: str = None,
        chat_mode: str = "chat"
    ) -> List[Dict]:
        messages = []
        
        system_content = await self.get_system_prompt()
        
        # 根据聊天模式添加不同提示
        if chat_mode == "qa":
            system_content += "\n\n【答疑模式】请只关注当前问题，不要参考之前的对话历史。"
        elif chat_mode == "single":
            system_content += "\n\n【单用户聊天】只与当前用户对话，历史消息都是同一个用户的。"
        else:
            # multi模式
            system_content += "\n\n【多用户聊天】当前频道有多人对话，每条消息前有[用户名]标记。请注意区分不同用户，针对@你或回复你的用户进行回复，不要混淆不同用户的对话。"
        
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
        
        # 根据模式加载上下文
        if chat_mode == "qa":
            # 答疑模式不加载上下文
            pass
        elif chat_mode == "single":
            # 单用户模式：只加载Bot的回复和当前用户的消息
            for msg in context_messages:
                # assistant消息（Bot回复）始终加载
                # user消息只加载没有用户名标记的（当前用户）
                if msg["role"] == "assistant":
                    messages.append({"role": msg["role"], "content": msg["content"]})
                elif msg["role"] == "user" and not msg["content"].startswith("["):
                    # 没有[用户名]标记的是当前用户
                    messages.append({"role": msg["role"], "content": msg["content"]})
        else:
            # 多用户模式：加载所有上下文
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
        
        chat_mode = await self.get_chat_mode()
        
        messages = await self.build_messages(
            user_message=message,
            context_messages=context_messages or [],
            pinned_messages=pinned_messages or [],
            reply_content=reply_content,
            user_memory=user_memory,
            knowledge_results=knowledge_texts,
            image_urls=image_urls or [],
            guild_emojis=guild_emojis,
            chat_mode=chat_mode
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
            print(f"[ContentFilter] Blocked: {filter_reason}, message: {message[:50]}...")
            yield f"[BLOCKED]{filter_reason}"
            return
        
        user = await self.user_service.get_or_create_user(discord_id, username)
        
        memory = await self.memory_service.get_user_memory(user.id)
        user_memory = memory.summary if memory else None
        
        kb_results = await self.knowledge_service.search(message)
        knowledge_texts = [f"【{kb.title}】\n{kb.content}" for kb in kb_results]
        
        chat_mode = await self.get_chat_mode()
        
        messages = await self.build_messages(
            user_message=message,
            context_messages=context_messages or [],
            pinned_messages=pinned_messages or [],
            reply_content=reply_content,
            user_memory=user_memory,
            knowledge_results=knowledge_texts,
            image_urls=image_urls or [],
            guild_emojis=guild_emojis,
            chat_mode=chat_mode
        )
        
        # 支持失败重试下一个模型
        max_retries = 3
        last_error = None
        
        for retry in range(max_retries):
            try:
                client, model, source = await self.get_client_and_model()
                full_response = ""
                
                # 获取流式开关（跟随主API设置）
                stream_enabled = await self.is_stream_enabled()
                
                print(f"[ChatService] Attempt {retry+1}: Using model: {model} from {source}, mode: {chat_mode}, stream: {stream_enabled}")
                print(f"[ChatService] Messages count: {len(messages)}")
                
                # 构建请求参数
                request_params = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 16000,
                    "stream": stream_enabled
                }
                
                # thinking模型通过extra_body传递特殊参数
                if "thinking" in model.lower():
                    request_params["extra_body"] = {
                        "thinking": {
                            "type": "enabled",
                            "budget_tokens": 10000
                        }
                    }
                
                response = await client.chat.completions.create(**request_params)
                
                input_tokens = 0
                output_tokens = 0
                
                if stream_enabled:
                    # 流式响应
                    async for chunk in response:
                        if hasattr(chunk, 'usage') and chunk.usage:
                            if hasattr(chunk.usage, 'prompt_tokens'):
                                input_tokens = chunk.usage.prompt_tokens
                            if hasattr(chunk.usage, 'completion_tokens'):
                                output_tokens = chunk.usage.completion_tokens
                        
                        if chunk.choices and len(chunk.choices) > 0:
                            choice = chunk.choices[0]
                            delta = getattr(choice, 'delta', None)
                            content = None
                            
                            if delta:
                                content = getattr(delta, 'content', None)
                                if not content:
                                    content = getattr(delta, 'text', None)
                            
                            if not content:
                                content = getattr(choice, 'text', None)
                            
                            if not content and hasattr(choice, 'message'):
                                msg = choice.message
                                content = getattr(msg, 'content', None)
                            
                            if content:
                                full_response += content
                                yield content
                else:
                    # 非流式响应
                    if hasattr(response, 'usage') and response.usage:
                        input_tokens = getattr(response.usage, 'prompt_tokens', 0)
                        output_tokens = getattr(response.usage, 'completion_tokens', 0)
                    
                    if response.choices and len(response.choices) > 0:
                        content = response.choices[0].message.content
                        if content:
                            full_response = content
                            yield content
                
                # 发送统计信息
                yield f"[STATS]{input_tokens}|{output_tokens}"
                
                print(f"[ChatService] Full response length: {len(full_response)}")
                if full_response:
                    await self.memory_service.save_conversation(user.id, channel_id, "user", message)
                    await self.memory_service.save_conversation(user.id, channel_id, "assistant", full_response)
                
                # 成功，退出重试循环
                return
                
            except Exception as e:
                import traceback
                last_error = str(e)
                print(f"[ChatService] Attempt {retry+1} failed: {last_error}")
                print(f"[ChatService] Traceback: {traceback.format_exc()}")
                
                # 如果还有重试机会，继续尝试下一个模型
                if retry < max_retries - 1:
                    print(f"[ChatService] Retrying with next model...")
                    continue
        
        # 所有重试都失败
        yield f"[ERROR]{last_error}"
