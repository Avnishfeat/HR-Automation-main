# app/infrastructure/browser/actions/media_actions.py
"""
Media control actions (microphone, camera) for Google Meet.
Refactored for async Playwright to use JS evaluation to bypass auto-hiding toolbars.
"""

import logging
import asyncio
from playwright.async_api import Page

logger = logging.getLogger(__name__)

class MediaActions:
    def __init__(self, page: Page):
        self.page = page
    
    async def turn_off_camera(self) -> bool:
        if not self.page: return False
        try:
            changed = await self.page.evaluate('''() => {
                const btn = document.querySelector("button[aria-label*='Turn off camera' i], div[role='button'][aria-label*='Turn off camera' i]");
                if (btn && btn.getAttribute('data-is-muted') !== 'true') {
                    btn.click();
                    return true;
                }
                return false;
            }''')
            if changed:
                logger.info("Camera turned off")
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" not in err_msg and "target" not in err_msg and "disconnect" not in err_msg:
                logger.error(f"Error turning off camera: {e}")
            return False
    
    async def turn_on_camera(self) -> bool:
        if not self.page: return False
        try:
            changed = await self.page.evaluate('''() => {
                const btn = document.querySelector("button[aria-label*='Turn on camera' i], div[role='button'][aria-label*='Turn on camera' i]");
                if (btn && btn.getAttribute('data-is-muted') === 'true') {
                    btn.click();
                    return true;
                }
                return false;
            }''')
            if changed:
                logger.info("Camera turned on")
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" not in err_msg and "target" not in err_msg and "disconnect" not in err_msg:
                logger.error(f"Error turning on camera: {e}")
            return False
    
    async def enable_microphone(self) -> bool:
        if not self.page: return False
        try:
            changed = await self.page.evaluate('''() => {
                const btn = document.querySelector("button[aria-label*='microphone' i], div[role='button'][aria-label*='microphone' i]");
                if (btn && btn.getAttribute('data-is-muted') === 'true') {
                    btn.click();
                    return true;
                }
                return false;
            }''')
            if changed:
                logger.info("Microphone enabled")
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" not in err_msg and "target" not in err_msg and "disconnect" not in err_msg:
                logger.error(f"Error enabling microphone: {e}")
            return False
    
    async def disable_microphone(self) -> bool:
        if not self.page: return False
        try:
            changed = await self.page.evaluate('''() => {
                const btn = document.querySelector("button[aria-label*='microphone' i], div[role='button'][aria-label*='microphone' i]");
                if (btn && btn.getAttribute('data-is-muted') === 'false') {
                    btn.click();
                    return true;
                }
                return false;
            }''')
            if changed:
                logger.info("Microphone disabled")
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" not in err_msg and "target" not in err_msg and "disconnect" not in err_msg:
                logger.error(f"Error disabling microphone: {e}")
            return False
    
    async def turn_off_microphone_at_join(self) -> bool:
        if not self.page: return False
        try:
            changed = await self.page.evaluate('''() => {
                const btn = document.querySelector("button[aria-label*='microphone' i], div[role='button'][aria-label*='microphone' i]");
                if (btn && btn.getAttribute('data-is-muted') !== 'true') {
                    btn.click();
                    return true;
                }
                return false;
            }''')
            if changed:
                logger.info("Microphone turned off at join screen")
                await asyncio.sleep(0.5)
                return True
            return False
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" not in err_msg and "target" not in err_msg and "disconnect" not in err_msg:
                logger.error(f"Error turning off microphone at join screen: {e}")
            return False
