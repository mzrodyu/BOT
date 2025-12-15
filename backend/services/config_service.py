from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import BotConfig, SystemConfig
from typing import Optional, Dict, Any

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


class ConfigService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============ 通用配置 (SystemConfig) ============
    
    async def get_system_config(self, key: str) -> Optional[str]:
        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        return config.value if config else None
    
    async def set_system_config(self, key: str, value: str, description: str = None):
        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        
        if config:
            config.value = value
            if description:
                config.description = description
        else:
            config = SystemConfig(key=key, value=value, description=description)
            self.db.add(config)
        
        await self.db.commit()
        return config
    
    async def get_llm_config(self) -> Dict[str, Any]:
        """获取通用LLM配置"""
        base_url = await self.get_system_config("llm_base_url")
        api_key = await self.get_system_config("llm_api_key")
        model = await self.get_system_config("llm_model")
        stream = await self.get_system_config("llm_stream")
        
        from config import get_settings
        settings = get_settings()
        
        return {
            "base_url": base_url or settings.llm_base_url,
            "api_key": api_key or settings.llm_api_key,
            "model": model or settings.llm_model,
            "stream": stream != "false"  # 默认为True
        }
    
    async def set_llm_config(self, base_url: str = None, api_key: str = None, model: str = None, stream: bool = None):
        """设置通用LLM配置"""
        if base_url is not None:
            await self.set_system_config("llm_base_url", base_url, "LLM API地址")
        if api_key is not None:
            await self.set_system_config("llm_api_key", api_key, "LLM API密钥")
        if model is not None:
            await self.set_system_config("llm_model", model, "LLM模型名称")
        if stream is not None:
            await self.set_system_config("llm_stream", str(stream).lower(), "是否启用流式传输")
    
    # ============ Bot独立配置 (BotConfig) ============
    
    async def get_bot_config(self, bot_id: str) -> Optional[BotConfig]:
        result = await self.db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        return result.scalar_one_or_none()
    
    async def get_or_create_bot_config(self, bot_id: str) -> BotConfig:
        config = await self.get_bot_config(bot_id)
        if not config:
            config = BotConfig(
                bot_id=bot_id,
                bot_name="CatieBot",
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                context_limit=10
            )
            self.db.add(config)
            await self.db.commit()
            await self.db.refresh(config)
        return config
    
    async def update_bot_config(
        self, 
        bot_id: str,
        bot_name: str = None,
        system_prompt: str = None,
        context_limit: int = None,
        is_active: bool = None,
        admin_ids: str = None,
        chat_mode: str = None
    ) -> BotConfig:
        config = await self.get_or_create_bot_config(bot_id)
        
        if bot_name is not None:
            config.bot_name = bot_name
        if system_prompt is not None:
            config.system_prompt = system_prompt
        if context_limit is not None:
            config.context_limit = context_limit
        if is_active is not None:
            config.is_active = is_active
        if admin_ids is not None:
            config.admin_ids = admin_ids
        if chat_mode is not None:
            config.chat_mode = chat_mode
        
        await self.db.commit()
        await self.db.refresh(config)
        return config
    
    async def get_all_bot_configs(self):
        result = await self.db.execute(select(BotConfig))
        return result.scalars().all()
    
    async def delete_bot_config(self, bot_id: str) -> bool:
        config = await self.get_bot_config(bot_id)
        if not config:
            return False
        await self.db.delete(config)
        await self.db.commit()
        return True
