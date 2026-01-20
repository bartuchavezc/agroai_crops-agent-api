# src/agent/search/elastic_adapter.py
"""
Elasticsearch/OpenSearch adapter for document search.

Provides the underlying search functionality for both
index lookup and document search stages.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ElasticSearchAdapter:
    """
    Adapter for Elasticsearch/OpenSearch operations.
    
    Handles:
    - Connection management
    - Index operations
    - Text search queries
    - Document CRUD operations
    """
    
    def __init__(
        self,
        hosts: List[str],
        index_summaries: str = "agro_summaries",
        index_documents: str = "agro_documents",
        timeout: int = 30,
    ):
        """
        Initialize Elasticsearch adapter.
        
        Args:
            hosts: List of Elasticsearch hosts
            index_summaries: Name of summaries index
            index_documents: Name of documents index
            timeout: Request timeout in seconds
        """
        self.hosts = hosts
        self.index_summaries = index_summaries
        self.index_documents = index_documents
        self.timeout = timeout
        self._client = None
    
    async def _get_client(self):
        """Get or create Elasticsearch client."""
        if self._client is None:
            try:
                from elasticsearch import AsyncElasticsearch
                self._client = AsyncElasticsearch(
                    hosts=self.hosts,
                    timeout=self.timeout,
                )
                logger.info(f"Connected to Elasticsearch: {self.hosts}")
            except ImportError:
                logger.warning("elasticsearch-py not installed, using mock client")
                self._client = MockElasticClient()
        return self._client
    
    async def search_summaries(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search the summaries index.
        
        Args:
            query: Search query
            max_results: Maximum results
            
        Returns:
            List of summary documents
        """
        client = await self._get_client()
        
        try:
            body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["category^3", "keywords^2", "description"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                },
                "size": max_results,
            }
            
            response = await client.search(
                index=self.index_summaries,
                body=body,
            )
            
            results = []
            for hit in response.get("hits", {}).get("hits", []):
                doc = hit["_source"]
                doc["id"] = hit["_id"]
                doc["relevance_score"] = hit["_score"]
                results.append(doc)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching summaries: {e}")
            return []
    
    async def search_documents(
        self,
        query: str,
        categories: Optional[List[str]] = None,
        region: Optional[str] = None,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search the documents index.
        
        Args:
            query: Search query
            categories: Optional category filter
            region: Optional region filter
            max_results: Maximum results
            
        Returns:
            List of documents
        """
        client = await self._get_client()
        
        try:
            # Build query
            must_clauses = [
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^3", "content^2", "keywords"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                }
            ]
            
            filter_clauses = []
            
            if categories:
                filter_clauses.append({
                    "terms": {"category": categories}
                })
            
            if region:
                filter_clauses.append({
                    "bool": {
                        "should": [
                            {"term": {"region": region}},
                            {"term": {"region": "global"}},  # Always include global docs
                        ]
                    }
                })
            
            body = {
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "filter": filter_clauses if filter_clauses else None,
                    }
                },
                "size": max_results,
                "highlight": {
                    "fields": {
                        "content": {"fragment_size": 200, "number_of_fragments": 3}
                    }
                }
            }
            
            # Remove None filter
            if body["query"]["bool"]["filter"] is None:
                del body["query"]["bool"]["filter"]
            
            response = await client.search(
                index=self.index_documents,
                body=body,
            )
            
            results = []
            for hit in response.get("hits", {}).get("hits", []):
                doc = hit["_source"]
                doc["id"] = hit["_id"]
                doc["score"] = hit["_score"]
                
                # Include highlights if available
                if "highlight" in hit:
                    doc["highlights"] = hit["highlight"].get("content", [])
                
                results.append(doc)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return []
    
    async def index_document(
        self,
        index: str,
        doc_id: str,
        document: Dict[str, Any],
    ) -> bool:
        """
        Index a document.
        
        Args:
            index: Index name
            doc_id: Document ID
            document: Document data
            
        Returns:
            True if successful
        """
        client = await self._get_client()
        
        try:
            await client.index(
                index=index,
                id=doc_id,
                body=document,
            )
            return True
        except Exception as e:
            logger.error(f"Error indexing document: {e}")
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Elasticsearch health."""
        try:
            client = await self._get_client()
            info = await client.info()
            
            return {
                "status": "healthy",
                "cluster_name": info.get("cluster_name", "unknown"),
                "version": info.get("version", {}).get("number", "unknown"),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
    
    async def close(self):
        """Close the client connection."""
        if self._client:
            await self._client.close()
            self._client = None


class MockElasticClient:
    """
    Mock Elasticsearch client for development/testing.
    Returns empty results but doesn't fail.
    """
    
    async def search(self, index: str, body: dict) -> dict:
        """Mock search returning empty results."""
        logger.debug(f"Mock search on {index}: {body.get('query', {})}")
        return {"hits": {"hits": [], "total": {"value": 0}}}
    
    async def index(self, index: str, id: str, body: dict) -> dict:
        """Mock index operation."""
        logger.debug(f"Mock index to {index}: {id}")
        return {"result": "created"}
    
    async def info(self) -> dict:
        """Mock cluster info."""
        return {
            "cluster_name": "mock-cluster",
            "version": {"number": "0.0.0-mock"}
        }
    
    async def close(self):
        """Mock close."""
        pass
