# app/services/participant_monitor.py

import logging
import re
import asyncio
from typing import Optional, Callable
from collections import Counter

from app.agents.interview.config.constants import (
    ParticipantThresholds,
    LoggingConfig
)

logger = logging.getLogger(__name__)

class ParticipantMonitor:

    def __init__(
        self,
        session_id: str,
        meet_controller,
        stop_event: asyncio.Event,
        # Callback now accepts (count, violation_type, details)
        on_violation: Optional[Callable[[int, str, list], None]] = None,
        bot_name: str = "AI Bot" # Pass bot name to exclude from checks
    ):
        self.session_id = session_id
        self.meet = meet_controller
        self.stop_event = stop_event
        self.on_violation = on_violation
        self.bot_name = bot_name

        self.monitor_task: Optional[asyncio.Task] = None
        self.violation_detected = False
        self.total_checks = 0

    def start_monitoring(self):
        if self.monitor_task and not self.monitor_task.done(): return
        self.monitor_task = asyncio.create_task(
            self._monitoring_loop(),
            name=f"ParticipantMonitor-{self.session_id}"
        )

    def stop_monitoring(self):
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()

    async def _monitoring_loop(self):
        check_interval = LoggingConfig.PARTICIPANT_CHECK_LOG_INTERVAL_SEC

        while not self.stop_event.is_set():
            try:
                self.total_checks += 1
                current_count = await self.meet.get_participant_count()

                if self.total_checks % 10 == 0:
                    logger.debug(f"Participant Check: {current_count}")
                    
                if current_count == -1:
                    logger.info("Browser connection closed. Stopping monitor without violation.")
                    break

                if current_count < ParticipantThresholds.MIN_VALID_COUNT:
                    logger.warning(f"Candidate disconnected detected in monitoring loop. Count: {current_count}")
                    self._handle_violation(current_count, "candidate_disconnected", [])
                    break

                if current_count > ParticipantThresholds.MAX_VALID_COUNT:
                    raw_names = await self.meet.get_active_participant_names()

                    candidate_names = [
                        n for n in raw_names
                        if self.bot_name.lower() not in n.lower() and "ai bot" not in n.lower()
                    ]

                    # Log what we found to help debugging
                    logger.info(f"Checking participants: {candidate_names}")

                    # If after filtering we have <= 1 candidate name (meaning the others were icons/artifacts), ignore
                    # But if count > 2, we must have found *something*.

                    violation_type = self._analyze_violation_type(candidate_names)

                    logger.info(f"Anomaly Detected: {violation_type} | Names: {candidate_names}")
                    self._handle_violation(current_count, violation_type, candidate_names)
                    break

                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=check_interval)
                    break
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=check_interval)
                    break
                except asyncio.TimeoutError:
                    pass

    def _analyze_violation_type(self, names: list) -> str:
        """
        Classifies violation.
        Names should now be clean: e.g. ["John Doe", "devices"] or ["John Doe", "John Doe"]
        """
        normalized_names = []
        companion_signal = False

        for n in names:
            lower = n.lower()
            
            # Explicit Companion Signals
            if "companion" in lower or "devices" in lower:
                companion_signal = True
                
                # If it's the "devices" tile, we don't treat it as a unique name string for the counter,
                # effectively assuming it belongs to the primary user.
                if "devices" in lower:
                    continue 

                # If it's "Name (Companion)", clean it to "Name" for duplicate checking
                clean = re.sub(r'\s*\(Companion\)', '', n, flags=re.IGNORECASE).strip()
                normalized_names.append(clean)
            else:
                normalized_names.append(n)
        
        # Check for explicit name duplicates
        counts = Counter(normalized_names)
        has_duplicates = any(c > 1 for c in counts.values())

        if has_duplicates or companion_signal:
            return "companion_mode_detected"
        
        return "unauthorized_person"
    
    def _handle_violation(self, count: int, violation_type: str, names: list):
        if self.violation_detected: return
        
        self.violation_detected = True
        logger.critical(f"VIOLATION: {violation_type} | Count: {count} | Names: {names}")
        
        if self.on_violation:
            try:
                self.on_violation(count, violation_type, names)
            except Exception as e:
                logger.error(f"Error in violation callback: {e}")
        else:
            self.stop_event.set()

    def get_status(self) -> dict:
        return {
            'active': self.monitor_task is not None and not self.monitor_task.done(),
            'violation': self.violation_detected
        }
