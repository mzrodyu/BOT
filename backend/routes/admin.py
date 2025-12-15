from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from backend.schemas import (
    BlacklistCreate, BlacklistResponse,
    ChannelWhitelistCreate, ChannelWhitelistResponse,
    SensitiveWordCreate, SensitiveWordResponse,
    UserResponse, MemoryResponse,
    BotConfigCreate, BotConfigUpdate, BotConfigResponse,
    LLMConfigUpdate, LLMConfigResponse
)
from backend.services import (
    BlacklistService, ChannelService, ContentFilter,
    UserService, MemoryService, ConfigService
)
from config import get_settings
from typing import List

router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()


async def verify_admin(x_admin_secret: str = Header(None)):
    if x_admin_secret != settings.admin_password:
        raise HTTPException(status_code=403, detail="Invalid admin password")
    return True


# Blacklist Routes
@router.post("/blacklist", response_model=BlacklistResponse)
async def ban_user(
    request: BlacklistCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = BlacklistService(db)
    ban = await service.ban_user(
        discord_id=request.discord_id,
        username=request.username,
        reason=request.reason,
        banned_by=request.banned_by,
        is_permanent=request.is_permanent,
        duration_minutes=request.duration_minutes
    )
    return ban


@router.delete("/blacklist/{discord_id}")
async def unban_user(
    discord_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = BlacklistService(db)
    success = await service.unban_user(discord_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found in blacklist")
    return {"success": True}


@router.get("/blacklist", response_model=List[BlacklistResponse])
async def get_blacklist(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = BlacklistService(db)
    return await service.get_all(skip, limit)


@router.get("/blacklist/check/{discord_id}")
async def check_banned(
    discord_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = BlacklistService(db)
    is_banned, reason = await service.is_banned(discord_id)
    return {"is_banned": is_banned, "reason": reason}


# Channel Whitelist Routes
@router.post("/channels", response_model=ChannelWhitelistResponse)
async def add_channel(
    request: ChannelWhitelistCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ChannelService(db)
    return await service.add_channel(
        bot_id=request.bot_id,
        channel_id=request.channel_id,
        guild_id=request.guild_id,
        channel_name=request.channel_name,
        added_by=request.added_by
    )


@router.delete("/channels/{bot_id}/{channel_id}")
async def remove_channel(
    bot_id: str,
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ChannelService(db)
    success = await service.remove_channel(bot_id, channel_id)
    if not success:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"success": True}


@router.get("/channels", response_model=List[ChannelWhitelistResponse])
async def get_channels(
    bot_id: str = None,
    guild_id: str = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ChannelService(db)
    return await service.get_all(bot_id, guild_id, skip, limit)


@router.get("/channels/check/{bot_id}/{channel_id}")
async def check_channel(
    bot_id: str,
    channel_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = ChannelService(db)
    is_whitelisted = await service.is_whitelisted(bot_id, channel_id)
    return {"is_whitelisted": is_whitelisted}


# Sensitive Words Routes
@router.post("/sensitive-words", response_model=SensitiveWordResponse)
async def add_sensitive_word(
    request: SensitiveWordCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ContentFilter(db)
    word = await service.add_sensitive_word(request.word, request.category)
    if not word:
        raise HTTPException(status_code=400, detail="Word already exists")
    return word


@router.delete("/sensitive-words/{word_id}")
async def remove_sensitive_word(
    word_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ContentFilter(db)
    success = await service.remove_sensitive_word(word_id)
    if not success:
        raise HTTPException(status_code=404, detail="Word not found")
    return {"success": True}


@router.get("/sensitive-words", response_model=List[SensitiveWordResponse])
async def get_sensitive_words(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ContentFilter(db)
    return await service.get_all_words()


# Users & Memories Routes
@router.get("/users", response_model=List[UserResponse])
async def get_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = UserService(db)
    return await service.get_all_users(skip, limit)


@router.get("/memories")
async def get_memories(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = MemoryService(db)
    return await service.get_all_memories(skip, limit)


@router.post("/memories/summarize/{discord_id}")
async def summarize_user_memory(
    discord_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    user_service = UserService(db)
    user = await user_service.get_user_by_discord_id(discord_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    memory_service = MemoryService(db)
    memory = await memory_service.summarize_user(user.id)
    if not memory:
        raise HTTPException(status_code=400, detail="No conversations to summarize")
    return {"success": True, "summary": memory.summary}


# Bot Config Routes
@router.get("/bot-config", response_model=List[BotConfigResponse])
async def get_all_bot_configs(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    return await service.get_all_bot_configs()


@router.get("/bot-config/{bot_id}", response_model=BotConfigResponse)
async def get_bot_config(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    config = await service.get_or_create_bot_config(bot_id)
    return config


@router.post("/bot-config", response_model=BotConfigResponse)
async def create_bot_config(
    request: BotConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    return await service.update_bot_config(
        bot_id=request.bot_id,
        bot_name=request.bot_name,
        system_prompt=request.system_prompt,
        context_limit=request.context_limit
    )


@router.put("/bot-config/{bot_id}", response_model=BotConfigResponse)
async def update_bot_config(
    bot_id: str,
    request: BotConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    return await service.update_bot_config(
        bot_id=bot_id,
        bot_name=request.bot_name,
        system_prompt=request.system_prompt,
        context_limit=request.context_limit,
        is_active=request.is_active
    )


@router.delete("/bot-config/{bot_id}")
async def delete_bot_config(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    success = await service.delete_bot_config(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bot config not found")
    return {"success": True}


# LLM Config Routes (通用配置)
@router.get("/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    config = await service.get_llm_config()
    return LLMConfigResponse(**config)


@router.put("/llm-config")
async def update_llm_config(
    request: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    service = ConfigService(db)
    await service.set_llm_config(
        base_url=request.base_url,
        api_key=request.api_key,
        model=request.model
    )
    return {"success": True}


@router.get("/llm-models")
async def get_llm_models(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """从LLM API获取可用模型列表"""
    import httpx
    service = ConfigService(db)
    config = await service.get_llm_config()
    
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key", "")
    
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="请先配置API地址和密钥")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="获取模型列表失败")
            
            data = resp.json()
            models = data.get("data", [])
            return {"models": [m.get("id") for m in models if m.get("id")]}
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"请求失败: {str(e)}")
