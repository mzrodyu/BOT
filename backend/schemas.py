from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# User Schemas
class UserBase(BaseModel):
    discord_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# Memory Schemas
class MemoryBase(BaseModel):
    summary: Optional[str] = None
    traits: Optional[str] = None
    preferences: Optional[str] = None


class MemoryCreate(MemoryBase):
    user_id: int


class MemoryResponse(MemoryBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Conversation Schemas
class ConversationCreate(BaseModel):
    discord_id: str
    channel_id: str
    role: str
    content: str


class ConversationResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    
    class Config:
        from_attributes = True


# Knowledge Base Schemas
class KnowledgeBaseCreate(BaseModel):
    title: str
    content: str
    keywords: Optional[str] = None
    category: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    keywords: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class KnowledgeBaseResponse(BaseModel):
    id: int
    title: str
    content: str
    keywords: Optional[str]
    category: Optional[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# Blacklist Schemas
class BlacklistCreate(BaseModel):
    discord_id: str
    username: Optional[str] = None
    reason: Optional[str] = None
    banned_by: Optional[str] = None
    is_permanent: bool = False
    duration_minutes: Optional[int] = None


class BlacklistResponse(BaseModel):
    id: int
    discord_id: str
    username: Optional[str]
    reason: Optional[str]
    is_permanent: bool
    expires_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


# Channel Whitelist Schemas
class ChannelWhitelistCreate(BaseModel):
    bot_id: str
    channel_id: str
    guild_id: str
    channel_name: Optional[str] = None
    added_by: Optional[str] = None


class ChannelWhitelistResponse(BaseModel):
    id: int
    bot_id: str
    channel_id: str
    guild_id: str
    channel_name: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


# Chat Schemas
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    bot_id: str = "default"
    discord_id: str
    username: str
    channel_id: str
    message: str
    context_messages: List[ChatMessage] = []
    pinned_messages: List[str] = []
    reply_content: Optional[str] = None
    image_urls: List[str] = []
    guild_emojis: Optional[str] = None


class ChatResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None


# Sensitive Word Schemas
class SensitiveWordCreate(BaseModel):
    word: str
    category: Optional[str] = None


class SensitiveWordResponse(BaseModel):
    id: int
    word: str
    category: Optional[str]
    is_active: bool
    
    class Config:
        from_attributes = True


# Bot Config Schemas
class BotConfigCreate(BaseModel):
    bot_id: str
    bot_name: Optional[str] = "CatieBot"
    system_prompt: Optional[str] = None
    context_limit: Optional[int] = 10
    admin_ids: Optional[str] = None  # 逗号分隔的管理员ID
    chat_mode: Optional[str] = "chat"  # chat=聊天模式, qa=答疑模式


class BotConfigUpdate(BaseModel):
    bot_name: Optional[str] = None
    system_prompt: Optional[str] = None
    context_limit: Optional[int] = None
    is_active: Optional[bool] = None
    admin_ids: Optional[str] = None  # 逗号分隔的管理员ID
    chat_mode: Optional[str] = None  # chat=聊天模式, qa=答疑模式


class BotConfigResponse(BaseModel):
    id: int
    bot_id: str
    bot_name: str
    system_prompt: Optional[str]
    context_limit: int
    is_active: bool
    admin_ids: Optional[str] = None
    chat_mode: Optional[str] = "chat"
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# LLM Config Schemas
class LLMConfigUpdate(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    stream: Optional[bool] = None


class LLMConfigResponse(BaseModel):
    base_url: str
    api_key: str
    model: str
    stream: bool = True
