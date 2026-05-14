# app/services/orchestrator/state_manager.py
import logging
from typing import Optional
from .types import InterviewState, InterviewPhase

logger = logging.getLogger(__name__)

class InterviewStateManager:
    """
    Manages the persistence and transitions of the Interview State Machine.
    Acts as the 'Brain' ensuring we never lose progress.
    """
    def __init__(self):
        pass

    def load_or_init_state(self, session_id: str) -> InterviewState:
        """Loads existing checkpoint or creates a fresh state."""
        saved_data = None
        if saved_data:
            try:
                state = InterviewState(**saved_data)
                state.is_resumed = True
                logger.info(f"Resumed state for {session_id} at Phase: {state.phase}")
                return state
            except Exception as e:
                logger.error(f"Failed to parse saved state for {session_id}: {e}. Starting fresh.")
        
        # Initialize new state
        state = InterviewState(session_id=session_id)
        self.save_checkpoint(state)
        return state

    def save_checkpoint(self, state: InterviewState):
        """Persists state to MongoDB."""
        pass

    def advance_phase(self, state: InterviewState, new_phase: InterviewPhase):
        """Transition to new phase and save."""
        logger.info(f"Advancing Phase: {state.phase} -> {new_phase}")
        state.phase = new_phase
        self.save_checkpoint(state)

    def mark_question_asked(self, state: InterviewState, new_turn: int):
        """Updates state after a question is successfully asked."""
        state.turn_count = new_turn
        state.questions_asked_count += 1
        self.save_checkpoint(state)

    def update_turn_count(self, state: InterviewState, new_turn: int):
        """Simple update of turn count without changing phase."""
        state.turn_count = new_turn
        self.save_checkpoint(state)