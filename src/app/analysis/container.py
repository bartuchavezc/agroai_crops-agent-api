"""
Dependency injection container for the analysis module.
"""
from dependency_injector import containers, providers

from .infrastructure.segmenter.unet_segmenter_repository import UNetRepository
from .infrastructure.captioner.blip_container_repository import BlipContainerRepository
from .infrastructure.llm_reasoning.mistral_reasoning_repository import MistralRepository
from .service.segmenter import SegmenterService
from .service.captioner import CaptionerService
from .service.reasoning import ReasoningService


class AnalysisContainer(containers.DeclarativeContainer):
    """Container for analysis-related services."""

    # Configuration
    # This 'config' will be populated with the 'analysis_services' dictionary
    # from the main container (e.g., config.unet, config.blip, config.reasoning_llm)
    config = providers.Configuration()
    
    # Repositories
    segmenter_repository = providers.Singleton(
        UNetRepository,
        model_endpoint=config.unet.model_endpoint
    )
    
    captioner_repository = providers.Singleton(
        BlipContainerRepository, # Assuming this is the intended one based on config.blip_container
        service_url=config.blip_container.service_url,
        timeout=config.blip_container.timeout,
        # If BlipContainerRepository needs to know if it should be used:
        # use_container=config.blip_container.use_container
    )
    
    reasoner_repository = providers.Singleton(
        MistralRepository,
        model_name=config.reasoning_llm.model_name, # Changed from config.llm
        ollama_endpoint=config.reasoning_llm.ollama_endpoint, # Changed from config.llm
        max_tokens=config.reasoning_llm.max_tokens, # Changed from config.llm
        temperature=config.reasoning_llm.temperature, # Changed from config.llm
        system_prompt=config.reasoning_llm.system_prompt, # Changed from config.llm
        # Add prompt_template if MistralRepository uses it
        # prompt_template=config.reasoning_llm.prompt_template 
    )
    
    # Services
    segmenter_service = providers.Singleton(
        SegmenterService,
        repository=segmenter_repository
    )
    
    captioner_service = providers.Singleton(
        CaptionerService,
        repository=captioner_repository
    )
    
    reasoner_service = providers.Singleton(
        ReasoningService,
        repository=reasoner_repository
    )
    
