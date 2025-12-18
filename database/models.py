from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String(50), unique=True, nullable=False, index=True)
    username = Column(String(100))
    display_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    memories = relationship("Memory", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Memory(Base):
    __tablename__ = "memories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    summary = Column(Text)
    traits = Column(Text)
    preferences = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="memories")


class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel_id = Column(String(50))
    role = Column(String(20))  # user / assistant
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="conversations")
    
    __table_args__ = (
        Index("idx_conv_user_channel", "user_id", "channel_id"),
    )


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    keywords = Column(String(500))
    category = Column(String(100))
    embedding = Column(Text, nullable=True)  # JSON格式存储向量
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_kb_keywords", "keywords"),
    )


class Blacklist(Base):
    __tablename__ = "blacklist"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String(50), unique=True, nullable=False, index=True)
    username = Column(String(100))
    reason = Column(Text)
    banned_by = Column(String(50))
    is_permanent = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChannelWhitelist(Base):
    __tablename__ = "channel_whitelist"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(50), nullable=False, index=True)
    channel_id = Column(String(50), nullable=False, index=True)
    guild_id = Column(String(50), nullable=False)
    channel_name = Column(String(100))
    added_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_channel_bot", "bot_id", "channel_id", unique=True),
    )


class SensitiveWord(Base):
    __tablename__ = "sensitive_words"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(100), unique=True, nullable=False)
    category = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemConfig(Base):
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(String(500))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BotConfig(Base):
    """Bot独立配置（每个Bot实例独立）"""
    __tablename__ = "bot_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(50), unique=True, nullable=False, index=True)
    bot_name = Column(String(100), default="CatieBot")
    system_prompt = Column(Text)  # 人设
    context_limit = Column(Integer, default=10)  # 上下文条数
    admin_ids = Column(Text)  # 逗号分隔的管理员ID
    chat_mode = Column(String(20), default="multi")  # single=单用户, multi=多用户, qa=答疑
    respond_to_bot = Column(Boolean, default=False)  # 是否响应其他机器人的@
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PublicAPIConfig(Base):
    """公益站配置"""
    __tablename__ = "public_api_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(50), nullable=False, index=True)
    name = Column(String(100), default="公益站")  # 站点名称
    newapi_url = Column(String(500))  # NewAPI地址
    newapi_token = Column(String(500))  # 管理员session/token
    default_quota = Column(Integer, default=100000)  # 默认额度（美元*500000）
    default_group = Column(String(50), default="default")  # 默认用户组
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PublicAPIUser(Base):
    """公益站用户注册记录"""
    __tablename__ = "public_api_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(String(50), nullable=False, index=True)
    discord_username = Column(String(100))
    newapi_user_id = Column(Integer)  # NewAPI中的用户ID
    newapi_username = Column(String(100))  # NewAPI用户名
    api_key = Column(String(200))  # 分配的API Key
    registered_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_public_api_discord", "discord_id", unique=True),
    )


class Lottery(Base):
    """抽奖活动"""
    __tablename__ = "lotteries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(50), nullable=False, index=True)
    title = Column(String(200), nullable=False)  # 抽奖标题
    description = Column(Text)  # 描述
    prize_quota = Column(Integer, default=0)  # 奖品额度
    winner_count = Column(Integer, default=1)  # 中奖人数
    end_time = Column(DateTime)  # 结束时间
    is_active = Column(Boolean, default=True)
    is_ended = Column(Boolean, default=False)
    created_by = Column(String(50))  # 创建者Discord ID
    created_at = Column(DateTime, default=datetime.utcnow)


class LotteryParticipant(Base):
    """抽奖参与者"""
    __tablename__ = "lottery_participants"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    lottery_id = Column(Integer, ForeignKey("lotteries.id"), nullable=False)
    discord_id = Column(String(50), nullable=False)
    discord_username = Column(String(100))
    is_winner = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_lottery_participant", "lottery_id", "discord_id", unique=True),
    )


class RedPacket(Base):
    """额度红包"""
    __tablename__ = "red_packets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(50), nullable=False, index=True)
    total_quota = Column(Integer, nullable=False)  # 总额度
    remaining_quota = Column(Integer, nullable=False)  # 剩余额度
    total_count = Column(Integer, nullable=False)  # 总个数
    remaining_count = Column(Integer, nullable=False)  # 剩余个数
    is_random = Column(Boolean, default=True)  # 是否拼手气
    created_by = Column(String(50))  # 创建者Discord ID
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RedPacketClaim(Base):
    """红包领取记录"""
    __tablename__ = "red_packet_claims"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    red_packet_id = Column(Integer, ForeignKey("red_packets.id"), nullable=False)
    discord_id = Column(String(50), nullable=False)
    discord_username = Column(String(100))
    quota_received = Column(Integer, nullable=False)  # 领取的额度
    claimed_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_redpacket_claim", "red_packet_id", "discord_id", unique=True),
    )
