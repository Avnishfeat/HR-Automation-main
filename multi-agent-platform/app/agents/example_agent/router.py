from fastapi import APIRouter, Depends, HTTPException
from app.agents.example_agent.schemas import ExampleAgentRequest, ExampleAgentResponse
from app.agents.example_agent.service import ExampleAgentService
from app.core.dependencies import get_llm_service, get_db_service
from app.utils.response import APIResponse

router = APIRouter(prefix="/example-agent", tags=["Example Agent"])

@router.post("/query", response_model=ExampleAgentResponse)
async def process_query(
    request: ExampleAgentRequest,
    llm_service = Depends(get_llm_service),
    db_service = Depends(get_db_service)
):
    """
    Process a query using the example agent
    """
    try:
        service = ExampleAgentService(llm_service, db_service)
        result = await service.process_query(
            query=request.query,
            context=request.context,
            provider=request.use_provider
        )
        
        return ExampleAgentResponse(
            result=result["result"],
            provider_used=result["provider_used"]
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return APIResponse.success({"status": "healthy"})
