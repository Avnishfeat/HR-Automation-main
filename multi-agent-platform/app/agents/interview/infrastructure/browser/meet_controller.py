# app/infrastructure/browser/meet_controller.py
import logging
import asyncio
import os
import re
import subprocess
from typing import Optional, Tuple, List
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from app.agents.interview.config.constants import BrowserConfig, InterviewTiming
from .actions.chat_actions import ChatActions
from .actions.media_actions import MediaActions
from .actions.video_capture import VideoCapture
from .actions.participant_tracker import ParticipantTracker

logger = logging.getLogger(__name__)

class MeetController:
    def __init__(
        self,
        headless: bool = True,
        audio_device_index: Optional[int] = None,
        user_data_dir: Optional[str] = None,
        use_vb_audio: bool = True
    ):
        self.headless = headless
        self.audio_device_index = audio_device_index
        self.user_data_dir = user_data_dir
        self.use_vb_audio = use_vb_audio
        
        self.playwright_mgr = None
        self.playwright = None
        self.browser: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.current_meet_link: Optional[str] = None
        
        # Action delegates
        self.chat: Optional[ChatActions] = None
        self.media: Optional[MediaActions] = None
        self.video: Optional[VideoCapture] = None
        self.participants: Optional[ParticipantTracker] = None

    async def setup_driver(self) -> bool:
        """Setup Playwright browser with appropriate options asynchronously"""
        try:
            self.playwright_mgr = async_playwright()
            self.playwright = await self.playwright_mgr.start()
            
            args = [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ]

            # Critical: Old headless mode completely mocks out the WebRTC media pipeline.
            # We must use the new headless mode to allow real virtual audio cables to work.
            if self.headless:
                args.append('--headless=new')

            if self.use_vb_audio:
                logger.info("Configuring Playwright for VB-Audio Cable/Virtual Sinks (REAL audio)")
                args.extend([
                    '--use-fake-ui-for-media-stream',
                    '--enable-usermedia-screen-capturing',
                    '--allow-file-access-from-files'
                ])
            else:
                logger.info("Configuring Playwright with fake audio devices")
                args.extend([
                    '--use-fake-ui-for-media-stream',
                    '--use-fake-device-for-media-stream'
                ])

            env = os.environ.copy()
            if self.use_vb_audio and os.name != 'nt':
                # Chromium actively hides .monitor sources, so we must proxy it through a virtual source
                os.system("for id in $(pactl list modules short | grep module-virtual-source | awk '{print $1}'); do pactl unload-module $id; done || true")
                os.system("pactl load-module module-virtual-source source_name=BotSpeaker_Virtual master=BotSpeaker.monitor || true")
                os.system("pactl set-default-source output.BotSpeaker_Virtual || true")
                os.system("pactl set-default-sink BotMic || true")
                env["PULSE_SINK"] = "BotMic"
                env["PULSE_SOURCE"] = "output.BotSpeaker_Virtual"
                logger.info("Set PULSE_SINK=BotMic and PULSE_SOURCE=output.BotSpeaker_Virtual for Chromium")

            if self.user_data_dir:
                profile_path = os.path.abspath(self.user_data_dir)
                os.makedirs(profile_path, exist_ok=True)
                
                # FIX: Remove stale SingletonLock if previous run crashed
                lock_file = os.path.join(profile_path, "SingletonLock")
                if os.path.lexists(lock_file):
                    try:
                        os.remove(lock_file)
                        logger.info(f"Removed stale SingletonLock at {lock_file}")
                    except OSError as e:
                        logger.warning(f"Could not remove SingletonLock: {e}")
                
                logger.info(f"Using persistent Chromium profile: {profile_path}")
                self.browser = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,  # We use args=['--headless=new'] instead
                    args=args,
                    env=env
                )
            else:
                logger.info("Using temporary Chromium profile")
                browser_instance = await self.playwright.chromium.launch(
                    headless=False,  # We use args=['--headless=new'] instead
                    args=args,
                    env=env
                )
                self.browser = await browser_instance.new_context()

            await self.browser.grant_permissions(['camera', 'microphone'])
            
            self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()
            
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """)

            self.page.set_default_navigation_timeout(BrowserConfig.PAGE_LOAD_TIMEOUT_SEC * 1000)
            self.page.set_default_timeout(BrowserConfig.IMPLICIT_WAIT_SEC * 1000)

            self.chat = ChatActions(self.page)
            self.media = MediaActions(self.page)
            self.video = VideoCapture(self.page)
            self.participants = ParticipantTracker(self.page)

            logger.info("Playwright browser started successfully (Async)")
            return True

        except Exception as e:
            logger.error(f"Failed to setup Playwright browser: {e}", exc_info=True)
            await self.cleanup()
            return False

    async def join_meeting(self, meet_link: str, display_name: str = "AI Bot") -> bool:
        """Join a Google Meet meeting asynchronously"""
        try:
            if not self.page:
                logger.error("Page not initialized")
                return False

            logger.info(f"Navigating to Meet: {meet_link}")
            self.current_meet_link = meet_link

            await self.page.goto(meet_link)
            await self.page.wait_for_timeout(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC * 1000)

            if self.page.url == "https://meet.google.com/":
                logger.warning("Redirected to Google Meet home page. Attempting manual code entry.")
                match = re.search(r'meet\.google\.com/([^/?]+)', meet_link)
                if match:
                    code = match.group(1)
                    code_input = self.page.locator("input[placeholder='Enter a code or link']")
                    if await code_input.count() > 0:
                        await code_input.first.fill(code)
                        await self.page.locator("button:has-text('Join')").first.click()
                        await self.page.wait_for_timeout(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC * 1000)
                else:
                    logger.error("Could not extract meeting code from link.")
                    return False

            await self._set_display_name(display_name)
            await self.media.turn_off_camera()

            if not self.use_vb_audio:
                await self.media.turn_off_microphone_at_join()
            else:
                logger.info("Microphone configured for VB-Audio/Virtual Sinks (keeping ON)")

            if not await self._click_join_button():
                return False

            return await self._verify_meeting_joined()

        except Exception as e:
            logger.error(f"Error joining meeting: {e}", exc_info=True)
            return False

    async def _set_display_name(self, display_name: str):
        try:
            name_input = self.page.locator("input[placeholder='Enter your name'], input[aria-label='Your name']")
            if await name_input.count() > 0:
                await name_input.first.fill(display_name)
                logger.info(f"Entered display name: {display_name}")
            else:
                logger.info("Name input not required or not found")
        except Exception as e:
            logger.warning(f"Could not set display name: {e}")

    async def _click_join_button(self) -> bool:
        try:
            logger.info(f"Finding 'Join' button (timeout: {BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC}s)...")
            join_button = self.page.locator("button:has-text('Join now'), button:has-text('Ask to join'), div[role='button']:has-text('Join now'), div[role='button']:has-text('Ask to join')").first
            
            try:
                await join_button.wait_for(state="visible", timeout=BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC * 1000)
                await join_button.click()
                logger.info("Clicked join button")
                await self.page.wait_for_timeout(BrowserConfig.POST_JOIN_WAIT_SEC * 1000)
                return True
            except PlaywrightTimeoutError:
                logger.warning(f"Could not find join button after {BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC} seconds")
                try:
                    screenshot_path = os.path.join(os.getcwd(), "failed_join_screenshot.png")
                    await self.page.screenshot(path=screenshot_path)
                    logger.error(f"Saved screenshot to {screenshot_path}")
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.error(f"Failed to click join button: {e}", exc_info=True)
            return False

    async def _verify_meeting_joined(self) -> bool:
        """Verify that the meeting was joined successfully"""
        try:
            await self.page.wait_for_url("**/meet.google.com/*", timeout=BrowserConfig.POST_JOIN_VERIFY_TIMEOUT_SEC * 1000)
            await self.page.wait_for_load_state("domcontentloaded")
            logger.info("Successfully joined Google Meet")
            return True
        except PlaywrightTimeoutError:
            logger.error("Failed to verify meeting join within timeout")
            return False

    async def leave_meeting(self):
        try:
            if not self.page: return
            logger.info("Leaving meeting...")
            leave_button = self.page.locator("button[aria-label*='Leave call'], button[aria-label*='Hang up']").first
            if await leave_button.count() > 0:
                await leave_button.click()
                logger.info("Left meeting")
                await self.page.wait_for_timeout(2000)
            else:
                logger.warning("Could not find leave button, navigating away")
                await self.page.goto("about:blank")
        except Exception as e:
            logger.warning(f"Error leaving meeting: {e}")
            try:
                 await self.page.goto("about:blank")
            except:
                 pass

    async def enable_microphone(self):
        return await self.media.enable_microphone() if self.media else False

    async def disable_microphone(self):
        return await self.media.disable_microphone() if self.media else False

    async def send_chat_message(self, message: str) -> bool:
        return await self.chat.send_message(message) if self.chat else False

    async def get_participant_count(self) -> int:
        return await self.participants.get_participant_count() if self.participants else 0

    async def get_active_participant_names(self) -> List[str]:
        return await self.participants.get_active_participant_names() if self.participants else []

    async def capture_candidate_video(self) -> Optional[Tuple[bytes, int, int]]:
        result = await self.capture_candidate_video_js()
        if result: return result
        screenshot_bytes = await self.capture_candidate_video_screenshot()
        if screenshot_bytes: return (screenshot_bytes, 0, 0) 
        return None

    async def capture_candidate_video_js(self) -> Optional[Tuple[bytes, int, int]]:
        return await self.video.capture_candidate_video_js() if self.video else None

    async def capture_candidate_video_screenshot(self) -> Optional[bytes]:
        return await self.video.capture_screenshot() if self.video else None

    async def cleanup(self):
        try:
            logger.info("Cleaning up Playwright browser...")
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            logger.info("Playwright browser cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        return False

