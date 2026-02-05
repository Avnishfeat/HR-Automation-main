from dotenv import load_dotenv
load_dotenv()

# Standard Library Imports 
from contextlib import asynccontextmanager
import logging

# Third-Party Imports 
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware

# Application-Specific Imports
from app.core.config import settings
from app.services.database import DatabaseService
from app.core.dependencies import get_websocket_manager


# Import agent routers
from app.agents.jd_agent.router import router as jd_router
from app.agents.example_agent.router import router as example_agent_router
from app.agents.criteria_agent.router import router as criteria_router
from app.agents.job_post_agent.router import router as job_post_agent_router
from app.agents.talent_matcher.router import router as talent_matcher_router
from app.agents.question_generator.router import router as question_generator_router
from app.agents.interview.api.interview import router as interview_router
from app.agents.interview.core.startup import initialize_services as initialize_interview_services

# Security imports
from app.core.dependencies import get_current_user
from app.routers import auth as auth_router
from app.services.user_service import UserService

# Setup logging
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Initialize global logging (masks secrets)
    setup_logging()
    
    # Startup
    logger.info("Starting Multi-Agent Platform...")
    await DatabaseService.connect_db(settings.MONGODB_URL)
    
    # --- NEW: Ensure Unique Email Index ---
    # This runs once on startup to tell MongoDB: "Never allow duplicate emails"
    try:
        user_service = UserService()
        await user_service.ensure_indexes()
    except Exception as e:
        logger.error(f"Failed to create database indexes: {e}")

    # Initialize Interview Services
    try:
        initialize_interview_services()
        logger.info("Interview Services initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Interview Services: {e}")
    
    logger.info("Application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await DatabaseService.close_db()
    logger.info("Application shut down successfully")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router
app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Authentication"])

@app.get("/")
async def root():
    return {
        "message": "Multi-Agent Platform API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }

# Protected Routes - Requires Authentication
protected_deps = [Depends(get_current_user)]

app.include_router(
    example_agent_router, 
    prefix="/api/v1/example", 
    tags=["Example Agent"],
    dependencies=protected_deps
    )

app.include_router(
    jd_router, 
    prefix="/api/v1/jd", 
    tags=["Job Description Agent"], 
    dependencies=protected_deps
    )

app.include_router(
    criteria_router, 
    prefix="/api/v1/criteria", 
    tags=["Candidate Criteria Agent"],
    dependencies=protected_deps
    )

app.include_router(
    job_post_agent_router,
    prefix="/api/v1", 
    tags=["Job Post Agent"], 
    dependencies=protected_deps
    )

app.include_router(
    talent_matcher_router,
    prefix="/api/v1/talent_matcher", 
    tags=["Talent Matcher Agent"],
    dependencies=protected_deps
    )

app.include_router(
    question_generator_router,
    prefix="/api/v1/question_generator", 
    tags=["Question Generator Agent"],
    dependencies=protected_deps
    )

app.include_router(
    interview_router, 
    prefix="/api/v1/interview", 
    tags=["Interview Agent"], 
    dependencies=protected_deps
    )

# WebSocket example endpoint
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint example"""
    manager = get_websocket_manager()
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_message(f"Echo: {data}", client_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, client_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.APP_PORT, reload=settings.DEBUG)