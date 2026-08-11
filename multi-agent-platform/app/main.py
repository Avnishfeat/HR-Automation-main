# app/main.py

import os
import subprocess
import asyncio
from contextlib import asynccontextmanager
import logging
import sys

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
from app.agents.interview.api.health import router as interview_health_router
from app.agents.interview.core.startup import (
    get_services,
    initialize_services as initialize_interview_services,
)
from app.agents.interview.core.cleanup import start_cleanup_task, stop_cleanup_task
from app.agents.interview.core.task_registry import drain_interview_tasks
from app.agents.interview.core.maintenance import run_local_retention_cleanup
from app.agents.interview.services.audio.linux_audio import (
    configure_chromium_virtual_source,
    setup_linux_audio,
)
from app.utils.webhook_outbox import deliver_due_webhooks_async
from app.agents.jd_agent.router import router as jd_router
from app.agents.job_post_agent.router import router as job_post_agent_router
from app.agents.question_generator.router import router as question_generator_router
from app.agents.talent_matcher.router import router as talent_matcher_router
from app.agents.resume_matcher.router import router as resume_matcher_router
from app.core.config import settings
from app.core.dependencies import get_websocket_manager
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


async def _monitor_linux_audio() -> None:
    """Restore virtual devices when PipeWire/Pulse restarts after API startup."""
    try:
        interval_seconds = max(5, int(os.getenv("LINUX_AUDIO_RECOVERY_INTERVAL_SECONDS", "15")))
    except ValueError:
        interval_seconds = 15
        logger.warning("Invalid LINUX_AUDIO_RECOVERY_INTERVAL_SECONDS; using %s seconds", interval_seconds)

    while True:
        await asyncio.sleep(interval_seconds)
        if setup_linux_audio(max_retries=1, retry_delay_seconds=0):
            configure_chromium_virtual_source()


async def _monitor_webhook_outbox() -> None:
    """Deliver persisted completion notifications without blocking interviews."""
    while True:
        try:
            summary = await deliver_due_webhooks_async(max_events=5)
            if summary["delivered"] or summary["retried"] or summary["failed"]:
                logger.info(f"Webhook outbox delivery summary: {summary}")
        except Exception:
            logger.exception("Webhook outbox delivery pass failed")
        await asyncio.sleep(15)


async def _monitor_local_retention() -> None:
    """Prune only terminal local artifacts on a low-frequency maintenance loop."""
    try:
        interval_seconds = max(300, int(os.getenv("LOCAL_RETENTION_CLEANUP_INTERVAL_SECONDS", "3600")))
    except ValueError:
        interval_seconds = 3600
        logger.warning("Invalid LOCAL_RETENTION_CLEANUP_INTERVAL_SECONDS; using %s seconds", interval_seconds)

    while True:
        try:
            summary = await asyncio.to_thread(run_local_retention_cleanup)
            logger.info(f"Local retention cleanup summary: {summary}")
        except Exception:
            logger.exception("Local retention cleanup failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    setup_logging()

    logger.info("Starting Multi-Agent Platform...")

    try:
        initialize_interview_services()
        await start_cleanup_task()
        logger.info("Interview services initialized")
    except Exception:
        logger.exception("Failed to initialize interview services")
        raise

    audio_recovery_task = None
    webhook_outbox_task = asyncio.create_task(_monitor_webhook_outbox(), name="webhook-outbox")
    retention_task = asyncio.create_task(_monitor_local_retention(), name="local-retention")
    if sys.platform.startswith("linux"):
        audio_recovery_task = asyncio.create_task(
            _monitor_linux_audio(), name="linux-audio-recovery"
        )

    logger.info("Application started successfully")

    try:
        yield
    finally:
        if audio_recovery_task:
            audio_recovery_task.cancel()
            try:
                await audio_recovery_task
            except asyncio.CancelledError:
                pass

        services = get_services()
        if services.meet_session_mgr:
            for session_id in list(services.meet_session_mgr.get_all_active_sessions()):
                services.meet_session_mgr.request_session_stop(session_id)
        await drain_interview_tasks()

        webhook_outbox_task.cancel()
        try:
            await webhook_outbox_task
        except asyncio.CancelledError:
            pass
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
        await stop_cleanup_task()

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
app.include_router(interview_health_router, prefix="/api/v1/interview", tags=["Interview Health"])


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
