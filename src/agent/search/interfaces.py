# src/agent/search/interfaces.py
"""
Search interface definitions for the two-stage search system.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """
    Standard search result format.
    
    Attributes:
        id: Document identifier
        title: Document title
        content: Document content (or excerpt)
        score: Relevance score
        source: Source identifier (e.g., "inta_manual", "vademecum")
        category: Document category
        region: Applicable region/country
        metadata: Additional metadata
    """
    id: str
    title: str
    content: str
    score: float
    source: str = ""
    category: str = ""
    region: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "source": self.source,
            "category": self.category,
            "region": self.region,
            "metadata": self.metadata,
        }


@dataclass
class IndexSummary:
    """
    Summary entry from the first-stage index.
    
    Attributes:
        id: Summary identifier
        category: Category name
        keywords: Associated keywords
        document_count: Number of documents in this category
        description: Brief description of the category
        relevance_score: Relevance to query
    """
    id: str
    category: str
    keywords: List[str]
    document_count: int
    description: str
    relevance_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "keywords": self.keywords,
            "document_count": self.document_count,
            "description": self.description,
            "relevance_score": self.relevance_score,
        }


class ISearchService(ABC):
    """
    Abstract interface for search services.
    """
    
    @abstractmethod
    async def search(
        self,
        query: str,
        context: Optional[str] = None,
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[SearchResult]:
        """
        Search for relevant documents.
        
        Args:
            query: Search query
            context: Optional conversation context
            region: Optional region filter
            max_results: Maximum results to return
            
        Returns:
            List of search results
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check search service health.
        
        Returns:
            Health status dictionary
        """
        pass


class IIndexLookupService(ABC):
    """
    Interface for first-stage index lookup (summaries/categories).
    """
    
    @abstractmethod
    async def lookup(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[IndexSummary]:
        """
        Look up relevant categories/summaries.
        
        Args:
            query: Search query
            max_results: Maximum summaries to return
            
        Returns:
            List of relevant summaries
        """
        pass


class IDocumentSearchService(ABC):
    """
    Interface for second-stage document search.
    """
    
    @abstractmethod
    async def search_in_categories(
        self,
        query: str,
        categories: List[str],
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[SearchResult]:
        """
        Search documents within specific categories.
        
        Args:
            query: Search query
            categories: Categories to search in
            region: Optional region filter
            max_results: Maximum results to return
            
        Returns:
            List of search results
        """
        pass
