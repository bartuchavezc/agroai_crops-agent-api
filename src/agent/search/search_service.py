# src/agent/search/search_service.py
"""
Two-stage search service orchestrator.

Combines index lookup (stage 1) with document search (stage 2)
to provide efficient and relevant search results.
"""
import logging
from typing import Any, Dict, List, Optional

from .interfaces import ISearchService, SearchResult
from .index_lookup import IndexLookupService
from .doc_search import DocumentSearchService

logger = logging.getLogger(__name__)


class TwoStageSearchService(ISearchService):
    """
    Two-stage search service.
    
    Stage 1: Index Lookup
    - Searches a lightweight index of summaries/categories
    - Identifies which document collections are relevant
    - Fast and cheap
    
    Stage 2: Document Search
    - Searches full documents within identified categories
    - Filtered by region when applicable
    - Returns detailed results
    
    Benefits:
    - Reduces search space for large document collections
    - Improves relevance by focusing on appropriate categories
    - Supports region-specific filtering
    """
    
    def __init__(
        self,
        index_lookup: IndexLookupService,
        doc_search: DocumentSearchService,
        skip_lookup_threshold: int = 3,
    ):
        """
        Initialize two-stage search service.
        
        Args:
            index_lookup: First-stage index lookup service
            doc_search: Second-stage document search service
            skip_lookup_threshold: Minimum categories to skip first stage
        """
        self.index_lookup = index_lookup
        self.doc_search = doc_search
        self.skip_lookup_threshold = skip_lookup_threshold
    
    async def search(
        self,
        query: str,
        context: Optional[str] = None,
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[SearchResult]:
        """
        Perform two-stage search.
        
        Args:
            query: Search query
            context: Optional conversation context
            region: Optional region filter
            max_results: Maximum results to return
            
        Returns:
            List of search results
        """
        try:
            # Enhance query with context if available
            enhanced_query = self._enhance_query(query, context)
            
            # Stage 1: Index Lookup
            logger.debug(f"Stage 1: Looking up categories for: {enhanced_query[:50]}")
            summaries = await self.index_lookup.lookup(
                query=enhanced_query,
                max_results=5,
            )
            
            # Extract categories from summaries
            categories = [s.category for s in summaries if s.category]
            
            if not categories:
                # If no categories found, search all documents
                logger.debug("No categories found, searching all documents")
                return await self.doc_search.search_all(
                    query=enhanced_query,
                    region=region,
                    max_results=max_results,
                )
            
            logger.debug(f"Stage 1 found categories: {categories}")
            
            # Stage 2: Document Search within categories
            logger.debug(f"Stage 2: Searching documents in {len(categories)} categories")
            results = await self.doc_search.search_in_categories(
                query=enhanced_query,
                categories=categories,
                region=region,
                max_results=max_results,
            )
            
            logger.info(f"Two-stage search completed: {len(results)} results for '{query[:30]}...'")
            return results
            
        except Exception as e:
            logger.error(f"Error in two-stage search: {e}")
            return []
    
    def _enhance_query(self, query: str, context: Optional[str]) -> str:
        """
        Enhance query with conversation context.
        
        Args:
            query: Original query
            context: Conversation context
            
        Returns:
            Enhanced query string
        """
        if not context:
            return query
        
        # Simple enhancement: prepend key context terms
        # More sophisticated: use LLM to reformulate query
        context_words = context.split()[:20]  # Limit context words
        if context_words:
            return f"{' '.join(context_words)} {query}"
        
        return query
    
    async def search_direct(
        self,
        query: str,
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[SearchResult]:
        """
        Direct search without two-stage process.
        Useful for simple queries or when categories are not needed.
        
        Args:
            query: Search query
            region: Optional region filter
            max_results: Maximum results
            
        Returns:
            List of search results
        """
        return await self.doc_search.search_all(
            query=query,
            region=region,
            max_results=max_results,
        )
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check search service health.
        
        Returns:
            Health status dictionary
        """
        # Both services use the same adapter, check once
        try:
            # Try a simple lookup
            await self.index_lookup.lookup("test", max_results=1)
            return {
                "status": "healthy",
                "stages": {
                    "index_lookup": "operational",
                    "document_search": "operational",
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
