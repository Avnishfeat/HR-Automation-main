# app/api/health.py
import logging
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.agents.interview.core.startup import get_services
from app.agents.interview.core.limiter import get_concurrency_limiter
from app.agents.interview.core.task_registry import active_task_count
from app.agents.interview.core.maintenance import get_maintenance_status
from app.agents.interview.services.audio.linux_audio import linux_audio_ready
from app.utils.webhook_outbox import get_outbox_status

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
async def health_check():
    services = get_services()
    
    is_healthy = all([
        services.interview_service,
        services.meet_session_mgr,
        services.combined_analyzer,
        services.stt_service,
        services.tts_service
    ])
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "active_interview_tasks": active_task_count(),
        "webhook_outbox": get_outbox_status(),
    }

@router.get("/health/detailed", status_code=status.HTTP_200_OK)
async def detailed_health_check():
    services = get_services()
    
    services_status = {
        "interview_service": services.interview_service is not None,
        "combined_analyzer": services.combined_analyzer is not None,
        "meet_manager": services.meet_session_mgr is not None,
        "stt_service": services.stt_service is not None,
        "tts_service": services.tts_service is not None
    }
    
    if not all(services_status.values()):
        raise HTTPException(
            status_code=503,
            detail={"status": "down", "details": services_status}
        )

    async def check_llm():
        if services.combined_analyzer and hasattr(services.combined_analyzer, 'check_health'):
            return services.combined_analyzer.check_health()
        return True

    async def check_stt():
        if services.stt_service:
            if hasattr(services.stt_service, 'check_health'):
                return await asyncio.to_thread(services.stt_service.check_health)
            return True
        return False

    async def check_tts():
        if services.tts_service:
            if hasattr(services.tts_service, 'check_health'):
                return await asyncio.to_thread(services.tts_service.check_health)
            return True
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

    llm_ok, disk_ok, stt_ok, tts_ok, audio_ok = await asyncio.gather(
        check_llm(), check_disk_write(), check_stt(), check_tts(), asyncio.to_thread(linux_audio_ready)
    )
    concurrency_limiter = get_concurrency_limiter()

    health_report = {
        "status": "healthy",
        "components": {
            "llm_api": "operational" if llm_ok else "error",
            "stt_v2": "operational" if stt_ok else "error",
            "tts": "operational" if tts_ok else "error",
            "disk_storage": "writable" if disk_ok else "read-only",
            "linux_audio": "operational" if audio_ok else "error",
        },
        "runtime": {
            "active_interview_tasks": active_task_count(),
            "active_sessions": len(services.meet_session_mgr.get_all_active_sessions()) if services.meet_session_mgr else 0,
            "max_sessions": concurrency_limiter.max_sessions if concurrency_limiter else None,
            "webhook_outbox": get_outbox_status(),
            "local_retention": get_maintenance_status(),
        },
    }

    if not (llm_ok and disk_ok and stt_ok and tts_ok and audio_ok):
        health_report["status"] = "degraded"
        return JSONResponse(status_code=503, content=health_report)

    return health_report
