from app.services.llm_service import LLMService
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class ExampleAgentService:
    """Example Agent Business Logic"""
    
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
    
    async def process_query(
        self, 
        query: str, 
        context: str = None,
        provider: str = "gemini"
    ) -> dict:
        """
        Process user query
        
        Args:
            query: User query
            context: Additional context
            provider: LLM provider to use
        """
        try:
            # Build prompt
            prompt = f"Query: {query}"
            if context:
                prompt += f"\nContext: {context}"
            
            # Generate response using LLM
            response = await self.llm_service.generate(
                prompt=prompt,
                provider=provider
            )
            
            logger.info(f" Processed query: {query[:50]}...")
            
            return {
                "result": response,
                "provider_used": provider
            }
        
        except Exception as e:
            logger.error(f"❌ Error processing query: {e}")
            raise