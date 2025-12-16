from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from database.models import KnowledgeBase
from typing import List, Optional
import jieba
import json
from .embedding_service import EmbeddingService


class KnowledgeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._embedding_service = None
    
    async def get_embedding_service(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = await EmbeddingService.from_db(self.db)
        return self._embedding_service
    
    async def create(self, title: str, content: str, keywords: str = None, category: str = None, auto_embed: bool = True) -> KnowledgeBase:
        kb = KnowledgeBase(
            title=title,
            content=content,
            keywords=keywords,
            category=category
        )
        
        # 自动生成向量
        if auto_embed:
            try:
                embed_service = await self.get_embedding_service()
                embed_text = f"{title} {content[:500]}"  # 合并标题和内容前500字
                embedding = await embed_service.embed(embed_text)
                kb.embedding = json.dumps(embedding)
            except Exception as e:
                print(f"[KnowledgeService] Embedding failed: {e}")
        
        self.db.add(kb)
        await self.db.commit()
        await self.db.refresh(kb)
        return kb
    
    async def get_by_id(self, kb_id: int) -> Optional[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        return result.scalar_one_or_none()
    
    async def update(self, kb_id: int, **kwargs) -> Optional[KnowledgeBase]:
        kb = await self.get_by_id(kb_id)
        if not kb:
            return None
        
        for key, value in kwargs.items():
            if value is not None and hasattr(kb, key):
                setattr(kb, key, value)
        
        await self.db.commit()
        await self.db.refresh(kb)
        return kb
    
    async def delete(self, kb_id: int) -> bool:
        kb = await self.get_by_id(kb_id)
        if not kb:
            return False
        
        await self.db.delete(kb)
        await self.db.commit()
        return True
    
    async def search(self, query: str, limit: int = 3, max_content_length: int = 500, use_vector: bool = True) -> List[KnowledgeBase]:
        """搜索知识库，优先使用向量检索，回退到关键词匹配"""
        print(f"[KnowledgeService] Searching for: {query[:50]}...")
        
        # 尝试向量检索
        if use_vector:
            try:
                results = await self.vector_search(query, limit, max_content_length)
                if results:
                    print(f"[KnowledgeService] Vector search found {len(results)} results")
                    return results
                print("[KnowledgeService] Vector search returned empty, trying keyword")
            except Exception as e:
                print(f"[KnowledgeService] Vector search failed, fallback to keyword: {e}")
        
        # 回退到关键词匹配
        results = await self.keyword_search(query, limit, max_content_length)
        print(f"[KnowledgeService] Keyword search found {len(results)} results")
        return results
    
    async def vector_search(self, query: str, limit: int = 3, max_content_length: int = 500) -> List[KnowledgeBase]:
        """向量语义检索"""
        # 获取所有有向量的知识库条目
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.is_active == True)
            .where(KnowledgeBase.embedding.isnot(None))
        )
        all_kb = result.scalars().all()
        
        if not all_kb:
            print("[KnowledgeService] No knowledge entries with embeddings found")
            return []
        
        print(f"[KnowledgeService] Found {len(all_kb)} entries with embeddings")
        
        # 获取查询向量
        embed_service = await self.get_embedding_service()
        query_embedding = await embed_service.embed(query)
        
        # 计算相似度
        embeddings = [json.loads(kb.embedding) for kb in all_kb]
        similar_indices = EmbeddingService.find_most_similar(
            query_embedding, 
            embeddings, 
            top_k=limit,
            threshold=0.3  # 降低相似度阈值以提高召回率
        )
        
        results = []
        for idx, score in similar_indices:
            kb = all_kb[idx]
            # 截断过长内容
            if len(kb.content) > max_content_length:
                kb.content = kb.content[:max_content_length] + "...(已截断)"
            results.append(kb)
            print(f"[KnowledgeService] Vector match: {kb.title} (score: {score:.3f})")
        
        return results
    
    async def keyword_search(self, query: str, limit: int = 3, max_content_length: int = 500) -> List[KnowledgeBase]:
        """关键词匹配检索"""
        keywords = list(jieba.cut(query))
        keywords = [k.strip() for k in keywords if len(k.strip()) > 1]
        
        if not keywords:
            return []
        
        conditions = []
        for kw in keywords[:5]:
            conditions.append(KnowledgeBase.keywords.contains(kw))
            conditions.append(KnowledgeBase.title.contains(kw))
        
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.is_active == True)
            .where(or_(*conditions))
            .limit(limit)
        )
        results = result.scalars().all()
        
        for kb in results:
            if len(kb.content) > max_content_length:
                kb.content = kb.content[:max_content_length] + "...(已截断)"
        
        return results
    
    async def rebuild_embeddings(self) -> int:
        """重建所有知识库条目的向量"""
        result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.is_active == True)
        )
        all_kb = result.scalars().all()
        
        embed_service = await self.get_embedding_service()
        count = 0
        for kb in all_kb:
            try:
                embed_text = f"{kb.title} {kb.content[:500]}"
                embedding = await embed_service.embed(embed_text)
                kb.embedding = json.dumps(embedding)
                count += 1
            except Exception as e:
                print(f"[KnowledgeService] Embed failed for {kb.id}: {e}")
        
        await self.db.commit()
        return count
    
    async def get_all(self, skip: int = 0, limit: int = 100, active_only: bool = False):
        query = select(KnowledgeBase)
        if active_only:
            query = query.where(KnowledgeBase.is_active == True)
        query = query.offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_total_count(self, active_only: bool = False) -> int:
        """获取知识库条目总数"""
        from sqlalchemy import func
        query = select(func.count(KnowledgeBase.id))
        if active_only:
            query = query.where(KnowledgeBase.is_active == True)
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    async def batch_update_category(self, kb_ids: List[int], category: str) -> int:
        """批量更新知识库分类"""
        from sqlalchemy import update
        result = await self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id.in_(kb_ids))
            .values(category=category)
        )
        await self.db.commit()
        return result.rowcount
    
    async def batch_delete(self, kb_ids: List[int]) -> int:
        """批量删除知识库条目"""
        from sqlalchemy import delete as sql_delete
        result = await self.db.execute(
            sql_delete(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )
        await self.db.commit()
        return result.rowcount
    
    async def batch_toggle_active(self, kb_ids: List[int], is_active: bool) -> int:
        """批量启用/禁用知识库条目"""
        from sqlalchemy import update
        result = await self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id.in_(kb_ids))
            .values(is_active=is_active)
        )
        await self.db.commit()
        return result.rowcount
