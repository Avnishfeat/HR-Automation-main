"""PulseAudio/PipeWire virtual-device setup and recovery helpers."""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_audio_setup_lock = threading.Lock()


def _configure_runtime_dir() -> None:
    """Give non-interactive processes access to the user's audio socket."""
    configured_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if configured_runtime_dir and os.path.exists(configured_runtime_dir):
        return

    runtime_dir = f"/run/user/{os.getuid()}"
    if os.path.exists(runtime_dir):
        if configured_runtime_dir:
            logger.warning(
                "Replacing unavailable XDG_RUNTIME_DIR %s with %s",
                configured_runtime_dir,
                runtime_dir,
            )
        os.environ["XDG_RUNTIME_DIR"] = runtime_dir
        logger.info("Set fallback XDG_RUNTIME_DIR to %s", runtime_dir)


def setup_linux_audio(max_retries: int = 5, retry_delay_seconds: float = 2) -> bool:
    """Ensure the bot's PulseAudio/PipeWire sinks exist.

    The audio server can be restarted independently of the backend.  Calling
    this function again is safe: it reconnects to the server and recreates
    sinks that disappeared with the server process.
    """
    if not sys.platform.startswith("linux"):
        return True

    _configure_runtime_dir()
    max_retries = max(1, max_retries)

    with _audio_setup_lock:
        for attempt in range(1, max_retries + 1):
            try:
                sinks = subprocess.check_output(
                    ["pactl", "list", "sinks", "short"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )

                created_sinks = False
                if "BotSpeaker" not in sinks:
                    logger.info("Creating virtual sink: BotSpeaker")
                    subprocess.run(
                        [
                            "pactl", "load-module", "module-null-sink",
                            "sink_name=BotSpeaker",
                            "sink_properties=device.description=BotSpeaker",
                        ],
                        check=True,
                        stderr=subprocess.DEVNULL,
                    )
                    created_sinks = True

                if "BotMic" not in sinks:
                    logger.info("Creating virtual sink: BotMic")
                    subprocess.run(
                        [
                            "pactl", "load-module", "module-null-sink",
                            "sink_name=BotMic",
                            "sink_properties=device.description=BotMic",
                        ],
                        check=True,
                        stderr=subprocess.DEVNULL,
                    )
                    created_sinks = True

                os.environ["PULSE_SINK"] = "BotSpeaker"
                os.environ["PULSE_SOURCE"] = "BotMic.monitor"
                if created_sinks:
                    logger.info("[Linux Audio] Virtual sinks recreated and environment routed")
                else:
                    logger.debug("[Linux Audio] Virtual sinks are ready")
                return True
            except FileNotFoundError:
                logger.error("[Linux Audio] pactl is not installed. Install pulseaudio-utils.")
                return False
            except (subprocess.CalledProcessError, OSError) as error:
                if attempt < max_retries:
                    logger.warning(
                        "[Linux Audio] Audio server unavailable (attempt %s/%s); retrying in %ss...",
                        attempt,
                        max_retries,
                        retry_delay_seconds,
                    )
                    time.sleep(retry_delay_seconds)
                    continue

                logger.error(
                    "[Linux Audio] Cannot connect to the PulseAudio/PipeWire server after %s attempts: %s. "
                    "Start pipewire-pulse (or PulseAudio) for the PM2 user.",
                    max_retries,
                    error,
                )
                return False

    return False


def _find_virtual_source_name(sources: str) -> Optional[str]:
    """Return the actual Pulse source name for the BotSpeaker proxy."""
    expected_names = {"BotSpeaker_Virtual", "output.BotSpeaker_Virtual"}
    for line in sources.splitlines():
        columns = line.split()
        if len(columns) > 1 and columns[1] in expected_names:
            return columns[1]
    return None


def configure_chromium_virtual_source() -> Optional[str]:
    """Expose BotSpeaker's monitor and return its actual Chromium source name."""
    with _audio_setup_lock:
        try:
            sources = subprocess.check_output(
                ["pactl", "list", "sources", "short"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            source_name = _find_virtual_source_name(sources)
            created_source = False
            if not source_name:
                subprocess.run(
                    [
                        "pactl", "load-module", "module-virtual-source",
                        "source_name=BotSpeaker_Virtual",
                        "master=BotSpeaker.monitor",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                created_source = True
                sources = subprocess.check_output(
                    ["pactl", "list", "sources", "short"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                source_name = _find_virtual_source_name(sources)

            if not source_name:
                logger.error("[Linux Audio] BotSpeaker virtual source was not created by pactl")
                return None

            if created_source:
                subprocess.run(
                    ["pactl", "set-default-source", source_name],
                    check=True,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["pactl", "set-default-sink", "BotMic"],
                    check=True,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("[Linux Audio] Chromium virtual source recreated as %s", source_name)
            else:
                logger.debug("[Linux Audio] Chromium virtual source is ready: %s", source_name)
            return source_name
        except (FileNotFoundError, subprocess.CalledProcessError, OSError) as error:
            logger.error("[Linux Audio] Could not configure Chromium virtual source: %s", error)
            return None


def linux_audio_ready() -> bool:
    """Return whether PulseAudio/PipeWire currently exposes the bot devices."""
    if not sys.platform.startswith("linux"):
        return True
    _configure_runtime_dir()
    try:
        sinks = subprocess.check_output(
            ["pactl", "list", "sinks", "short"], text=True, stderr=subprocess.DEVNULL
        )
        sources = subprocess.check_output(
            ["pactl", "list", "sources", "short"], text=True, stderr=subprocess.DEVNULL
        )
        return "BotSpeaker" in sinks and "BotMic" in sinks and _find_virtual_source_name(sources) is not None
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return False
