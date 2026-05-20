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
import soundfile as sf
import time
from pathlib import Path
from typing import Union, Optional, Callable, Iterator

from app.agents.interview.infrastructure.browser.meet_controller import MeetController
from app.agents.interview.config.constants import AudioConfig

logger = logging.getLogger(__name__)

# Standard G.711 mu-law to 16-bit linear PCM lookup table
ULAW_TO_LIN16_TABLE = np.array([
    -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956, -23932, -22908,
    -21884, -20860, -19836, -18812, -17788, -16764, -15996, -15484, -14972, -14460,
    -13948, -13436, -12924, -12412, -11900, -11388, -10876, -10364, -9852, -9340, -8828,
    -8316, -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140, -5884, -5628, -5372,
    -5116, -4860, -4604, -4348, -4092, -3900, -3772, -3644, -3516, -3388, -3260, -3132,
    -3004, -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980, -1884, -1820, -1756,
    -1692, -1628, -1564, -1500, -1436, -1372, -1308, -1244, -1180, -1116, -1052, -988,
    -924, -876, -844, -812, -780, -748, -716, -684, -652, -620, -588, -556, -524, -492,
    -460, -428, -396, -372, -356, -340, -324, -308, -292, -276, -260, -244, -228, -212,
    -196, -180, -164, -148, -132, -120, -112, -104, -96, -88, -80, -72, -64, -56, -48,
    -40, -32, -24, -16, -8, 0, 32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
    23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764, 15996, 15484, 14972, 14460,
    13948, 13436, 12924, 12412, 11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316, 7932,
    7676, 7420, 7164, 6908, 6652, 6396, 6140, 5884, 5628, 5372, 5116, 4860, 4604, 4348,
    4092, 3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004, 2876, 2748, 2620, 2492, 2364,
    2236, 2108, 1980, 1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436, 1372, 1308, 1244,
    1180, 1116, 1052, 988, 924, 876, 844, 812, 780, 748, 716, 684, 652, 620, 588, 556,
    524, 492, 460, 428, 396, 372, 356, 340, 324, 308, 292, 276, 260, 244, 228, 212, 196,
    180, 164, 148, 132, 120, 112, 104, 96, 88, 80, 72, 64, 56, 48, 40, 32, 24, 16, 8, 0
], dtype=np.int16)


class AudioHandler:
    def __init__(self):
        self.target_samplerate = AudioConfig.SAMPLE_RATE_24K
        self.virtual_output = self._find_playback_device()

    def _find_playback_device(self) -> Optional[int]:
        """Discovers and configures the virtual audio output device."""
        try:
            import os
            target_name = AudioConfig.PLAYBACK_DEVICE_NAME.lower()
            devices = sd.query_devices()
            preferred_hostapis = ['Windows WASAPI', 'Windows DirectSound', 'MME']
            
            # First pass: look for exact device match with preferred APIs
            for api in preferred_hostapis:
                for d in devices:
                    if d['max_output_channels'] > 0 and target_name in d['name'].lower():
                        host_api_name = sd.query_hostapis(d['hostapi'])['name']
                        if host_api_name == api:
                            logger.info(f"[AudioHandler] Found preferred VB-Audio Playback [{api}]: {d['index']}")
                            self.target_samplerate = int(d['default_samplerate'])
                            return d['index']
            
            # Second pass: Any matching device regardless of API
            for d in devices:
                if d['max_output_channels'] > 0 and target_name in d['name'].lower():
                    logger.info(f"[AudioHandler] Found fallback VB-Audio Playback: {d['index']}")
                    self.target_samplerate = int(d['default_samplerate'])
                    return d['index']
                    
            if os.name != 'nt':
                # Fallback to the explicit PulseAudio device on Linux
                # since we set PULSE_SINK in the environment
                for d in devices:
                    if d['name'] == 'pulse' and d['max_output_channels'] > 0:
                        logger.info("Falling back to PulseAudio device for TTS playback")
                        self.target_samplerate = int(d['default_samplerate']) or 48000
                        return d['index']
            
            logger.warning("[AudioHandler] VB-Audio Playback device not found. Using system default.")
            return None
            
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
        """
        logger.debug("Starting MULAW stream playback")
        
        def feeder_func(audio_queue: queue.Queue, finished: threading.Event):
            """Feeds decoded audio chunks into queue."""
            try:
                for chunk_bytes in audio_chunk_iterator:
                    if stop_event.is_set() or finished.is_set():
                        break
                    
                    # Decode MULAW to Linear PCM (Google TTS native 24kHz) via numpy lookup
                    chunk_uint8 = np.frombuffer(chunk_bytes, dtype=np.uint8)
                    linear_audio_int16 = ULAW_TO_LIN16_TABLE[chunk_uint8]
                    
                    # Convert to float32 for sounddevice
                    audio_data = linear_audio_int16.astype(np.float32) / 32768.0
                    
                    if len(audio_data) > 0:
                        audio_queue.put(audio_data)
            except Exception as e:
                logger.error(f"Audio feeder error: {e}", exc_info=True)
            finally:
                audio_queue.put(None)
                
        # Use native 24kHz and let PipeWire/OS handle the resampling, preventing crackles
        # Increase prebuffer to 20 to handle tiny network chunks from Google TTS
        return self._execute_playback(feeder_func, stop_event, samplerate=24000, prebuffer_chunks=20)

    def play_wav_file(
        self,
        file_path: Union[str, Path],
        meet: MeetController,
        stop_event: threading.Event
    ) -> bool:
        """
        Play a local WAV file directly.
        Optimized for cached static audio.
        """
        if not Path(file_path).exists():
            logger.error(f"Audio file not found: {file_path}")
            return False
        
        logger.info(f"Playing cached audio: {Path(file_path).name}")
        
        # Read file using soundfile
        try:
            data, fs = sf.read(str(file_path), dtype='float32')
        except Exception as e:
            logger.error(f"Failed to read audio file: {e}")
            return False

        # Ensure mono
        if len(data.shape) > 1:
            data = data.mean(axis=1)

        def feeder_func(audio_queue: queue.Queue, finished: threading.Event):
            """Feeds audio file chunks into queue."""
            try:
                chunk_size = 4096  # Larger chunk to prevent queue starvation
                
                for i in range(0, len(data), chunk_size):
                    if stop_event.is_set() or finished.is_set():
                        break
                    chunk = data[i:i + chunk_size]
                    audio_queue.put(chunk)
            except Exception as e:
                logger.error(f"File playback feeder error: {e}", exc_info=True)
            finally:
                audio_queue.put(None)  # Signal end
        
        return self._execute_playback(feeder_func, stop_event, samplerate=fs, prebuffer_chunks=2)

    # =========================================================================
    # CORE PLAYBACK ENGINE (Unified Logic)
    # =========================================================================

    def _execute_playback(self, feeder_func: Callable[[queue.Queue, threading.Event], None], stop_event: threading.Event, samplerate: Optional[int] = None, prebuffer_chunks: int = 5) -> bool:
        audio_queue: queue.Queue = queue.Queue(maxsize=200)
        stream_finished = threading.Event()
        internal_buffer = np.array([], dtype=np.float32)
        
        interrupted = threading.Event()
        
        def playback_callback(outdata: np.ndarray, frames: int, time_info, status):
            nonlocal internal_buffer
            
            if status:
                # Only log critical status errors, not every underflow to avoid spam
                if status.output_underflow:
                    pass # Normal if queue is starved, don't spam log
                else:
                    logger.warning(f"Playback status: {status}")
            
            if stop_event.is_set():
                interrupted.set()
                outdata.fill(0)
                raise sd.CallbackStop
            
            while len(internal_buffer) < frames:
                try:
                    chunk = audio_queue.get_nowait()
                    if chunk is None:
                        self._write_remaining_buffer(outdata, internal_buffer, frames)
                        internal_buffer = np.array([], dtype=np.float32)
                        raise sd.CallbackStop
                    internal_buffer = np.concatenate([internal_buffer, chunk])
                except queue.Empty:
                    # FIX: We must zero-pad the rest of outdata so the OS doesn't
                    # replay garbage from its circular buffer if we underflow!
                    self._write_remaining_buffer(outdata, internal_buffer, frames)
                    internal_buffer = np.array([], dtype=np.float32)
                    return
            
            outdata[:] = internal_buffer[:frames].reshape(-1, 1)
            internal_buffer = internal_buffer[frames:]
        
        try:
            if stop_event.is_set():
                return False
            
            feeder_thread = threading.Thread(
                target=feeder_func,
                args=(audio_queue, stream_finished),
                daemon=True,
                name="AudioFeeder"
            )
            feeder_thread.start()
            
            # --- Pre-buffering wait to avoid instant underflow ---
            wait_time = 0.0
            while audio_queue.qsize() < prebuffer_chunks and wait_time < 3.0:
                if stop_event.is_set(): return False
                time.sleep(0.05)
                wait_time += 0.05
            
            output_device = self.virtual_output or sd.default.device[1]
            
            stream = sd.OutputStream(
                samplerate=samplerate or self.target_samplerate,
                device=output_device,
                channels=1,
                dtype='float32',
                blocksize=2048,
                latency='high',
                callback=playback_callback,
                finished_callback=stream_finished.set
            )
            
            with stream:
                success = self._monitor_playback(
                    stream, stream_finished, stop_event, interrupted
                )
            
            feeder_thread.join(timeout=2)
            return success
            
        except Exception as e:
            logger.error(f"Playback failed: {e}", exc_info=True)
            return False

    def _monitor_playback(
        self,
        stream: sd.OutputStream,
        stream_finished: threading.Event,
        stop_event: threading.Event,
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
