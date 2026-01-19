"""
Chat-related actions for Google Meet.
Extracted from MeetController for better separation of concerns.
"""

import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from app.agents.interview_agent.utils.constants import BrowserConfig

logger = logging.getLogger(__name__)


class ChatActions:
    #Handles all chat-related operations in Google Meet
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, BrowserConfig.ELEMENT_WAIT_TIMEOUT_SEC)
    
    def send_message(self, message: str) -> bool:
        if not self.driver:
            logger.error("Driver not initialized")
            return False
        
        try:
            logger.debug("Attempting to send chat message...")
            
            # Step 1: Ensure chat panel is open
            if not self._ensure_chat_panel_open():
                return False
            
            # Step 2: Find chat input
            chat_input = self._find_chat_input()
            if not chat_input:
                return False
            
            # Step 3: Set message text and send
            if not self._send_message_via_input(chat_input, message):
                return False
            
            # Step 4: Verify message was sent
            return self._verify_message_sent(message)
            
        except TimeoutException as e:
            logger.error(f"Chat message timeout: {e.msg}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Chat message error: {e}", exc_info=True)
            return False
    
    def _ensure_chat_panel_open(self) -> bool:
        chat_input_selector = (By.CSS_SELECTOR, 'textarea[aria-label*="message" i]')
        
        try:
            # Check if already open
            self.wait.until(EC.visibility_of_element_located(chat_input_selector))
            logger.debug("Chat panel already open")
            return True
        except TimeoutException:
            # Need to open it
            logger.debug("Opening chat panel...")
            try:
                chat_button = self.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[aria-label*='Chat' i]")
                ))
                chat_button.click()
                
                # Wait for input to appear
                self.wait.until(EC.visibility_of_element_located(chat_input_selector))
                logger.debug("Chat panel opened successfully")
                return True
            except TimeoutException:
                logger.error("Failed to open chat panel")
                return False
    
    def _find_chat_input(self):
        try:
            return self.driver.find_element(
                By.CSS_SELECTOR,
                'textarea[aria-label*="message" i]'
            )
        except Exception as e:
            logger.error(f"Failed to find chat input: {e}")
            return None
    
    def _send_message_via_input(self, chat_input, message: str) -> bool:
        try:
            # Set text via JavaScript (more reliable for long text)
            js_set_text = """
            var ele = arguments[0];
            var txt = arguments[1];
            ele.value = txt;
            ele.dispatchEvent(new Event('input', { bubbles: true }));
            """
            self.driver.execute_script(js_set_text, chat_input, message)
            logger.debug("Message text set via JS")
            
            time.sleep(0.5)
            
            # Send Enter key to submit
            chat_input.send_keys(Keys.RETURN)
            logger.debug("Sent Enter key to submit message")
            
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    def _verify_message_sent(self, message: str) -> bool:
        # Use first 30 chars for verification
        verification_snippet = (
            "Interview Guidelines" if "Interview Guidelines" in message 
            else message.split('\n')[0].strip()[:30]
        )
        logger.info(f"Verifying message: '{verification_snippet}'")
        
        # Build XPath dynamically based on quote presence
        if "'" in verification_snippet and '"' not in verification_snippet:
            xpath = f'//div[contains(text(), "{verification_snippet}")]'
        elif '"' in verification_snippet:
            # Handle double quotes with concat
            parts = verification_snippet.split('"')
            concat_parts = "', '\"', '".join(parts)
            xpath = f"//div[contains(text(), concat('{concat_parts}'))]"
        else:
            xpath = f"//div[contains(text(), '{verification_snippet}')]"
        
        try:
            verify_wait = WebDriverWait(self.driver, 5)
            verify_wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            logger.info("Chat message sent and verified")
            return True
        except TimeoutException:
            # Fallback: Check if input cleared
            logger.warning("Message verification via DOM timed out, checking input state...")
            return self._verify_via_input_cleared()
    
    def _verify_via_input_cleared(self) -> bool:
        try:
            chat_input = self.driver.find_element(
                By.CSS_SELECTOR,
                'textarea[aria-label*="message" i]'
            )
            current_value = chat_input.get_attribute("value")
            
            if not current_value:
                logger.info("Message verified via cleared input field")
                return True
            else:
                logger.warning("Input not cleared, send may have failed")
                return False
        except Exception:
            # Assume success if we can't verify
            return True
