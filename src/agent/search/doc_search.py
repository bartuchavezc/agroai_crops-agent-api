# src/agent/search/doc_search.py
"""
Second-stage document search service.

Performs detailed full-text search within specific categories
identified by the first-stage index lookup.
"""
import logging
from typing import List, Optional

from .interfaces import IDocumentSearchService, SearchResult
from .elastic_adapter import ElasticSearchAdapter

logger = logging.getLogger(__name__)


class DocumentSearchService(IDocumentSearchService):
    """
    Service for second-stage document search.
    
    Searches the full documents index, optionally filtered
    by categories from the first stage and by region.
    """
    
    def __init__(self, elastic_adapter: ElasticSearchAdapter):
        """
        Initialize document search service.
        
        Args:
            elastic_adapter: Elasticsearch adapter
        """
        self.adapter = elastic_adapter
    
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
        try:
            results = await self.adapter.search_documents(
                query=query,
                categories=categories if categories else None,
                region=region,
                max_results=max_results,
            )
            
            search_results = []
            for doc in results:
                result = SearchResult(
                    id=doc.get("id", ""),
                    title=doc.get("title", "Sin título"),
                    content=doc.get("content", ""),
                    score=doc.get("score", 0.0),
                    source=doc.get("source", ""),
                    category=doc.get("category", ""),
                    region=doc.get("region", "global"),
                    metadata={
                        "highlights": doc.get("highlights", []),
                        "author": doc.get("author"),
                        "date": doc.get("date"),
                    }
                )
                search_results.append(result)
            
            logger.debug(f"Document search found {len(search_results)} results for: {query[:50]}")
            return search_results
            
        except Exception as e:
            logger.error(f"Error in document search: {e}")
            return []
    
    async def search_all(
        self,
        query: str,
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[SearchResult]:
        """
        Search all documents without category filter.
        
        Args:
            query: Search query
            region: Optional region filter
            max_results: Maximum results
            
        Returns:
            List of search results
        """
        return await self.search_in_categories(
            query=query,
            categories=[],
            region=region,
            max_results=max_results,
        )
