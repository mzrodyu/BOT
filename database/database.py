from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from .models import Base
from config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # 自动添加缺失的字段
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE bot_config ADD COLUMN admin_ids TEXT"
                )
            )
        except:
            pass
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE bot_config ADD COLUMN chat_mode TEXT DEFAULT 'chat'"
                )
            )
        except:
            pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
