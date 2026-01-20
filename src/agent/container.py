# src/agent/container.py
"""
Dependency injection container for the Agent layer.
"""
from dependency_injector import containers, providers

from .conversation.agent_service import AgentService
from .conversation.memory_manager import MemoryManager
from .search.elastic_adapter import ElasticSearchAdapter
from .search.index_lookup import IndexLookupService
from .search.doc_search import DocumentSearchService
from .search.search_service import TwoStageSearchService
from .reasoning.llm_service import LLMService
from .reasoning.rules_engine import RulesEngine
from .reasoning.diagnosis_service import DiagnosisService


class AgentContainer(containers.DeclarativeContainer):
    """Container for agent-related services."""
    
    # Configuration (will be provided by parent container)
    config = providers.Configuration()
    
    # ============================================
    # SEARCH LAYER
    # ============================================
    
    elastic_adapter = providers.Singleton(
        ElasticSearchAdapter,
        hosts=config.search.elasticsearch.hosts,
        index_summaries=config.search.elasticsearch.index_summaries,
        index_documents=config.search.elasticsearch.index_documents,
    )
    
    index_lookup = providers.Singleton(
        IndexLookupService,
        elastic_adapter=elastic_adapter,
    )
    
    doc_search = providers.Singleton(
        DocumentSearchService,
        elastic_adapter=elastic_adapter,
    )
    
    search_service = providers.Singleton(
        TwoStageSearchService,
        index_lookup=index_lookup,
        doc_search=doc_search,
    )
    
    # ============================================
    # REASONING LAYER
    # ============================================
    
    llm_service = providers.Factory(
        LLMService,
        model_name=config.agent_llm.model_name,
        ollama_endpoint=config.agent_llm.ollama_endpoint,
        max_tokens=config.chat_llm.max_tokens,
        temperature=config.chat_llm.temperature,
    )
    
    rules_engine = providers.Singleton(RulesEngine)
    
    diagnosis_service = providers.Factory(
        DiagnosisService,
        llm_service=llm_service,
        rules_engine=rules_engine,
    )
    
    # ============================================
    # CONVERSATION LAYER
    # ============================================
    
    agent_service = providers.Factory(
        AgentService,
        llm_service=llm_service,
        search_service=search_service,
        reasoning_service=diagnosis_service,
        system_prompt=config.agent_llm.system_prompt,
        max_memory_turns=10,
    )
