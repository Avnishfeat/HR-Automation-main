# app/infrastructure/selenium/actions/media_actions.py
"""
Media control actions (microphone, camera) for Google Meet.
Extracted from MeetController for better separation of concerns.
"""

import logging
import time
from selenium.common.exceptions import JavascriptException

logger = logging.getLogger(__name__)


class MediaActions:
    def __init__(self, driver):
        self.driver = driver
    
    def _execute_js_safely(self, script: str, error_msg: str = "JS execution failed"):
        try:
            return self.driver.execute_script(script)
        except JavascriptException as e:
            logger.error(f"{error_msg}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in JS execution: {e}")
            return None
    
    
    def turn_off_camera(self) -> bool:
        script = """
        const buttons = document.querySelectorAll("div[role='button'][aria-label*='camera' i]");
        const offButton = Array.from(buttons).find(b => 
            b.getAttribute('aria-label').toLowerCase().includes('turn off')
        );
        if (offButton) {
            offButton.click();
            return true;
        }
        return false;
        """
        result = self._execute_js_safely(script, "Failed to turn off camera")
        
        if result:
            logger.info("Camera turned off (JS)")
            time.sleep(0.5)
            return True
        else:
            logger.info("Camera already off or button not found (JS)")
            return False
    
    def turn_on_camera(self) -> bool:
        script = """
        const buttons = document.querySelectorAll("div[role='button'][aria-label*='camera' i]");
        const onButton = Array.from(buttons).find(b => 
            b.getAttribute('aria-label').toLowerCase().includes('turn on')
        );
        if (onButton) {
            onButton.click();
            return true;
        }
        return false;
        """
        result = self._execute_js_safely(script, "Failed to turn on camera")
        
        if result:
            logger.info("Camera turned on (JS)")
            time.sleep(0.5)
            return True
        else:
            logger.info("Camera already on or button not found (JS)")
            return False
    
    
    def enable_microphone(self) -> bool:
        if not self.driver:
            return False
            
        script = """
        const mic_button = Array.from(
            document.querySelectorAll("div[data-is-muted='true'][aria-label*='microphone' i]")
        ).find(e => e.offsetParent !== null);
        if (mic_button) { 
            mic_button.click(); 
            return true; 
        }
        return false;
        """
        
        result = self._execute_js_safely(script, "Failed to enable microphone")
        
        if result:
            logger.info("Microphone enabled (JS)")
            time.sleep(0.5)
            return True
        else:
            logger.debug("Microphone already enabled or button not found (JS)")
            time.sleep(0.5)
            return False
    
    def disable_microphone(self) -> bool:
        if not self.driver:
            return False
            
        script = """
        const mic_button = Array.from(
            document.querySelectorAll("div[data-is-muted='false'][aria-label*='microphone' i]")
        ).find(e => e.offsetParent !== null);
        if (mic_button) { 
            mic_button.click(); 
            return true; 
        }
        return false;
        """
        
        result = self._execute_js_safely(script, "Failed to disable microphone")
        
        if result:
            logger.info("Microphone disabled (JS)")
            time.sleep(0.5)
            return True
        else:
            logger.debug("Microphone already disabled or button not found (JS)")
            time.sleep(0.5)
            return False
    
    def turn_off_microphone_at_join(self) -> bool:
        script = """
        const buttons = document.querySelectorAll("div[role='button'][aria-label*='microphone' i]");
        const offButton = Array.from(buttons).find(b => 
            b.getAttribute('aria-label').toLowerCase().includes('turn off')
        );
        if (offButton) {
            offButton.click();
            return true;
        }
        return false;
        """
        result = self._execute_js_safely(script, "Failed to turn off microphone")
        
        if result:
            logger.info("Microphone turned off (JS)")
            time.sleep(0.5)
            return True
        else:
            logger.info("Microphone already off or button not found (JS)")
            return False