from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import SystemConfig
from openai import AsyncOpenAI
from typing import List, Dict, Optional
import json
import asyncio


class LLMPoolService:
    """LLM模型池服务，支持多模型/多Key轮流负载均衡"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __init__(self):
        self._pool: List[Dict] = []  # [{base_url, api_key, model, name, enabled}]
        self._current_index = 0
        self._loaded = False
        self._retry_count = 3  # 报错重试次数
        self._retry_on_error = True  # 是否启用报错重试
    
    @classmethod
    async def get_instance(cls) -> "LLMPoolService":
        """获取单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    async def load_from_db(self, db: AsyncSession):
        """从数据库加载模型池配置"""
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "llm_pool")
        )
        config = result.scalar_one_or_none()
        
        if config and config.value:
            try:
                data = json.loads(config.value)
                # 支持新旧格式
                if isinstance(data, list):
                    self._pool = data
                else:
                    self._pool = data.get("models", [])
                    self._retry_count = data.get("retry_count", 3)
                    self._retry_on_error = data.get("retry_on_error", True)
                self._loaded = True
                print(f"[LLMPool] Loaded {len(self._pool)} models, retry={self._retry_count}")
            except json.JSONDecodeError:
                self._pool = []
        
        return self._pool
    
    async def save_to_db(self, db: AsyncSession):
        """保存模型池配置到数据库"""
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "llm_pool")
        )
        config = result.scalar_one_or_none()
        
        # 使用新格式保存，包含重试配置
        data = {
            "models": self._pool,
            "retry_count": self._retry_count,
            "retry_on_error": self._retry_on_error
        }
        
        if config:
            config.value = json.dumps(data, ensure_ascii=False)
        else:
            config = SystemConfig(
                key="llm_pool",
                value=json.dumps(data, ensure_ascii=False),
                description="LLM模型池配置"
            )
            db.add(config)
        
        await db.commit()
    
    def add_model(self, base_url: str, api_key: str, model: str, name: str = None):
        """添加模型到池"""
        self._pool.append({
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "name": name or model,
            "enabled": True,
            "request_count": 0
        })
    
    def remove_model(self, index: int) -> bool:
        """移除模型"""
        if 0 <= index < len(self._pool):
            self._pool.pop(index)
            if self._current_index >= len(self._pool):
                self._current_index = 0
            return True
        return False
    
    def update_model(self, index: int, base_url: str = None, api_key: str = None, model: str = None, name: str = None) -> bool:
        """更新模型配置"""
        if 0 <= index < len(self._pool):
            if base_url is not None:
                self._pool[index]["base_url"] = base_url
            if api_key is not None:
                self._pool[index]["api_key"] = api_key
            if model is not None:
                self._pool[index]["model"] = model
            if name is not None:
                self._pool[index]["name"] = name
            return True
        return False
    
    def get_model(self, index: int) -> Optional[Dict]:
        """获取指定索引的模型（包含完整信息）"""
        if 0 <= index < len(self._pool):
            return self._pool[index]
        return None
    
    def toggle_model(self, index: int, enabled: bool) -> bool:
        """启用/禁用模型"""
        if 0 <= index < len(self._pool):
            self._pool[index]["enabled"] = enabled
            return True
        return False
    
    def get_pool(self) -> List[Dict]:
        """获取模型池列表"""
        return self._pool
    
    def get_enabled_models(self) -> List[Dict]:
        """获取启用的模型列表"""
        return [m for m in self._pool if m.get("enabled", True)]
    
    def get_next(self) -> Optional[Dict]:
        """轮流获取下一个可用模型"""
        enabled = self.get_enabled_models()
        if not enabled:
            return None
        
        # 轮流选择
        self._current_index = self._current_index % len(enabled)
        model = enabled[self._current_index]
        self._current_index = (self._current_index + 1) % len(enabled)
        
        # 增加请求计数
        if "request_count" not in model:
            model["request_count"] = 0
        model["request_count"] += 1
        
        return model
    
    def get_next_from_list(self, models: List[Dict]) -> Dict:
        """从指定列表中轮流选择下一个模型"""
        if not models:
            raise ValueError("模型列表为空")
        
        self._current_index = self._current_index % len(models)
        model = models[self._current_index]
        self._current_index = (self._current_index + 1) % len(models)
        
        # 更新请求计数（如果是池中的模型）
        self._increment_request_count(model)
        
        return model
    
    def _increment_request_count(self, model: Dict):
        """增加模型的请求计数（通过匹配base_url和model来找到池中对应的模型）"""
        for m in self._pool:
            if m.get("base_url") == model.get("base_url") and m.get("model") == model.get("model"):
                if "request_count" not in m:
                    m["request_count"] = 0
                m["request_count"] += 1
                self._needs_save = True
                break
    
    def needs_save(self) -> bool:
        """检查是否需要保存"""
        return getattr(self, '_needs_save', False)
    
    def mark_saved(self):
        """标记已保存"""
        self._needs_save = False
    
    def get_client_and_model(self, config: Dict = None) -> tuple[AsyncOpenAI, str]:
        """获取客户端和模型名，如果config为空则轮流选择"""
        if config is None:
            config = self.get_next()
        
        if config is None:
            raise ValueError("No available model in pool")
        
        client = AsyncOpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"]
        )
        return client, config["model"]
    
    def is_pool_enabled(self) -> bool:
        """检查是否启用了模型池（至少有一个模型）"""
        return len(self.get_enabled_models()) > 0
    
    @property
    def loaded(self) -> bool:
        return self._loaded
    
    @property
    def retry_count(self) -> int:
        return self._retry_count
    
    @retry_count.setter
    def retry_count(self, value: int):
        self._retry_count = max(1, min(10, value))  # 限制1-10次
    
    @property
    def retry_on_error(self) -> bool:
        return self._retry_on_error
    
    @retry_on_error.setter
    def retry_on_error(self, value: bool):
        self._retry_on_error = value
    
    def get_settings(self) -> Dict:
        """获取模型池设置"""
        return {
            "retry_count": self._retry_count,
            "retry_on_error": self._retry_on_error
        }
    
    def update_settings(self, retry_count: int = None, retry_on_error: bool = None):
        """更新模型池设置"""
        if retry_count is not None:
            self.retry_count = retry_count
        if retry_on_error is not None:
            self.retry_on_error = retry_on_error
    
    def reset_request_counts(self):
        """重置所有模型的请求计数"""
        for model in self._pool:
            model["request_count"] = 0
