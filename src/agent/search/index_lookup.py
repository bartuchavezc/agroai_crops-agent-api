# src/agent/search/index_lookup.py
"""
First-stage index lookup service.

Searches the summaries/metadata index to find relevant
categories and document collections before the detailed search.
"""
import logging
from typing import List

from .interfaces import IIndexLookupService, IndexSummary
from .elastic_adapter import ElasticSearchAdapter

logger = logging.getLogger(__name__)


class IndexLookupService(IIndexLookupService):
    """
    Service for first-stage index lookup.
    
    Searches a lightweight index of summaries/categories
    to identify which document collections are relevant
    before performing the more expensive full-text search.
    """
    
    def __init__(self, elastic_adapter: ElasticSearchAdapter):
        """
        Initialize index lookup service.
        
        Args:
            elastic_adapter: Elasticsearch adapter
        """
        self.adapter = elastic_adapter
    
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
        try:
            results = await self.adapter.search_summaries(
                query=query,
                max_results=max_results,
            )
            
            summaries = []
            for doc in results:
                summary = IndexSummary(
                    id=doc.get("id", ""),
                    category=doc.get("category", ""),
                    keywords=doc.get("keywords", []),
                    document_count=doc.get("document_count", 0),
                    description=doc.get("description", ""),
                    relevance_score=doc.get("relevance_score", 0.0),
                )
                summaries.append(summary)
            
            logger.debug(f"Index lookup found {len(summaries)} categories for: {query[:50]}")
            return summaries
            
        except Exception as e:
            logger.error(f"Error in index lookup: {e}")
            return []
    
    async def get_all_categories(self) -> List[str]:
        """
        Get all available categories.
        
        Returns:
            List of category names
        """
        try:
            # Search with match_all to get all summaries
            results = await self.adapter.search_summaries(
                query="*",
                max_results=100,
            )
            
            return list(set(doc.get("category", "") for doc in results if doc.get("category")))
            
        except Exception as e:
            logger.error(f"Error getting categories: {e}")
            return []
