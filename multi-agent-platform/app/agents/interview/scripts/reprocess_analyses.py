# app/scripts/reprocess_analyses.py
import asyncio
import logging
from pathlib import Path

from app.agents.interview.services.analysis.combined_analyzer import CombinedAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AnalysisRecovery")


async def reprocess_pending_sessions(data_root: str = "data"):
    """Rebuild missing final reports from local stateless session folders."""
    analyzer = CombinedAnalyzer()
    root = Path(data_root)
    if not root.exists():
        logger.info("No data directory found.")
        return

    sessions = [path for path in root.iterdir() if path.is_dir() and (path / "transcript.txt").exists()]
    pending = [
        path for path in sessions
        if not (path / "reports" / "final_screening_report.json").exists()
    ]

    if not pending:
        logger.info("No pending local analyses found.")
        return

    logger.info("Found %s sessions pending analysis. Starting recovery...", len(pending))
    for session_dir in pending:
        session_id = session_dir.name
        try:
            logger.info("Reprocessing %s...", session_id)
            await asyncio.to_thread(
                analyzer.combine_analyses,
                None,
                None,
                None,
                session_id,
            )
        except Exception as e:
            logger.error("Failed to recover %s: %s", session_id, e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(reprocess_pending_sessions())
