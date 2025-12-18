from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from backend.services.public_api_service import PublicAPIService
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/api/public", tags=["公益站"])

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


class RegisterRequest(BaseModel):
    bot_id: str
    discord_id: str
    discord_username: str


class ConfigRequest(BaseModel):
    bot_id: str
    name: Optional[str] = "公益站"
    newapi_url: str
    newapi_token: str
    default_quota: Optional[int] = 100000
    default_group: Optional[str] = "default"


@router.post("/register")
async def register_user(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """用户注册公益站"""
    service = PublicAPIService(db, req.bot_id)
    result = await service.register_user(req.discord_id, req.discord_username)
    return result


@router.get("/usage/{bot_id}/{discord_id}")
async def get_usage(
    bot_id: str,
    discord_id: str,
    db: AsyncSession = Depends(get_db)
):
    """查询用户用量"""
    service = PublicAPIService(db, bot_id)
    result = await service.get_user_usage(discord_id)
    return result


@router.get("/check/{bot_id}/{discord_id}")
async def check_registered(
    bot_id: str,
    discord_id: str,
    db: AsyncSession = Depends(get_db)
):
    """检查用户是否已注册"""
    service = PublicAPIService(db, bot_id)
    is_registered = await service.is_registered(discord_id)
    user = await service.get_user(discord_id) if is_registered else None
    return {
        "registered": is_registered,
        "username": user.newapi_username if user else None,
        "api_key": user.api_key if user else None
    }


@router.post("/config")
async def save_config(
    req: ConfigRequest,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """保存公益站配置（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    from database.models import PublicAPIConfig
    from sqlalchemy import select
    
    # 查找现有配置
    result = await db.execute(
        select(PublicAPIConfig).where(PublicAPIConfig.bot_id == req.bot_id)
    )
    config = result.scalar_one_or_none()
    
    if config:
        config.name = req.name
        config.newapi_url = req.newapi_url
        config.newapi_token = req.newapi_token
        config.default_quota = req.default_quota
        config.default_group = req.default_group
    else:
        config = PublicAPIConfig(
            bot_id=req.bot_id,
            name=req.name,
            newapi_url=req.newapi_url,
            newapi_token=req.newapi_token,
            default_quota=req.default_quota,
            default_group=req.default_group
        )
        db.add(config)
    
    await db.commit()
    return {"success": True}


@router.get("/config/{bot_id}")
async def get_config(
    bot_id: str,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """获取公益站配置（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = PublicAPIService(db, bot_id)
    config = await service.get_config()
    
    if not config:
        return {"configured": False}
    
    return {
        "configured": True,
        "name": config.name,
        "newapi_url": config.newapi_url,
        "default_quota": config.default_quota,
        "default_group": config.default_group
    }
