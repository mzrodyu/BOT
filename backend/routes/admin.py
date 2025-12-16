from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
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
    UserService, MemoryService, ConfigService, KnowledgeService, LLMPoolService
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


@router.delete("/sensitive-words/clear")
async def clear_all_sensitive_words(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    from database.models import SensitiveWord
    await db.execute(delete(SensitiveWord))
    await db.commit()
    return {"success": True}


@router.post("/sensitive-words/batch")
async def batch_add_sensitive_words(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量添加敏感词"""
    from database.models import SensitiveWord
    from sqlalchemy import select
    
    words = request.get("words", [])
    category = request.get("category", "导入")
    
    # 获取已存在的词
    result = await db.execute(select(SensitiveWord.word))
    existing = set(w.lower() for w in result.scalars().all())
    
    # 批量添加新词
    added = 0
    for word in words:
        if word.lower() not in existing:
            db.add(SensitiveWord(word=word, category=category))
            existing.add(word.lower())
            added += 1
    
    await db.commit()
    return {"success": True, "added": added, "total": len(words)}


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


@router.get("/sensitive-words")
async def get_sensitive_words(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """获取敏感词列表（带分页）"""
    service = ContentFilter(db)
    items = await service.get_words_paginated(skip, limit)
    total = await service.get_total_count()
    return {
        "items": [
            {
                "id": w.id,
                "word": w.word,
                "category": w.category,
                "is_active": w.is_active,
                "created_at": w.created_at.isoformat() if w.created_at else None
            }
            for w in items
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.put("/sensitive-words/batch-category")
async def batch_update_category(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量更新敏感词分类"""
    word_ids = request.get("ids", [])
    category = request.get("category", "")
    if not word_ids:
        raise HTTPException(status_code=400, detail="请选择敏感词")
    if not category:
        raise HTTPException(status_code=400, detail="请输入分类名称")
    
    service = ContentFilter(db)
    count = await service.batch_update_category(word_ids, category)
    return {"success": True, "updated": count}


@router.post("/sensitive-words/batch-delete")
async def batch_delete_sensitive_words(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量删除敏感词"""
    word_ids = request.get("ids", [])
    if not word_ids:
        raise HTTPException(status_code=400, detail="请选择敏感词")
    
    service = ContentFilter(db)
    count = await service.batch_delete(word_ids)
    return {"success": True, "deleted": count}


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


@router.put("/memories/{user_id}")
async def update_memory(
    user_id: int,
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    memory_service = MemoryService(db)
    memory = await memory_service.update_memory(user_id, request.get("summary", ""))
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True}


@router.delete("/memories/{user_id}")
async def delete_memory(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    memory_service = MemoryService(db)
    success = await memory_service.delete_memory(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True}


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
        is_active=request.is_active,
        admin_ids=request.admin_ids,
        chat_mode=request.chat_mode
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
        model=request.model,
        stream=request.stream
    )
    return {"success": True}


# Bot频道列表缓存（内存存储）
_bot_channels_cache = {}


@router.post("/bot-channels")
async def report_bot_channels(
    request: dict,
    _: bool = Depends(verify_admin)
):
    """接收Bot上报的频道列表"""
    bot_id = request.get("bot_id")
    guilds = request.get("guilds", [])
    _bot_channels_cache[bot_id] = guilds
    return {"success": True, "count": sum(len(g.get("channels", [])) for g in guilds)}


@router.get("/bot-channels/{bot_id}")
async def get_bot_channels(
    bot_id: str,
    _: bool = Depends(verify_admin)
):
    """获取Bot上报的频道列表"""
    return _bot_channels_cache.get(bot_id, [])


@router.get("/embedding-config")
async def get_embedding_config(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """获取向量化服务配置"""
    service = ConfigService(db)
    base_url = await service.get_system_config("embedding_base_url")
    api_key = await service.get_system_config("embedding_api_key")
    model = await service.get_system_config("embedding_model")
    
    return {
        "base_url": base_url or "",
        "api_key": api_key or "",
        "model": model or "BAAI/bge-m3"
    }


@router.put("/embedding-config")
async def update_embedding_config(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """更新向量化服务配置"""
    service = ConfigService(db)
    
    if "base_url" in request:
        await service.set_system_config("embedding_base_url", request["base_url"], "向量化API地址")
    if "api_key" in request:
        await service.set_system_config("embedding_api_key", request["api_key"], "向量化API密钥")
    if "model" in request:
        await service.set_system_config("embedding_model", request["model"], "向量化模型名称")
    
    return {"success": True}


@router.post("/embedding-config/test")
async def test_embedding_connection(
    request: dict,
    _: bool = Depends(verify_admin)
):
    """测试向量化服务连接"""
    import httpx
    
    base_url = request.get("base_url", "").rstrip("/")
    api_key = request.get("api_key", "")
    model = request.get("model", "")
    
    if not base_url or not api_key or not model:
        return {"success": False, "message": "请填写完整的API地址、密钥和模型名称"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "input": "测试连接"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    return {"success": True, "message": f"连接成功，向量维度: {len(data['data'][0].get('embedding', []))}"}
                return {"success": True, "message": "连接成功"}
            else:
                return {"success": False, "message": f"API返回错误: {response.status_code} - {response.text[:200]}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


@router.get("/llm-models")
async def get_llm_models(
    base_url: str = None,
    api_key: str = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """从LLM API获取可用模型列表，支持传入临时配置或使用已保存配置"""
    import httpx
    
    # 如果没有传入参数，使用已保存的配置
    if not base_url or not api_key:
        service = ConfigService(db)
        config = await service.get_llm_config()
        base_url = base_url or config.get("base_url", "")
        api_key = api_key or config.get("api_key", "")
    
    base_url = base_url.rstrip("/") if base_url else ""
    
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="请先填写API地址和密钥")
    
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


# Knowledge Base Routes
@router.post("/knowledge/rebuild-embeddings")
async def rebuild_knowledge_embeddings(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """重建所有知识库条目的向量"""
    try:
        service = KnowledgeService(db)
        count = await service.rebuild_embeddings()
        return {"success": True, "rebuilt": count}
    except Exception as e:
        import traceback
        print(f"[Admin] Rebuild embeddings error: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge")
async def get_knowledge_list(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """获取知识库列表（带分页）"""
    service = KnowledgeService(db)
    items = await service.get_all(skip, limit)
    total = await service.get_total_count()
    return {
        "items": [
            {
                "id": kb.id,
                "title": kb.title,
                "content": kb.content[:200] + "..." if len(kb.content) > 200 else kb.content,
                "keywords": kb.keywords,
                "category": kb.category,
                "has_embedding": kb.embedding is not None,
                "is_active": kb.is_active,
                "created_at": kb.created_at.isoformat() if kb.created_at else None
            }
            for kb in items
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/knowledge")
async def create_knowledge(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """创建知识库条目"""
    service = KnowledgeService(db)
    kb = await service.create(
        title=request.get("title", ""),
        content=request.get("content", ""),
        keywords=request.get("keywords"),
        category=request.get("category"),
        auto_embed=request.get("auto_embed", True)
    )
    return {"success": True, "id": kb.id}


@router.delete("/knowledge/{kb_id}")
async def delete_knowledge(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """删除知识库条目"""
    service = KnowledgeService(db)
    success = await service.delete(kb_id)
    if not success:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return {"success": True}


@router.put("/knowledge/batch-category")
async def batch_update_knowledge_category(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量更新知识库分类"""
    kb_ids = request.get("ids", [])
    category = request.get("category", "")
    if not kb_ids:
        raise HTTPException(status_code=400, detail="请选择知识条目")
    if not category:
        raise HTTPException(status_code=400, detail="请输入分类名称")
    
    service = KnowledgeService(db)
    count = await service.batch_update_category(kb_ids, category)
    return {"success": True, "updated": count}


@router.post("/knowledge/batch-delete")
async def batch_delete_knowledge(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量删除知识库条目"""
    kb_ids = request.get("ids", [])
    if not kb_ids:
        raise HTTPException(status_code=400, detail="请选择知识条目")
    
    service = KnowledgeService(db)
    count = await service.batch_delete(kb_ids)
    return {"success": True, "deleted": count}


@router.put("/knowledge/batch-active")
async def batch_toggle_knowledge_active(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """批量启用/禁用知识库条目"""
    kb_ids = request.get("ids", [])
    is_active = request.get("is_active", True)
    if not kb_ids:
        raise HTTPException(status_code=400, detail="请选择知识条目")
    
    service = KnowledgeService(db)
    count = await service.batch_toggle_active(kb_ids, is_active)
    return {"success": True, "updated": count}


# LLM Pool Routes (多模型轮流负载均衡)
@router.get("/llm-pool")
async def get_llm_pool(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """获取模型池列表"""
    pool = await LLMPoolService.get_instance()
    if not pool.loaded:
        await pool.load_from_db(db)
    
    # 返回时隐藏API Key的中间部分
    models = []
    for i, m in enumerate(pool.get_pool()):
        key = m.get("api_key", "")
        masked_key = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        models.append({
            "index": i,
            "name": m.get("name", ""),
            "base_url": m.get("base_url", ""),
            "api_key": masked_key,
            "model": m.get("model", ""),
            "enabled": m.get("enabled", True)
        })
    return {"models": models, "enabled_count": len(pool.get_enabled_models())}


@router.post("/llm-pool/test")
async def test_llm_connection(
    request: dict,
    _: bool = Depends(verify_admin)
):
    """测试LLM API连接"""
    import httpx
    base_url = request.get("base_url", "").rstrip("/")
    api_key = request.get("api_key", "")
    model = request.get("model", "")
    
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="缺少API地址或密钥")
    
    try:
        # 发送一个简单的测试请求
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )
            
            if resp.status_code == 200:
                return {"success": True, "message": "连接成功"}
            else:
                error_text = resp.text[:200]
                return {"success": False, "message": f"HTTP {resp.status_code}: {error_text}"}
    except httpx.TimeoutException:
        return {"success": False, "message": "连接超时"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/llm-pool")
async def add_llm_to_pool(
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """添加模型到池"""
    pool = await LLMPoolService.get_instance()
    if not pool.loaded:
        await pool.load_from_db(db)
    
    pool.add_model(
        base_url=request.get("base_url", ""),
        api_key=request.get("api_key", ""),
        model=request.get("model", ""),
        name=request.get("name")
    )
    await pool.save_to_db(db)
    return {"success": True, "count": len(pool.get_pool())}


@router.delete("/llm-pool/{index}")
async def remove_llm_from_pool(
    index: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """从池中移除模型"""
    pool = await LLMPoolService.get_instance()
    if not pool.loaded:
        await pool.load_from_db(db)
    
    success = pool.remove_model(index)
    if not success:
        raise HTTPException(status_code=404, detail="Model not found")
    
    await pool.save_to_db(db)
    return {"success": True}


@router.post("/llm-pool/{index}/test")
async def test_existing_model(
    index: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """测试已添加模型的连接"""
    import httpx
    pool = await LLMPoolService.get_instance()
    if not pool.loaded:
        await pool.load_from_db(db)
    
    models = pool.get_pool()
    if index < 0 or index >= len(models):
        raise HTTPException(status_code=404, detail="Model not found")
    
    m = models[index]
    base_url = m.get("base_url", "").rstrip("/")
    api_key = m.get("api_key", "")
    model = m.get("model", "")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5
                }
            )
            
            if resp.status_code == 200:
                return {"success": True, "message": "连接成功"}
            else:
                error_text = resp.text[:200]
                return {"success": False, "message": f"HTTP {resp.status_code}: {error_text}"}
    except httpx.TimeoutException:
        return {"success": False, "message": "连接超时"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.put("/llm-pool/{index}/toggle")
async def toggle_llm_in_pool(
    index: int,
    request: dict,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """启用/禁用池中的模型"""
    pool = await LLMPoolService.get_instance()
    if not pool.loaded:
        await pool.load_from_db(db)
    
    enabled = request.get("enabled", True)
    success = pool.toggle_model(index, enabled)
    if not success:
        raise HTTPException(status_code=404, detail="Model not found")
    
    await pool.save_to_db(db)
    return {"success": True}
