from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from backend.schemas import ChatRequest, ChatResponse
from backend.services import ChatService
import json

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    service = ChatService(db, bot_id=request.bot_id)
    result = await service.chat(
        discord_id=request.discord_id,
        username=request.username,
        channel_id=request.channel_id,
        message=request.message,
        context_messages=[m.model_dump() for m in request.context_messages],
        pinned_messages=request.pinned_messages,
        reply_content=request.reply_content,
        image_urls=request.image_urls,
        guild_emojis=request.guild_emojis
    )
    return ChatResponse(**result)


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    service = ChatService(db, bot_id=request.bot_id)
    
    # 检查是否启用流式
    stream_enabled = await service.is_stream_enabled()
    
    if not stream_enabled:
        # 非流式模式：直接调用chat方法，但包装成SSE格式返回
        result = await service.chat(
            discord_id=request.discord_id,
            username=request.username,
            channel_id=request.channel_id,
            message=request.message,
            context_messages=[m.model_dump() for m in request.context_messages],
            pinned_messages=request.pinned_messages,
            reply_content=request.reply_content,
            image_urls=request.image_urls,
            guild_emojis=request.guild_emojis
        )
        
        async def generate_non_stream():
            if result.get("success"):
                yield f"data: {json.dumps({'content': result['response']})}\n\n"
                yield f"data: {json.dumps({'content': '[STATS]0|0'})}\n\n"
            elif result.get("is_blocked"):
                block_reason = result.get('block_reason', '被阻止')
                yield f"data: {json.dumps({'content': f'[BLOCKED]{block_reason}'})}\n\n"
            else:
                error_msg = result.get('error', '未知错误')
                yield f"data: {json.dumps({'content': f'[ERROR]{error_msg}'})}\n\n"
        
        return StreamingResponse(
            generate_non_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    
    # 流式模式
    async def generate():
        async for chunk in service.chat_stream(
            discord_id=request.discord_id,
            username=request.username,
            channel_id=request.channel_id,
            message=request.message,
            context_messages=[m.model_dump() for m in request.context_messages],
            pinned_messages=request.pinned_messages,
            reply_content=request.reply_content,
            image_urls=request.image_urls,
            guild_emojis=request.guild_emojis
        ):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )
