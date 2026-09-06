from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class RAGClientInterface(ABC):
    """统一的 RAG 客户端接口，便于替换后端实现。"""

    @abstractmethod
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义检索：输入自然语言，返回候选条目列表（包含文本、score、meta 等）。"""
        pass

    @abstractmethod
    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        """知识图谱查询：输入实体名，返回相关关系/节点列表。"""
        pass

    @abstractmethod
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """混合检索：语义 + 图谱的综合召回接口。"""
        pass
