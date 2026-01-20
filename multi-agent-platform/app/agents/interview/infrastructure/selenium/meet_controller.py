# app/infrastructure/selenium/meet_controller.py
import logging
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from typing import Optional, Tuple, List
import undetected_chromedriver as uc

from app.agents.interview.config.constants import BrowserConfig, InterviewTiming
from .actions.chat_actions import ChatActions
from .actions.media_actions import MediaActions
from .actions.video_capture import VideoCapture
from .actions.participant_tracker import ParticipantTracker  # ✅ CORRECT IMPORT

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
        self.driver: Optional[uc.Chrome] = None
        self.current_meet_link: Optional[str] = None
        
        # Action delegates (initialized after driver setup)
        self.chat: Optional[ChatActions] = None
        self.media: Optional[MediaActions] = None
        self.video: Optional[VideoCapture] = None
        self.participants: Optional[ParticipantTracker] = None  # ✅ CORRECT TYPE


    def setup_driver(self) -> bool:
        """Setup Chrome driver with appropriate options"""
        try:
            options = uc.ChromeOptions()

            if self.headless:
                options.add_argument('--headless=new')

            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')

            if self.use_vb_audio:
                logger.info("Configuring Chrome for VB-Audio Cable (REAL audio)")
                options.add_argument('--use-fake-ui-for-media-stream')
                options.add_argument('--enable-usermedia-screen-capturing')
                options.add_argument('--allow-file-access-from-files')

                prefs = {
                    "profile.default_content_setting_values.media_stream_mic": 1,
                    "profile.default_content_setting_values.media_stream_camera": 1,
                    "profile.default_content_setting_values.notifications": 2,
                }

                if self.audio_device_index is not None:
                    logger.info(f"Using VB-Audio device index: {self.audio_device_index}")
                    prefs["media.audio_capture_device"] = str(self.audio_device_index)

            else:
                logger.info("Configuring Chrome with fake audio devices")
                options.add_argument('--use-fake-ui-for-media-stream')
                options.add_argument('--use-fake-device-for-media-stream')

                prefs = {
                    "profile.default_content_setting_values.media_stream_mic": 1,
                    "profile.default_content_setting_values.media_stream_camera": 1,
                    "profile.default_content_setting_values.notifications": 2,
                }

            options.add_experimental_option("prefs", prefs)

            if self.user_data_dir:
                profile_path = os.path.abspath(self.user_data_dir)
                os.makedirs(profile_path, exist_ok=True)
                logger.info(f"Using persistent Chrome profile: {profile_path}")
                options.add_argument(f'--user-data-dir={profile_path}')
            else:
                logger.info("Using temporary Chrome profile")

            options.add_argument('--disable-extensions')
            options.add_argument('--disable-plugins-discovery')

            logger.info("Creating Chrome driver...")
            self.driver = uc.Chrome(options=options)

            self.driver.set_page_load_timeout(BrowserConfig.PAGE_LOAD_TIMEOUT_SEC)
            self.driver.implicitly_wait(BrowserConfig.IMPLICIT_WAIT_SEC)

            # Initialize action delegates
            self.chat = ChatActions(self.driver)
            self.media = MediaActions(self.driver)
            self.video = VideoCapture(self.driver)
            self.participants = ParticipantTracker(self.driver)  # ✅ CORRECT - only needs driver

            logger.info("Chrome driver created successfully")

            if self.use_vb_audio:
                logger.info("Chrome is configured to use REAL audio devices (VB-Audio)")
                logger.info("1. VB-Audio Cable is installed")
                logger.info("2. Your TTS output is routed to VB-Audio Input")
                logger.info("3. Chrome will capture from VB-Audio Output")

            return True

        except Exception as e:
            logger.error(f"Failed to setup Chrome driver: {e}", exc_info=True)
            return False


    def join_meeting(self, meet_link: str, display_name: str = "AI Bot") -> bool:
        """Join a Google Meet meeting"""
        try:
            if not self.driver:
                logger.error("Driver not initialized")
                return False

            logger.info(f"Navigating to Meet: {meet_link}")
            self.current_meet_link = meet_link

            self.driver.get(meet_link)
            time.sleep(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC)

            # Handle name input if needed
            self._set_display_name(display_name)

            # Turn off camera
            self.media.turn_off_camera()

            # Turn off mic if not using VB Audio
            if not self.use_vb_audio:
                self.media.turn_off_microphone_at_join()
            else:
                logger.info("Microphone configured for VB-Audio (keeping ON)")

            # Click join button
            if not self._click_join_button():
                return False

            # Verify join
            return self._verify_meeting_joined()

        except Exception as e:
            logger.error(f"Error joining meeting: {e}", exc_info=True)
            return False

    def _set_display_name(self, display_name: str):
        try:
            name_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    By.XPATH, 
                    "//input[@placeholder='Enter your name'] | //input[@aria-label='Your name']"
                ))
            )
            name_input.clear()
            name_input.send_keys(display_name)
            logger.info(f"Entered display name: {display_name}")
        except TimeoutException:
            logger.info("Name input not required or already set")
        except Exception as e:
            logger.warning(f"Could not set display name: {e}")

    def _click_join_button(self) -> bool:
        try:
            logger.info(
                f"Finding 'Join' button "
                f"(will try for {BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC} seconds)..."
            )
            join_locators = [
                (By.XPATH, 
                 "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                 "'abcdefghijklmnopqrstuvwxyz'), 'join now')]]"),
                (By.XPATH, 
                 "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                 "'abcdefghijklmnopqrstuvwxyz'), 'ask to join')]]")
            ]

            join_button = None
            start_time = time.time()
            
            while time.time() - start_time < BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC:
                for locator_type, selector_string in join_locators:
                    try:
                        element = WebDriverWait(
                            self.driver, 
                            BrowserConfig.JOIN_BUTTON_CHECK_INTERVAL_SEC
                        ).until(
                            EC.element_to_be_clickable((locator_type, selector_string))
                        )
                        if element:
                            join_button = element
                            logger.info(f"Found clickable join button")
                            break
                    except TimeoutException:
                        continue
                if join_button:
                    break
                time.sleep(1)

            if join_button:
                self.driver.execute_script("arguments[0].click();", join_button)
                logger.info("Clicked join button (JS)")
                time.sleep(BrowserConfig.POST_JOIN_WAIT_SEC)
                return True
            else:
                logger.warning(
                    f"Could not find join button after "
                    f"{BrowserConfig.JOIN_BUTTON_SEARCH_TIMEOUT_SEC} seconds"
                )
                return False

        except Exception as e:
            logger.error(f"Failed to click join button: {e}", exc_info=True)
            return False

    def _verify_meeting_joined(self) -> bool:
        """Verify that the meeting was joined successfully"""
        try:
            WebDriverWait(self.driver, BrowserConfig.POST_JOIN_VERIFY_TIMEOUT_SEC).until(
                lambda d: "meet.google.com/" in d.current_url and 
                         d.execute_script("return document.readyState") == "complete"
            )
            logger.info("Successfully joined Google Meet")

            if self.use_vb_audio:
                logger.info("Bot is now listening via VB-Audio Cable")

            return True
        except TimeoutException:
            logger.error("Failed to verify meeting join or page didn't complete loading")
            return False

    def leave_meeting(self):
        try:
            if not self.driver:
                return
            logger.info("Leaving meeting...")
            
            # Try JS first
            if self._leave_via_js():
                return
            
            # Fallback to Selenium
            self._leave_via_selenium()
            
        except Exception as e:
            logger.error(f"Error in leave_meeting: {e}")

    def _leave_via_js(self) -> bool:
        script = """
        const leaveButton = document.querySelector(
            "button[aria-label*='Leave call' i], button[aria-label*='Hang up' i]"
        );
        if (leaveButton) {
            leaveButton.click();
            return true;
        }
        const iconButton = document.querySelector("button i.google-material-icons");
        if (iconButton && iconButton.textContent === 'call_end') {
            const clickableParent = iconButton.closest('button');
            if (clickableParent) {
                clickableParent.click();
                return true;
            }
        }
        return false;
        """
        try:
            result = self.driver.execute_script(script)
            if result:
                logger.info("Left meeting (JS)")
                time.sleep(2)
                return True
        except Exception as e:
            logger.warning(f"JS leave failed: {e}. Trying Selenium.")
        
        return False

    def _leave_via_selenium(self):
        try:
            leave_selectors = [
                "button[aria-label*='Leave call'][data-mdc-value='end_call']",
                "button[aria-label*='Leave call' i]",
                "button[aria-label*='Hang up' i]"
            ]
            for selector in leave_selectors:
                try:
                    leave_button = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    leave_button.click()
                    logger.info("Left meeting (Selenium)")
                    time.sleep(2)
                    return
                except TimeoutException:
                    continue
            
            logger.warning("Could not find leave button via Selenium, navigating away")
            self.driver.get("about:blank")
        except Exception as e:
            logger.warning(f"Error leaving via Selenium: {e}")
            self.driver.get("about:blank")


    def enable_microphone(self):
        if self.media:
            return self.media.enable_microphone()
        return False

    def disable_microphone(self):
        if self.media:
            return self.media.disable_microphone()
        return False

    def send_chat_message(self, message: str) -> bool:
        if self.chat:
            return self.chat.send_message(message)
        return False

    def get_participant_count(self) -> int:
        if self.participants:
            return self.participants.get_participant_count()
        return 0

    def get_active_participant_names(self) -> List[str]:
        """Delegates name scraping to the ParticipantTracker."""
        if self.participants:
            return self.participants.get_active_participant_names()
        return []

    # --- NEW WRAPPER METHOD TO FIX 'NO ATTRIBUTE' ERROR ---
    def capture_candidate_video(self) -> Optional[Tuple[bytes, int, int]]:
        """
        Wrapper that attempts JS capture first, then falls back to Screenshot.
        Returns: (bytes, width, height) OR None
        """
        # Try 1: Fast JS Capture (Preferred)
        result = self.capture_candidate_video_js()
        if result:
            return result

        # Try 2: Screenshot Fallback
        # Note: We return generic dims (0,0) as we might not parse them here,
        # but the caller expects a tuple.
        screenshot_bytes = self.capture_candidate_video_screenshot()
        if screenshot_bytes:
            return (screenshot_bytes, 0, 0) 
            
        return None
    # -----------------------------------------------------

    def capture_candidate_video_js(self) -> Optional[Tuple[bytes, int, int]]:
        if self.video:
            return self.video.capture_candidate_video_js()
        return None

    def capture_candidate_video_screenshot(self) -> Optional[bytes]:
        if self.video:
            return self.video.capture_screenshot()
        return None


    def cleanup(self):
        try:
            if self.driver:
                logger.info("Cleaning up Chrome driver...")
                try:
                    self.driver.close()
                    self.driver.quit()
                except Exception as e:
                    logger.warning(f"Error driver close/quit: {e}")
                    try:
                        self.driver.quit()
                    except Exception as e_quit:
                        logger.error(f"Force quit failed: {e_quit}")
                self.driver = None
                logger.info("Chrome driver cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False