# app/main.py

import os
import subprocess
from contextlib import asynccontextmanager
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Suppress TensorFlow and MediaPipe C++ logging (must be set before imports)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['ABSL_LOGGING_MIN_INFO_LEVEL'] = '3'

load_dotenv()

# Force PulseAudio/PipeWire routing for sounddevice (used by the python bot)
if os.name != 'nt':
    os.environ["PULSE_SINK"] = "BotSpeaker"
    os.environ["PULSE_SOURCE"] = "BotMic.monitor"

from app.agents.criteria_agent.router import router as criteria_router
from app.agents.example_agent.router import router as example_agent_router
from app.agents.interview.api.interview import router as interview_router
from app.agents.interview.core.startup import initialize_services as initialize_interview_services
from app.agents.jd_agent.router import router as jd_router
from app.agents.job_post_agent.router import router as job_post_agent_router
from app.agents.question_generator.router import router as question_generator_router
from app.agents.talent_matcher.router import router as talent_matcher_router
from app.agents.resume_matcher.router import router as resume_matcher_router
from app.core.config import settings
from app.core.dependencies import get_websocket_manager
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    setup_logging()

    logger.info("Starting Multi-Agent Platform...")

    try:
        initialize_interview_services()
        logger.info("Interview services initialized")
    except Exception:
        logger.exception("Failed to initialize interview services")
        raise

    logger.info("Application started successfully")

    yield

    logger.info("Shutting down...")
    logger.info("Application shut down successfully")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

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
app.include_router(job_post_agent_router, prefix="/api/v1", tags=["Job Post Agent"])
app.include_router(talent_matcher_router, prefix="/api/v1/talent_matcher", tags=["Talent Matcher Agent"])
app.include_router(resume_matcher_router, prefix="/api/v1/resume_matcher", tags=["Resume Matcher Agent"])
app.include_router(question_generator_router, prefix="/api/v1/question_generator", tags=["Question Generator Agent"])
app.include_router(interview_router, prefix="/api/v1/interview", tags=["Interview Agent"])


@app.get("/")
async def root():
    return {
        "message": "Multi-Agent Platform API",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint example."""
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
