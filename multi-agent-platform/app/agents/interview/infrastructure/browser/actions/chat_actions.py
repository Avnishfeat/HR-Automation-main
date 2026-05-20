# app/infrastructure/browser/actions/chat_actions.py
import logging
import asyncio
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

class ChatActions:
    def __init__(self, page: Page):
        self.page = page

    async def send_message(self, message: str) -> bool:
        """Send a chat message in the Google Meet"""
        try:
            if not await self._open_chat_panel():
                return False

            # Wait for chat input
            chat_input = self.page.locator("textarea[aria-label='Send a message to everyone'], input[aria-label='Chat message']")
            
            try:
                await chat_input.first.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                logger.error("Chat input not found or not visible")
                return False

            # Clear and send
            await chat_input.first.fill(message)
            
            # Find and click send button
            send_button = self.page.locator("button[aria-label='Send message']").first
            if await send_button.count() > 0 and await send_button.is_enabled():
                await send_button.click()
            else:
                # Fallback to pressing Enter
                await chat_input.first.press("Enter")
                
            logger.info("Chat message sent")
            await asyncio.sleep(0.5) # Brief pause after sending
            return True

        except Exception as e:
            logger.error(f"Error sending chat message: {e}")
            return False

    async def _open_chat_panel(self) -> bool:
        """Ensure the chat panel is open"""
        try:
            # Check if chat is already open by looking for the chat input
            chat_input = self.page.locator("textarea[aria-label='Send a message to everyone'], input[aria-label='Chat message']")
            if await chat_input.count() > 0 and await chat_input.first.is_visible():
                return True

            # Find and click the chat icon button
            chat_button = self.page.locator("button[aria-label='Chat with everyone']").first
            
            try:
                await chat_button.wait_for(state="visible", timeout=5000)
                await chat_button.click()
                await asyncio.sleep(1) # Wait for panel animation
                
                # Verify it opened
                await chat_input.first.wait_for(state="visible", timeout=3000)
                return True
            except PlaywrightTimeoutError:
                logger.warning("Could not open chat panel")
                return False

        except Exception as e:
            logger.error(f"Error opening chat panel: {e}")
            return False
