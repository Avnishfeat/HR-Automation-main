# app/services/audio_handler.py
"""
Audio Handler - Enhanced with fast interruption for malpractice detection.
Handles audio playback with unified processing logic and responsive stop event checking.
"""

import logging
import sounddevice as sd
import numpy as np
import queue
import threading
import audioop
import soundfile as sf
from pathlib import Path
from typing import Union, Optional, Callable, Iterator

from app.agents.interview.infrastructure.selenium.meet_controller import MeetController
from app.agents.interview.config.constants import AudioConfig

logger = logging.getLogger(__name__)


class AudioHandler:
    def __init__(self):
        self.target_samplerate = AudioConfig.SAMPLE_RATE_24K
        self.virtual_output = self._find_playback_device()

    def _find_playback_device(self) -> Optional[int]:
        """Discovers and configures the virtual audio output device."""
        try:
            devices = sd.query_devices()
            device_index = next(
                (d['index'] for d in devices
                 if AudioConfig.PLAYBACK_DEVICE_NAME in d['name'] 
                 and d['max_output_channels'] > 0),
                None
            )
            
            if device_index is not None:
                logger.info(f"[AudioHandler] Found VB-Audio Playback: {device_index}")
            else:
                logger.warning("[AudioHandler] VB-Audio Playback device not found")
            
            return device_index
            
        except Exception as e:
            logger.error(f"Error finding playback audio device: {e}")
            return None

    # =========================================================================
    # PUBLIC API - PLAYBACK METHODS
    # =========================================================================

    def play_audio_stream(
        self,
        audio_chunk_iterator: Iterator[bytes],
        meet: MeetController,
        stop_event: threading.Event
    ) -> bool:
        """
        Play MULAW audio stream from an iterator (e.g., Google TTS stream).
        
        Args:
            audio_chunk_iterator: Iterator yielding MULAW audio chunks
            meet: Meet controller for participant monitoring
            stop_event: Event to signal early termination
            
        Returns:
            True if playback completed successfully, False if interrupted
        """
        logger.debug("Starting MULAW stream playback")
        
        def feeder_func(audio_queue: queue.Queue, finished: threading.Event):
            """Feeds decoded audio chunks into queue."""
            try:
                for chunk_bytes in audio_chunk_iterator:
                    #  Check stop event BEFORE processing each chunk
                    if stop_event.is_set() or finished.is_set():
                        logger.debug("Feeder stopped by event")
                        break
                    
                    # Decode MULAW to Linear PCM
                    linear_audio = audioop.ulaw2lin(chunk_bytes, 2)
                    
                    # Convert to float32 for sounddevice
                    audio_data = np.frombuffer(
                        linear_audio, dtype=np.int16
                    ).astype(np.float32) / 32768.0
                    
                    if len(audio_data) > 0:
                        audio_queue.put(audio_data)
                        
            except Exception as e:
                logger.error(f"Audio feeder error: {e}", exc_info=True)
            finally:
                audio_queue.put(None)  # Signal end
        
        return self._execute_playback(feeder_func, meet, stop_event)

    def play_wav_file(
        self,
        file_path: Union[str, Path],
        meet: MeetController,
        stop_event: threading.Event
    ) -> bool:
        """
        Play a local WAV file directly.
        Optimized for cached static audio.
        
        Args:
            file_path: Path to WAV file
            meet: Meet controller for participant monitoring
            stop_event: Event to signal early termination
            
        Returns:
            True if playback completed successfully, False if interrupted
        """
        if not Path(file_path).exists():
            logger.error(f"Audio file not found: {file_path}")
            return False
        
        logger.info(f"Playing cached audio: {Path(file_path).name}")
        
        def feeder_func(audio_queue: queue.Queue, finished: threading.Event):
            """Feeds audio file chunks into queue."""
            try:
                # Read file using soundfile (returns float32 by default)
                data, fs = sf.read(str(file_path), dtype='float32')
                
                # Ensure mono
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                
                #  Feed in smaller chunks for faster interruption response
                # Smaller chunks = more frequent stop_event checks
                chunk_size = 2048  # Reduced from 4096 for faster response
                
                for i in range(0, len(data), chunk_size):
                    #  Check stop event BEFORE each chunk
                    if stop_event.is_set() or finished.is_set():
                        logger.debug(f"File feeder stopped at chunk {i//chunk_size}")
                        break
                    
                    chunk = data[i:i + chunk_size]
                    audio_queue.put(chunk)
                    
            except Exception as e:
                logger.error(f"File playback feeder error: {e}", exc_info=True)
            finally:
                audio_queue.put(None)  # Signal end
        
        return self._execute_playback(feeder_func, meet, stop_event)

    # =========================================================================
    # CORE PLAYBACK ENGINE (Unified Logic)
    # =========================================================================

    def _execute_playback(self, feeder_func: Callable[[queue.Queue, threading.Event], None], meet: MeetController, stop_event: threading.Event) -> bool:
        audio_queue: queue.Queue = queue.Queue(maxsize=100)
        stream_finished = threading.Event()
        internal_buffer = np.array([], dtype=np.float32)
        
        #  Track if we were interrupted for better logging
        interrupted = threading.Event()
        
        def playback_callback(outdata: np.ndarray, frames: int, time_info, status):
            nonlocal internal_buffer
            
            if status:
                logger.warning(f"Playback status: {status}")
            
            #  Check stop event in callback for immediate response
            if stop_event.is_set():
                interrupted.set()
                # Fill with silence and stop
                outdata[:] = 0
                raise sd.CallbackStop
            
            # Try to fill buffer from queue
            while len(internal_buffer) < frames:
                try:
                    chunk = audio_queue.get_nowait()
                    
                    if chunk is None:
                        # End of stream
                        self._write_remaining_buffer(
                            outdata, internal_buffer, frames
                        )
                        internal_buffer = np.array([], dtype=np.float32)
                        raise sd.CallbackStop
                    
                    internal_buffer = np.concatenate([internal_buffer, chunk])
                    
                except queue.Empty:
                    # No more data available - write what we have
                    self._write_remaining_buffer(outdata, internal_buffer, frames)
                    internal_buffer = np.array([], dtype=np.float32)
                    return
            
            # Write full frame
            outdata[:] = internal_buffer[:frames].reshape(-1, 1)
            internal_buffer = internal_buffer[frames:]
        
        try:
            #  Check stop event BEFORE starting (early exit)
            if stop_event.is_set():
                logger.debug("Stop event already set before playback start")
                return False
            
            # Start feeder thread
            feeder_thread = threading.Thread(
                target=feeder_func,
                args=(audio_queue, stream_finished),
                daemon=True,
                name="AudioFeeder"
            )
            feeder_thread.start()
            
            # Determine output device
            output_device = self.virtual_output or sd.default.device[1]
            
            # Create output stream
            stream = sd.OutputStream(
                samplerate=self.target_samplerate,
                device=output_device,
                channels=1,
                dtype='float32',
                callback=playback_callback,
                finished_callback=stream_finished.set
            )
            
            # Run playback loop
            with stream:
                success = self._monitor_playback(
                    stream, stream_finished, stop_event, meet, interrupted
                )
            
            # Wait for feeder thread
            feeder_thread.join(timeout=2)
            
            if not success and interrupted.is_set():
                logger.debug("Playback interrupted by stop event")
            
            return success
            
        except Exception as e:
            logger.error(f"Playback failed: {e}", exc_info=True)
            return False

    def _monitor_playback(
        self,
        stream: sd.OutputStream,
        stream_finished: threading.Event,
        stop_event: threading.Event,
        meet: Optional[MeetController],
        interrupted: threading.Event
    ) -> bool:
        #  Check VERY frequently (50ms) for near-instant interruption
        # At 24kHz sample rate with typical buffer sizes, this is fast enough
        # to interrupt within 1-2 audio buffers (~100-200ms total latency)
        check_interval = 0.05  # 50ms - increased from 0.1s
        
        check_count = 0
        
        while not stream_finished.is_set():
            if stream_finished.wait(timeout=check_interval):
                break
            
            check_count += 1
            
            #  Check for external stop signal (HIGHEST PRIORITY)
            if stop_event.is_set():
                logger.warning(f"Playback interrupted by stop signal (after {check_count * check_interval:.2f}s)")
                interrupted.set()
                
                #  Use abort() instead of stop() to cut audio INSTANTLY
                # abort() doesn't wait for buffer to drain, stop() does
                try:
                    stream.abort()
                except Exception as e:
                    logger.debug(f"Stream abort error (may be already stopped): {e}")
                
                return False
            
            #  Check if candidate disconnected (secondary check)
            if meet and not self._is_candidate_present(meet):
                logger.error(" Candidate left during playback")
                interrupted.set()
                
                try:
                    stream.abort()
                except Exception as e:
                    logger.debug(f"Stream abort error: {e}")
                
                return False
        
        # Normal completion
        return True

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def _write_remaining_buffer(
        outdata: np.ndarray,
        buffer: np.ndarray,
        frames: int
    ):
        """Writes remaining buffer data and pads with zeros."""
        buffer_len = len(buffer)
        
        if buffer_len > 0:
            outdata[:buffer_len] = buffer.reshape(-1, 1)
        
        if buffer_len < frames:
            outdata[buffer_len:] = 0

    @staticmethod
    def _is_candidate_present(meet: MeetController) -> bool:
        try:
            return meet.get_participant_count() >= 2
        except Exception as e:
            logger.debug(f"Participant check error: {e}")
            return True  # Assume present on error to avoid false positives
    
    # =========================================================================
    # EMERGENCY STOP (Optional - for external use)
    # =========================================================================
    
    def emergency_stop_all(self):
        try:
            logger.warning(" Emergency audio stop requested")
            
            # Stop all active streams (if we tracked them)
            # This would require maintaining a list of active streams
            # For now, this is a placeholder for future enhancement
            
            # Force stop default output
            try:
                sd.stop()
                logger.info("All audio streams stopped")
            except Exception as e:
                logger.debug(f"Error stopping streams: {e}")
                
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}")