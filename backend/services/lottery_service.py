from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import Lottery, LotteryParticipant, RedPacket, RedPacketClaim, PublicAPIUser, PublicAPIConfig
from typing import Optional, Dict, Any, List
from datetime import datetime
import random
import httpx


class LotteryService:
    """抽奖服务"""
    
    def __init__(self, db: AsyncSession, bot_id: str = "default"):
        self.db = db
        self.bot_id = bot_id
    
    async def create_lottery(
        self,
        title: str,
        prize_quota: int,
        winner_count: int = 1,
        description: str = None,
        end_time: datetime = None,
        created_by: str = None
    ) -> Lottery:
        """创建抽奖活动"""
        lottery = Lottery(
            bot_id=self.bot_id,
            title=title,
            description=description,
            prize_quota=prize_quota,
            winner_count=winner_count,
            end_time=end_time,
            created_by=created_by
        )
        self.db.add(lottery)
        await self.db.commit()
        await self.db.refresh(lottery)
        return lottery
    
    async def get_active_lotteries(self) -> List[Lottery]:
        """获取活跃的抽奖列表"""
        result = await self.db.execute(
            select(Lottery).where(
                Lottery.bot_id == self.bot_id,
                Lottery.is_active == True,
                Lottery.is_ended == False
            ).order_by(Lottery.created_at.desc())
        )
        return result.scalars().all()
    
    async def get_lottery(self, lottery_id: int) -> Optional[Lottery]:
        """获取抽奖详情"""
        result = await self.db.execute(
            select(Lottery).where(Lottery.id == lottery_id)
        )
        return result.scalar_one_or_none()
    
    async def join_lottery(self, lottery_id: int, discord_id: str, discord_username: str) -> Dict[str, Any]:
        """参与抽奖"""
        lottery = await self.get_lottery(lottery_id)
        if not lottery:
            return {"success": False, "error": "抽奖不存在"}
        if lottery.is_ended:
            return {"success": False, "error": "抽奖已结束"}
        if not lottery.is_active:
            return {"success": False, "error": "抽奖未开启"}
        
        # 检查是否已参与
        existing = await self.db.execute(
            select(LotteryParticipant).where(
                LotteryParticipant.lottery_id == lottery_id,
                LotteryParticipant.discord_id == discord_id
            )
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "您已经参与过了"}
        
        participant = LotteryParticipant(
            lottery_id=lottery_id,
            discord_id=discord_id,
            discord_username=discord_username
        )
        self.db.add(participant)
        await self.db.commit()
        
        # 获取参与人数
        count_result = await self.db.execute(
            select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id)
        )
        count = len(count_result.scalars().all())
        
        return {"success": True, "participant_count": count}
    
    async def draw_lottery(self, lottery_id: int) -> Dict[str, Any]:
        """开奖"""
        lottery = await self.get_lottery(lottery_id)
        if not lottery:
            return {"success": False, "error": "抽奖不存在"}
        if lottery.is_ended:
            return {"success": False, "error": "抽奖已开奖"}
        
        # 获取所有参与者
        result = await self.db.execute(
            select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id)
        )
        participants = result.scalars().all()
        
        if len(participants) == 0:
            return {"success": False, "error": "没有参与者"}
        
        # 随机选择中奖者
        winner_count = min(lottery.winner_count, len(participants))
        winners = random.sample(list(participants), winner_count)
        
        # 更新中奖状态
        for winner in winners:
            winner.is_winner = True
        
        # 标记抽奖结束
        lottery.is_ended = True
        await self.db.commit()
        
        # 给中奖者发放额度
        prize_per_winner = lottery.prize_quota // winner_count if winner_count > 0 else 0
        
        return {
            "success": True,
            "winners": [{"discord_id": w.discord_id, "username": w.discord_username} for w in winners],
            "prize_per_winner": prize_per_winner
        }
    
    async def get_participant_count(self, lottery_id: int) -> int:
        """获取参与人数"""
        result = await self.db.execute(
            select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id)
        )
        return len(result.scalars().all())
    
    async def delete_lottery(self, lottery_id: int) -> bool:
        """删除抽奖"""
        lottery = await self.get_lottery(lottery_id)
        if lottery:
            await self.db.delete(lottery)
            await self.db.commit()
            return True
        return False


class RedPacketService:
    """红包服务"""
    
    def __init__(self, db: AsyncSession, bot_id: str = "default"):
        self.db = db
        self.bot_id = bot_id
    
    async def create_red_packet(
        self,
        total_quota: int,
        total_count: int,
        is_random: bool = True,
        created_by: str = None
    ) -> RedPacket:
        """创建红包"""
        red_packet = RedPacket(
            bot_id=self.bot_id,
            total_quota=total_quota,
            remaining_quota=total_quota,
            total_count=total_count,
            remaining_count=total_count,
            is_random=is_random,
            created_by=created_by
        )
        self.db.add(red_packet)
        await self.db.commit()
        await self.db.refresh(red_packet)
        return red_packet
    
    async def get_active_red_packets(self) -> List[RedPacket]:
        """获取活跃的红包列表"""
        result = await self.db.execute(
            select(RedPacket).where(
                RedPacket.bot_id == self.bot_id,
                RedPacket.is_active == True,
                RedPacket.remaining_count > 0
            ).order_by(RedPacket.created_at.desc())
        )
        return result.scalars().all()
    
    async def get_red_packet(self, red_packet_id: int) -> Optional[RedPacket]:
        """获取红包详情"""
        result = await self.db.execute(
            select(RedPacket).where(RedPacket.id == red_packet_id)
        )
        return result.scalar_one_or_none()
    
    async def claim_red_packet(self, red_packet_id: int, discord_id: str, discord_username: str) -> Dict[str, Any]:
        """领取红包"""
        red_packet = await self.get_red_packet(red_packet_id)
        if not red_packet:
            return {"success": False, "error": "红包不存在"}
        if not red_packet.is_active:
            return {"success": False, "error": "红包已失效"}
        if red_packet.remaining_count <= 0:
            return {"success": False, "error": "红包已领完"}
        
        # 检查是否已领取
        existing = await self.db.execute(
            select(RedPacketClaim).where(
                RedPacketClaim.red_packet_id == red_packet_id,
                RedPacketClaim.discord_id == discord_id
            )
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "您已经领过了"}
        
        # 计算领取额度
        if red_packet.is_random:
            # 拼手气：随机分配
            if red_packet.remaining_count == 1:
                quota = red_packet.remaining_quota
            else:
                # 保证每个人至少能领到1，最多领取剩余额度的50%
                max_quota = max(1, red_packet.remaining_quota * 2 // (red_packet.remaining_count + 1))
                quota = random.randint(1, max_quota)
        else:
            # 平均分配
            quota = red_packet.total_quota // red_packet.total_count
        
        # 更新红包
        red_packet.remaining_quota -= quota
        red_packet.remaining_count -= 1
        if red_packet.remaining_count <= 0:
            red_packet.is_active = False
        
        # 记录领取
        claim = RedPacketClaim(
            red_packet_id=red_packet_id,
            discord_id=discord_id,
            discord_username=discord_username,
            quota_received=quota
        )
        self.db.add(claim)
        await self.db.commit()
        
        return {
            "success": True,
            "quota": quota,
            "remaining_count": red_packet.remaining_count
        }
    
    async def get_all_red_packets(self) -> List[RedPacket]:
        """获取所有红包（管理用）"""
        result = await self.db.execute(
            select(RedPacket).where(
                RedPacket.bot_id == self.bot_id
            ).order_by(RedPacket.created_at.desc())
        )
        return result.scalars().all()
    
    async def delete_red_packet(self, red_packet_id: int) -> bool:
        """删除红包"""
        red_packet = await self.get_red_packet(red_packet_id)
        if red_packet:
            await self.db.delete(red_packet)
            await self.db.commit()
            return True
        return False
