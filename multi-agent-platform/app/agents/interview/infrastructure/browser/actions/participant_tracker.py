# app/infrastructure/browser/actions/participant_tracker.py

import logging
import re
import asyncio
from typing import Optional, List
from playwright.async_api import Page

logger = logging.getLogger(__name__)

class ParticipantTracker:

    def __init__(self, page: Page):
        self.page = page
    
    async def _execute_js_safely(self, script: str, error_msg: str = "JS execution failed"):
        try:
            if self.page.is_closed():
                return -1
            return await self.page.evaluate(script)
        except Exception as e:
            err_msg = str(e).lower()
            if "closed" in err_msg or "target" in err_msg or "disconnect" in err_msg:
                return -1
            logger.error(f"{error_msg}: {e}")
            return None
    
    async def get_participant_count(self) -> int:
        if not self.page or self.page.is_closed():
            return -1
        
        # Method 1: Count unique data-participant-id attributes
        count = await self._count_via_participant_ids()
        if count == -1: return -1
        if count and count >= 1:
            return count
        
        # Method 2: Fallback to video elements
        count = await self._count_via_visible_videos()
        if count == -1: return -1
        if count and count >= 1:
            return count
            
        return 1
    
    async def get_active_participant_names(self) -> List[str]:
        """
        Scrapes participant names while aggressively filtering UI artifacts and icon codes.
        """
        script = """
        () => {
            const names = [];
            
            // BLOCKLIST: Common Google Material Icon ligatures and UI terms
            const ignoreTerms = [
                'keep_outline', 'frame_person', 'monitor', 'mic', 'mic_off', 'videocam', 
                'videocam_off', 'more_vert', 'present_to_all', 'call_end', 'info', 
                'people', 'chat', 'activities', 'lock', 'devices', 'contributors', 
                'meeting host', 'you', 'pin', 'tile', 'grid_view', 'remove'
            ];

            document.querySelectorAll('[data-participant-id]').forEach(el => {
                let candidateName = null;
                const textContent = el.innerText || "";
                
                // 1. COMPANION CHECK (Priority)
                if (textContent.includes('(Companion)')) {
                     const parts = textContent.split('\\n');
                     if (parts.length > 0) {
                         // Usually the name is the first line
                         const potentialName = parts[0].trim();
                         if (potentialName.length > 1 && !ignoreTerms.includes(potentialName.toLowerCase())) {
                             candidateName = potentialName + " (Companion)";
                         }
                     }
                }

                // 2. DEVICES TILE CHECK
                if (!candidateName) {
                    const lower = textContent.toLowerCase();
                    if (lower.includes('your devices') || (lower.includes('devices') && lower.length < 15)) {
                        candidateName = "devices"; 
                    }
                }

                // 3. ARIA LABEL (Best source for real names)
                if (!candidateName) {
                    const label = el.getAttribute('aria-label');
                    if (label) {
                        const cleanLabel = label.trim();
                        // Ensure the label isn't just an icon name
                        if (!ignoreTerms.includes(cleanLabel.toLowerCase())) {
                            candidateName = cleanLabel;
                        }
                    }
                }
                
                // 4. INNER TEXT FALLBACK (Risky, needs strict filtering)
                if (!candidateName) {
                    const lines = textContent.split('\\n');
                    for (let line of lines) {
                        let clean = line.trim();
                        let lower = clean.toLowerCase();
                        
                        if (clean.length < 2) continue;
                        if (ignoreTerms.includes(lower)) continue; // Exact match ignore
                        if (lower.includes(' joined')) continue;   // Ignore "X joined" notifications
                        
                        // Heuristic: Icon names are usually single words in snake_case
                        if (lower.includes('_') && !lower.includes(' ')) continue; 

                        candidateName = clean;
                        break; 
                    }
                }

                if (candidateName) {
                    names.push(candidateName);
                }
            });
            return names;
        }
        """
        raw_names = await self._execute_js_safely(script, "Name scraping failed")
        if not raw_names: return []

        cleaned_names = []
        for n in raw_names:
            n_clean = n.strip()
            
            # Remove "joined" notification suffix if it slipped through
            n_clean = re.sub(r'\s+joined$', '', n_clean, flags=re.IGNORECASE)
            
            # Standard Cleanups
            n_clean = re.sub(r'\s*\(You\)', '', n_clean, flags=re.IGNORECASE)
            n_clean = re.sub(r'\s*\(Presentation\)', '', n_clean, flags=re.IGNORECASE)
            
            # Final Sanity Check: Don't add if it looks like an icon (snake_case single word)
            if "_" in n_clean and " " not in n_clean:
                continue

            if n_clean:
                cleaned_names.append(n_clean)
        
        return cleaned_names
    
    async def _count_via_participant_ids(self) -> Optional[int]:
        script = """
        () => {
            const elements = document.querySelectorAll('[data-participant-id]');
            const uniqueIds = new Set();
            elements.forEach(el => {
                const id = el.getAttribute('data-participant-id');
                if (id) uniqueIds.add(id);
            });
            return uniqueIds.size;
        }
        """
        return await self._execute_js_safely(script, "Participant ID count failed")
    
    async def _count_via_button_text(self) -> Optional[int]:
        try:
            button = self.page.locator("button[aria-label*='participants ('], button[aria-label*='Show everyone (']").first
            if await button.count() > 0:
                button_text = await button.inner_text() or await button.get_attribute('aria-label')
                match = re.search(r'\((\d+)\)', button_text)
                
                if match:
                    return int(match.group(1))
        except Exception as e:
            logger.debug(f"Button text count failed: {e}")
        
        return None
    
    async def _count_via_visible_videos(self) -> Optional[int]:
        script = """
        () => {
            return Array.from(document.querySelectorAll('video'))
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) 
                        && rect.width > 50 && rect.height > 50;
                }).length;
        }
        """
        return await self._execute_js_safely(script, "Video count failed")
    
    async def is_candidate_present(self, required_count: int = 2) -> bool:
        current_count = await self.get_participant_count()
        return current_count == required_count
    
    async def wait_for_participant_count(
        self, 
        expected_count: int, 
        timeout: int = 30,
        check_interval: float = 2.0
    ) -> bool:

        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            current_count = await self.get_participant_count()
            
            if current_count == expected_count:
                logger.info(f"✓ Reached expected participant count: {expected_count}")
                return True
            
            logger.debug(
                f"Current count: {current_count}, "
                f"Expected: {expected_count}, "
                f"Elapsed: {int(time.time() - start_time)}s"
            )
            
            await asyncio.sleep(check_interval)
        
        logger.warning(f"Timeout waiting for participant count {expected_count}")
        return False
