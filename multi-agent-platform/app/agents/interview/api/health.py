# app/api/health.py
import logging
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.agents.interview.core.startup import get_services

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
async def health_check():
    services = get_services()
    
    is_healthy = all([
        services.db_handler,
        services.interview_service,
        services.stt_service,
        services.tts_service
    ])
    
    return {"status": "healthy" if is_healthy else "degraded"}

@router.get("/health/detailed", status_code=status.HTTP_200_OK)
async def detailed_health_check():
    services = get_services()
    
    services_status = {
        "db_handler": services.db_handler is not None,
        "interview_service": services.interview_service is not None,
        "meet_manager": services.meet_session_mgr is not None,
        "stt_service": services.stt_service is not None,
        "tts_service": services.tts_service is not None
    }
    
    if not all(services_status.values()):
        raise HTTPException(
            status_code=503,
            detail={"status": "down", "details": services_status}
        )

    async def check_db():
        if hasattr(services.db_handler, 'check_connection'):
            return services.db_handler.check_connection()
        return True

    async def check_llm():
        if services.combined_analyzer and hasattr(services.combined_analyzer, 'check_health'):
            return services.combined_analyzer.check_health()
        return True

    async def check_stt():
        if services.stt_service:
            return await asyncio.to_thread(services.stt_service.check_health)
        return False

    async def check_tts():
        if services.tts_service:
            return await asyncio.to_thread(services.tts_service.check_health)
        return False

    async def check_disk_write():
        try:
            test_path = Path("data") / ".healthcheck"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.touch()
            test_path.unlink()
            return True
        except Exception:
            return False

    db_ok, llm_ok, disk_ok, stt_ok, tts_ok = await asyncio.gather(
        check_db(), check_llm(), check_disk_write(), check_stt(), check_tts()
    )

    health_report = {
        "status": "healthy",
        "components": {
            "database": "connected" if db_ok else "disconnected",
            "llm_api": "operational" if llm_ok else "error",
            "stt_v2": "operational" if stt_ok else "error",
            "tts": "operational" if tts_ok else "error",
            "disk_storage": "writable" if disk_ok else "read-only"
        }
    }

    if not (db_ok and llm_ok and disk_ok and stt_ok and tts_ok):
        health_report["status"] = "degraded"
        return JSONResponse(status_code=503, content=health_report)

    return health_report