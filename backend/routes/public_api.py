from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from backend.services.public_api_service import PublicAPIService
from backend.services.lottery_service import LotteryService, RedPacketService
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
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


class TestConnectionRequest(BaseModel):
    newapi_url: str
    newapi_token: str  # 现在这个字段存储密码


@router.post("/test-connection")
async def test_connection(
    req: TestConnectionRequest,
    x_admin_secret: str = Header(None)
):
    """测试NewAPI连接 - 使用用户名密码登录"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    import httpx
    import re
    try:
        base_url = req.newapi_url.rstrip("/")
        base_url = re.sub(r'/(v1|api)$', '', base_url)
        
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as client:
            # 检查token格式：如果包含:则是 username:password 格式
            if ':' in req.newapi_token:
                username, password = req.newapi_token.split(':', 1)
            else:
                # 兼容旧格式，尝试直接用token
                username, password = None, None
            
            if username and password:
                # 用户名密码登录
                login_resp = await client.post(
                    f"{base_url}/api/user/login",
                    json={"username": username, "password": password}
                )
                
                if login_resp.status_code != 200:
                    return {"success": False, "message": f"登录请求失败: HTTP {login_resp.status_code}"}
                
                login_data = login_resp.json()
                if not login_data.get("success"):
                    return {"success": False, "message": f"登录失败: {login_data.get('message', '未知错误')}"}
                
                # 获取session和用户信息
                session = login_resp.cookies.get("session")
                user_data = login_data.get("data", {})
                user_id = user_data.get("id", 1)
                role = user_data.get("role", 0)
                
                if not session:
                    return {"success": False, "message": "登录成功但未获取到session"}
                
                # 验证session可用
                headers = {"Cookie": f"session={session}", "New-Api-User": str(user_id)}
                resp = await client.get(f"{base_url}/api/user/self", headers=headers)
                
                if resp.status_code == 200 and resp.json().get("success"):
                    role_name = "管理员" if role >= 100 else "普通用户"
                    if role < 100:
                        return {"success": False, "message": f"登录成功但{username}不是管理员，无法创建用户"}
                    return {"success": True, "message": f"连接成功！用户: {username} ({role_name})", "session": session, "user_id": user_id}
                else:
                    return {"success": False, "message": "Session验证失败"}
            else:
                return {"success": False, "message": "请使用 用户名:密码 格式填写Token字段，如 admin:123456"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ========== 抽奖 API ==========
class LotteryRequest(BaseModel):
    bot_id: str
    title: str
    prize_quota: int
    winner_count: int = 1
    description: Optional[str] = None
    end_time: Optional[datetime] = None
    created_by: Optional[str] = None


class JoinLotteryRequest(BaseModel):
    bot_id: str
    lottery_id: int
    discord_id: str
    discord_username: str


@router.post("/lottery")
async def create_lottery(
    req: LotteryRequest,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """创建抽奖（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = LotteryService(db, req.bot_id)
    lottery = await service.create_lottery(
        title=req.title,
        prize_quota=req.prize_quota,
        winner_count=req.winner_count,
        description=req.description,
        end_time=req.end_time,
        created_by=req.created_by
    )
    return {"success": True, "lottery_id": lottery.id}


@router.get("/lottery/{bot_id}")
async def get_lotteries(
    bot_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取抽奖列表"""
    service = LotteryService(db, bot_id)
    lotteries = await service.get_active_lotteries()
    return [{
        "id": l.id,
        "title": l.title,
        "description": l.description,
        "prize_quota": l.prize_quota,
        "winner_count": l.winner_count,
        "end_time": l.end_time.isoformat() if l.end_time else None,
        "is_ended": l.is_ended,
        "participant_count": await service.get_participant_count(l.id)
    } for l in lotteries]


@router.post("/lottery/join")
async def join_lottery(
    req: JoinLotteryRequest,
    db: AsyncSession = Depends(get_db)
):
    """参与抽奖"""
    service = LotteryService(db, req.bot_id)
    return await service.join_lottery(req.lottery_id, req.discord_id, req.discord_username)


@router.post("/lottery/{lottery_id}/draw")
async def draw_lottery(
    lottery_id: int,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """开奖（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = LotteryService(db)
    return await service.draw_lottery(lottery_id)


@router.delete("/lottery/{lottery_id}")
async def delete_lottery(
    lottery_id: int,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """删除抽奖（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = LotteryService(db)
    await service.delete_lottery(lottery_id)
    return {"success": True}


# ========== 红包 API ==========
class RedPacketRequest(BaseModel):
    bot_id: str
    total_quota: int
    total_count: int
    is_random: bool = True
    created_by: Optional[str] = None


class ClaimRedPacketRequest(BaseModel):
    bot_id: str
    red_packet_id: int
    discord_id: str
    discord_username: str


@router.post("/redpacket")
async def create_red_packet(
    req: RedPacketRequest,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """创建红包（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = RedPacketService(db, req.bot_id)
    rp = await service.create_red_packet(
        total_quota=req.total_quota,
        total_count=req.total_count,
        is_random=req.is_random,
        created_by=req.created_by
    )
    return {"success": True, "red_packet_id": rp.id}


@router.get("/redpacket/{bot_id}")
async def get_red_packets(
    bot_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取红包列表"""
    service = RedPacketService(db, bot_id)
    packets = await service.get_active_red_packets()
    return [{
        "id": p.id,
        "total_quota": p.total_quota,
        "remaining_quota": p.remaining_quota,
        "total_count": p.total_count,
        "remaining_count": p.remaining_count,
        "is_random": p.is_random,
        "is_active": p.is_active
    } for p in packets]


@router.get("/redpacket/{bot_id}/all")
async def get_all_red_packets(
    bot_id: str,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """获取所有红包（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = RedPacketService(db, bot_id)
    packets = await service.get_all_red_packets()
    return [{
        "id": p.id,
        "total_quota": p.total_quota,
        "remaining_quota": p.remaining_quota,
        "total_count": p.total_count,
        "remaining_count": p.remaining_count,
        "is_random": p.is_random,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None
    } for p in packets]


@router.post("/redpacket/claim")
async def claim_red_packet(
    req: ClaimRedPacketRequest,
    db: AsyncSession = Depends(get_db)
):
    """领取红包"""
    service = RedPacketService(db, req.bot_id)
    return await service.claim_red_packet(req.red_packet_id, req.discord_id, req.discord_username)


@router.delete("/redpacket/{red_packet_id}")
async def delete_red_packet(
    red_packet_id: int,
    x_admin_secret: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """删除红包（管理员）"""
    if x_admin_secret != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    service = RedPacketService(db)
    await service.delete_red_packet(red_packet_id)
    return {"success": True}
