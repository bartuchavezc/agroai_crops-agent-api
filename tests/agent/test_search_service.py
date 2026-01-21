# tests/agent/test_search_service.py
"""
Tests for TwoStageSearchService logic.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass
from typing import List, Optional

from src.agent.search.search_service import TwoStageSearchService
from src.agent.search.interfaces import SearchResult


@dataclass
class MockSummary:
    """Mock summary for index lookup."""
    category: str
    score: float = 0.9


@pytest.fixture
def mock_index_lookup():
    """Create mock index lookup service."""
    return AsyncMock()


@pytest.fixture
def mock_doc_search():
    """Create mock document search service."""
    return AsyncMock()


@pytest.fixture
def search_service(mock_index_lookup, mock_doc_search):
    """Create TwoStageSearchService with mocked dependencies."""
    return TwoStageSearchService(
        index_lookup=mock_index_lookup,
        doc_search=mock_doc_search,
    )


class TestTwoStageSearchService:
    """Tests for TwoStageSearchService."""

    def test_enhance_query_prepends_context(self, search_service):
        """Test that context words are prepended to query."""
        query = "enfermedad en hojas"
        context = "cultivo de soja en zona pampeana con humedad alta"
        
        enhanced = search_service._enhance_query(query, context)
        
        # Context words should come before the query
        assert enhanced.startswith("cultivo")
        assert "enfermedad en hojas" in enhanced

    def test_enhance_query_returns_original_when_no_context(self, search_service):
        """Test that query is unchanged when context is None."""
        query = "plagas en maíz"
        
        enhanced = search_service._enhance_query(query, None)
        
        assert enhanced == query

    def test_enhance_query_limits_context_words(self, search_service):
        """Test that context is limited to first 20 words."""
        query = "test"
        long_context = " ".join([f"word{i}" for i in range(50)])  # 50 words
        
        enhanced = search_service._enhance_query(query, long_context)
        
        # Should have 20 context words + query
        context_part = enhanced.replace(" test", "")
        assert len(context_part.split()) == 20

    @pytest.mark.asyncio
    async def test_search_falls_back_to_all_when_no_categories(
        self, search_service, mock_index_lookup, mock_doc_search
    ):
        """When index lookup returns no categories, search_all is called."""
        mock_index_lookup.lookup.return_value = []  # No summaries/categories
        mock_doc_search.search_all.return_value = [
            SearchResult(id="1", title="Doc 1", content="...", score=0.8)
        ]
        
        results = await search_service.search("test query")
        
        mock_doc_search.search_all.assert_called_once()
        mock_doc_search.search_in_categories.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_uses_categories_from_index_lookup(
        self, search_service, mock_index_lookup, mock_doc_search
    ):
        """When index lookup returns categories, search_in_categories is used."""
        mock_index_lookup.lookup.return_value = [
            MockSummary(category="pest"),
            MockSummary(category="disease"),
        ]
        mock_doc_search.search_in_categories.return_value = []
        
        await search_service.search("plaga en cultivo")
        
        mock_doc_search.search_in_categories.assert_called_once()
        call_args = mock_doc_search.search_in_categories.call_args
        assert "pest" in call_args.kwargs["categories"]
        assert "disease" in call_args.kwargs["categories"]

    @pytest.mark.asyncio
    async def test_search_direct_bypasses_index_lookup(
        self, search_service, mock_index_lookup, mock_doc_search
    ):
        """search_direct should skip index lookup and go straight to search_all."""
        mock_doc_search.search_all.return_value = []
        
        await search_service.search_direct("direct query", region="AR")
        
        mock_index_lookup.lookup.assert_not_called()
        mock_doc_search.search_all.assert_called_once_with(
            query="direct query",
            region="AR",
            max_results=10,
        )

    @pytest.mark.asyncio
    async def test_search_handles_exception_gracefully(
        self, search_service, mock_index_lookup
    ):
        """Search should return empty list on exception, not crash."""
        mock_index_lookup.lookup.side_effect = Exception("Connection error")
        
        results = await search_service.search("test")
        
        assert results == []
