# app/main.py

# STEP 1: Load environment variables at the very top
from dotenv import load_dotenv
load_dotenv()

# --- Standard Library Imports ---
from contextlib import asynccontextmanager
import logging

# --- Third-Party Imports ---
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# --- Application-Specific Imports ---
from app.core.config import settings
from app.services.database import DatabaseService
from app.core.dependencies import get_websocket_manager

# Import agent routers
from app.agents.jd_agent.router import router as jd_router
from app.agents.example_agent.router import router as example_agent_router
from app.agents.criteria_agent.router import router as criteria_router
from app.agents.job_post_agent.router import router as job_post_agent_router
from app.agents.talent_matcher.router import router as talent_matcher_router


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting Multi-Agent Platform...")
    await DatabaseService.connect_db(settings.MONGODB_URL)
    logger.info("✅ Application started successfully")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    await DatabaseService.close_db()
    logger.info("✅ Application shut down successfully")


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


app.include_router(example_agent_router, prefix="/api/v1/example", tags=["Example Agent"])
app.include_router(jd_router, prefix="/api/v1/jd", tags=["Job Description Agent"])
app.include_router(criteria_router, prefix="/api/v1/criteria", tags=["Candidate Criteria Agent"])
app.include_router(job_post_agent_router,prefix="/api/v1", tags=["Job Post Agent"])
app.include_router(talent_matcher_router,prefix="/api/v1/talent_matcher", tags=["Talent Matcher Agent"])


@app.get("/")
async def root():
    return {
        "message": "Multi-Agent Platform API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


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