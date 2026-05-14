# app/utils/audio_file_utils.py
import logging
import soundfile as sf
import numpy as np
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

def get_user_audio_path_for_stt(
    session_id: str, 
    turn_count: int, 
    is_follow_up: bool = False
) -> Path:
    """
    Generates a standardized Path object for saving a candidate's STT audio.
    Ensures the directory structure exists.
    """
    audio_dir = Path("data") / session_id / "audio"
    
    # Ensure the directory exists
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    suffix = "_followup" if is_follow_up else ""
    path_24k_stt = audio_dir / f"candidate_turn_{turn_count}{suffix}_stt_24k.wav"
    return path_24k_stt

def save_audio_file(
    audio_data: np.ndarray, 
    file_path: Union[str, Path], 
    samplerate: int
):
    """
    Saves the provided numpy audio data to a file using soundfile.
    """
    try:
        # Ensure file_path is a string for the sf.write function if needed,
        # though Path objects are generally supported.
        sf.write(
            str(file_path), 
            audio_data.flatten(), 
            samplerate, 
            format='WAV', 
            subtype='PCM_16'
        )
        logger.debug(f"Successfully saved audio to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save audio file to {file_path}: {e}", exc_info=True)
