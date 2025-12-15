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
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
