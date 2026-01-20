# app/infrastructure/selenium/actions/video_capture.py
import logging
import base64
from typing import Optional, Tuple
from selenium.common.exceptions import JavascriptException

logger = logging.getLogger(__name__)


class VideoCapture:
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
    
    def capture_candidate_video_js(self) -> Optional[Tuple[bytes, int, int]]:
        script = """
        function isVisible(elem) {
            if (!elem) return false;
            return !!( elem.offsetWidth || elem.offsetHeight || elem.getClientRects().length );
        }
        
        const videos = Array.from(document.querySelectorAll('video'));
        let candidateVideo = null;
        let maxArea = 0;
        
        for (let video of videos) {
            // Skip invalid videos
            if (video.paused || video.ended || !video.videoWidth || 
                video.videoWidth < 100 || video.videoHeight < 100) continue;
            
            const rect = video.getBoundingClientRect();
            
            // Skip off-screen videos
            if (rect.width <= 0 || rect.height <= 0 || 
                rect.top < -5 || rect.left < -5 || 
                rect.bottom > (window.innerHeight + 5) || 
                rect.right > (window.innerWidth + 5)) continue;
            
            // Skip self-view
            let parent = video.closest('[data-self-view="true"], [jsname="Ne3sF"]');
            if (parent) continue;
            
            // Find largest video
            const area = rect.width * rect.height;
            if (area > maxArea) {
                maxArea = area;
                candidateVideo = video;
            }
        }
        
        if (!candidateVideo) return null;
        
        // Capture to canvas
        const canvas = document.createElement('canvas');
        canvas.width = candidateVideo.videoWidth;
        canvas.height = candidateVideo.videoHeight;
        
        const ctx = canvas.getContext('2d');
        ctx.drawImage(candidateVideo, 0, 0, canvas.width, canvas.height);
        
        return {
            data: canvas.toDataURL('image/jpeg', 0.85),
            width: canvas.width,
            height: canvas.height
        };
        """
        
        result = self._execute_js_safely(script, "Video capture failed")
        
        if not result or not result.get('data'):
            return None
        
        try:
            data_url = result['data']
            if not data_url.startswith('data:image/jpeg;base64,'):
                logger.debug("Invalid data URL format")
                return None
            
            base64_data = data_url.split(',', 1)[1]
            image_bytes = base64.b64decode(base64_data)
            width = result.get('width', 0)
            height = result.get('height', 0)
            
            if width > 0 and height > 0:
                return (image_bytes, width, height)
            else:
                logger.debug("Invalid dimensions")
                return None
                
        except Exception as e:
            logger.error(f"Failed to decode captured image: {e}")
            return None
    
    def capture_screenshot(self) -> Optional[bytes]:
        try:
            if not self.driver:
                return None
                
            logger.debug("Attempting screenshot capture (fallback)...")
            screenshot_bytes = self.driver.get_screenshot_as_png()
            
            if screenshot_bytes:
                logger.debug("Screenshot captured")
                return screenshot_bytes
            else:
                logger.warning("Screenshot empty")
                return None
                
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}", exc_info=True)
            return None