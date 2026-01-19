
# app/services/interview/tasks/background.py
import logging
import asyncio
from typing import Optional
import concurrent.futures

from app.agents.interview_agent.service_container import get_services
from app.agents.interview_agent.utils.exceptions import (ServiceInitializationError, MeetConnectionError, InterviewExecutionError)
from app.models.analysis_schemas import CombinedAnalysisReport

logger = logging.getLogger(__name__)

async def start_and_conduct_interview_task(
    session_id: str,
    candidate_id: str,
    meet_link: str,
    audio_device: Optional[int],
    enable_video: bool,
    video_capture_method: str,
    job_role: str,
    resume_content: str
):
    """Background task - Async Version for Main Loop Execution"""
    logger.info(f"[Task: {session_id}] Background task started (Async Mode)")
    
    # Get services
    services = get_services()
    db_handler = services.db_handler
    meet_session_mgr = services.meet_session_mgr
    meet_orchestrator = services.meet_orchestrator
    interview_service = services.interview_service
    combined_analyzer = services.combined_analyzer
    transcript_analyzer = services.transcript_analyzer
    
    # Check services...
    if not all([meet_session_mgr, meet_orchestrator, db_handler]):
        logger.error("Services missing in background task. Cannot proceed.")
        return 

    final_status = "error_unknown"
    snapshot_count = 0

    try:
        # 1. Start Bot
        success = meet_session_mgr.start_bot_session(
            session_id, meet_link, candidate_id, audio_device,
            enable_video, False, video_capture_method
        )
        if not success:
            await db_handler.update_session_status(session_id, "error_join_failed")
            raise MeetConnectionError(session_id, "Bot join failed")

        # 2. Wait for Candidate
        if not meet_session_mgr.wait_for_candidate(session_id, timeout=300):
            await db_handler.update_session_status(session_id, "error_candidate_no_show")
            raise InterviewExecutionError(session_id, "wait", "Candidate no-show")

        await db_handler.update_session_status(session_id, "active_interviewing")

        # 3. Video Capture
        if enable_video:
            meet_session_mgr._start_candidate_video_capture(session_id)

        # 4. Conduct Interview
        try:
            logger.info(f"[Task: {session_id}] Starting Orchestration (Main Loop)...")
            result = await meet_orchestrator.conduct_interview(session_id=session_id)
            final_status = result.get('status', 'completed_unknown')

        except Exception as e:
            raise InterviewExecutionError(session_id, "orchestration", str(e))
        
        # 5. Cleanup - GET COUNTS BEFORE ENDING SESSION
        snapshot_count = await meet_session_mgr.get_snapshot_count(session_id)
        background_person_count = meet_session_mgr.get_background_person_count(session_id)
        reconnection_count = meet_session_mgr.get_reconnection_count(session_id)
        logger.info(f"[Task: {session_id}] Counts before cleanup - snapshots: {snapshot_count}, bg_persons: {background_person_count}, reconnects: {reconnection_count}")
        
        if meet_session_mgr:
            meet_session_mgr.end_session(session_id)
            
        if interview_service:
            interview_service.end_interview_session(session_id)

        await db_handler.update_session_status(session_id, "active_analyzing")

        # 6. Retrieve Transcript (FROM DB)
        transcript_content = await db_handler.get_transcript_text(session_id)

        if not transcript_content:
            logger.warning(f"[Task: {session_id}] Transcript empty in DB.")

        # 7. Run Analyses (Async Gather)
        analysis_tasks = []
        analysis_results = {"behavioral": None, "transcript": None, "voice": None}

        # Helper wrappers for async execution of synchronous analysis methods if necessary
        # Assuming analysis methods might be sync or async. 
        # combined_analyzer methods appear effectively sync or wrapped. 
        # We will wrap them in to_thread if they are CPU bound sync functions.
        
        async def run_behavioral():
            return await asyncio.to_thread(
                combined_analyzer.perform_behavioral_analysis, 
                candidate_id, session_id
            )

        async def run_transcript():
             return await asyncio.to_thread(
                transcript_analyzer.analyze, 
                session_id
             )
        
        async def run_voice():
            return await asyncio.to_thread(
                combined_analyzer.perform_voice_authenticity_analysis,
                candidate_id, session_id
            )

        if enable_video and snapshot_count > 0:
            analysis_tasks.append(run_behavioral())
        else:
            analysis_tasks.append(asyncio.sleep(0)) # Place holder
            
        if transcript_content:
            analysis_tasks.append(run_transcript())
            analysis_tasks.append(run_voice())
        else:
             analysis_tasks.append(asyncio.sleep(0))
             analysis_tasks.append(asyncio.sleep(0))

        # We need to map results back to specific keys.
        # Let's do explicit checking.
        
        current_tasks = []
        task_types = []
        
        if enable_video and snapshot_count > 0:
            current_tasks.append(run_behavioral())
            task_types.append("behavioral")
            
        if transcript_content:
            current_tasks.append(run_transcript())
            task_types.append("transcript")
            current_tasks.append(run_voice())
            task_types.append("voice")
            
        if current_tasks:
            results = await asyncio.gather(*current_tasks, return_exceptions=True)
            
            for i, res in enumerate(results):
                t_type = task_types[i]
                if isinstance(res, Exception):
                    logger.error(f"Analysis task {t_type} failed: {res}")
                else:
                    analysis_results[t_type] = res

        # 8. Combine & Save (TO DB)
        try:
            # combine_analyses might be sync or async. Assuming it needs thread if sync CPU bound.
            combined_report = await asyncio.to_thread(
                combined_analyzer.combine_analyses,
                behavioral_result=analysis_results.get("behavioral"),
                transcript_result=analysis_results.get("transcript"),
                voice_result=analysis_results.get("voice"),
                session_id=session_id,
                candidate_id=candidate_id,
                background_person_count=background_person_count,
                reconnection_count=reconnection_count
            )
            
            if combined_report:
                logger.info(f"[Task: {session_id}] Analysis completed and saved.")
                await db_handler.update_session_status(session_id, "completed")
            else:
                logger.error(f"[Task: {session_id}] CombinedAnalyzer returned None.")
                await db_handler.update_session_status(session_id, "error_analysis_empty")

        except Exception as e:
            logger.error(f"[Task: {session_id}] Combine failed: {e}", exc_info=True)
            await db_handler.update_session_status(session_id, "error_analysis_failed")

    except Exception as e:
        logger.error(f"FATAL ERROR [Task: {session_id}]: {e}", exc_info=True)
        if db_handler:
            try:
                await db_handler.update_session_status(session_id, "error_fatal")
            except: pass
    finally:
        # Emergency Cleanup
        try:
            if meet_session_mgr: meet_session_mgr.end_session(session_id)
        except: pass
