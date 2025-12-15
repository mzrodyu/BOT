from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from database.models import Blacklist, User
from typing import Optional, List
from datetime import datetime, timedelta


class BlacklistService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def ban_user(
        self, 
        discord_id: str, 
        username: str = None,
        reason: str = None, 
        banned_by: str = None,
        is_permanent: bool = False,
        duration_minutes: int = None,
        delete_data: bool = True
    ) -> Blacklist:
        existing = await self.get_by_discord_id(discord_id)
        if existing:
            await self.db.delete(existing)
        
        # 删除用户数据（对话记录、记忆等）
        if delete_data:
            user_result = await self.db.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = user_result.scalar_one_or_none()
            if user:
                await self.db.delete(user)  # 级联删除memories和conversations
                print(f"[BlacklistService] Deleted user data for {discord_id}")
        
        expires_at = None
        if not is_permanent and duration_minutes:
            expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
        
        ban = Blacklist(
            discord_id=discord_id,
            username=username,
            reason=reason,
            banned_by=banned_by,
            is_permanent=is_permanent,
            expires_at=expires_at
        )
        self.db.add(ban)
        await self.db.commit()
        await self.db.refresh(ban)
        return ban
    
    async def unban_user(self, discord_id: str) -> bool:
        result = await self.db.execute(
            delete(Blacklist).where(Blacklist.discord_id == discord_id)
        )
        await self.db.commit()
        return result.rowcount > 0
    
    async def is_banned(self, discord_id: str) -> tuple[bool, Optional[str]]:
        ban = await self.get_by_discord_id(discord_id)
        if not ban:
            return False, None
        
        if ban.is_permanent:
            return True, ban.reason
        
        if ban.expires_at and ban.expires_at < datetime.utcnow():
            await self.unban_user(discord_id)
            return False, None
        
        return True, ban.reason
    
    async def get_by_discord_id(self, discord_id: str) -> Optional[Blacklist]:
        result = await self.db.execute(
            select(Blacklist).where(Blacklist.discord_id == discord_id)
        )
        return result.scalar_one_or_none()
    
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Blacklist]:
        result = await self.db.execute(
            select(Blacklist).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    async def cleanup_expired(self) -> int:
        result = await self.db.execute(
            delete(Blacklist).where(
                Blacklist.is_permanent == False,
                Blacklist.expires_at < datetime.utcnow()
            )
        )
        await self.db.commit()
        return result.rowcount
