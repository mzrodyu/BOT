from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import SensitiveWord
from typing import List, Tuple
import re


class ContentFilter:
    JAILBREAK_PATTERNS = [
        r"忽略.*指令",
        r"忘记.*设定",
        r"假装.*没有限制",
        r"扮演.*不受约束",
        r"DAN.*模式",
        r"越狱",
        r"ignore.*instruction",
        r"forget.*rules",
        r"pretend.*no.*limit",
        r"jailbreak",
    ]
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._sensitive_words: List[str] = []
        self._loaded = False
    
    async def load_sensitive_words(self):
        result = await self.db.execute(
            select(SensitiveWord).where(SensitiveWord.is_active == True)
        )
        words = result.scalars().all()
        self._sensitive_words = [w.word.lower() for w in words]
        self._loaded = True
    
    async def check_content(self, content: str) -> Tuple[bool, str]:
        if not self._loaded:
            await self.load_sensitive_words()
        
        content_lower = content.lower()
        
        for pattern in self.JAILBREAK_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return False, "检测到破甲话术"
        
        # 移除纯数字串（如用户ID）后再检测，避免误匹配
        # 保留原文用于检测，但对纯数字敏感词特殊处理
        content_no_ids = re.sub(r'\b\d{10,}\b', '', content_lower)  # 移除10位以上数字
        
        for word in self._sensitive_words:
            # 纯数字敏感词需要独立匹配，不能是长数字的一部分
            if word.isdigit():
                if re.search(r'(?<!\d)' + re.escape(word) + r'(?!\d)', content_lower):
                    return False, f"包含敏感词"
            # 短词（<=2字符）需要更严格匹配
            elif len(word) <= 2:
                if re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', content_lower):
                    return False, f"包含敏感词"
            else:
                if word in content_lower:
                    return False, f"包含敏感词"
        
        return True, ""
    
    async def add_sensitive_word(self, word: str, category: str = None) -> SensitiveWord:
        existing = await self.db.execute(
            select(SensitiveWord).where(SensitiveWord.word == word)
        )
        if existing.scalar_one_or_none():
            return None
        
        sw = SensitiveWord(word=word, category=category)
        self.db.add(sw)
        await self.db.commit()
        await self.db.refresh(sw)
        
        self._sensitive_words.append(word.lower())
        return sw
    
    async def remove_sensitive_word(self, word_id: int) -> bool:
        result = await self.db.execute(
            select(SensitiveWord).where(SensitiveWord.id == word_id)
        )
        sw = result.scalar_one_or_none()
        if not sw:
            return False
        
        if sw.word.lower() in self._sensitive_words:
            self._sensitive_words.remove(sw.word.lower())
        
        await self.db.delete(sw)
        await self.db.commit()
        return True
    
    async def get_all_words(self) -> List[SensitiveWord]:
        result = await self.db.execute(select(SensitiveWord))
        return result.scalars().all()
