from app.services.llm_service import LLMService
from app.services.database import DatabaseService
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class ExampleAgentService:
    """Example Agent Business Logic"""
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService):
        self.llm_service = llm_service
        self.db_service = db_service
    
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
            
            # Save to database (optional)
            collection = self.db_service.get_collection(
                settings.DATABASE_NAME, 
                "example_agent_logs"
            )
            await collection.insert_one({
                "query": query,
                "response": response,
                "provider": provider
            })
            
            logger.info(f"✅ Processed query: {query[:50]}...")
            
            return {
                "result": response,
                "provider_used": provider
            }
        
        except Exception as e:
            logger.error(f"❌ Error processing query: {e}")
            raise
