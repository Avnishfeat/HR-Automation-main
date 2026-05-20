import logging
import time
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def dispatch_webhook(webhook_url: str, payload: Dict[str, Any], max_retries: int = 3, initial_backoff: float = 2.0, headers: Optional[Dict[str, str]] = None) -> bool:
    """
    Synchronously dispatches a webhook to the provided URL with the given payload.
    Implements a retry mechanism for robust delivery.
    """
    if not webhook_url:
        logger.warning("No webhook URL provided. Cannot dispatch payload.")
        return False
        
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Dispatching webhook to {webhook_url} (Attempt {attempt}/{max_retries})")
            # Use a timeout so background task doesn't hang indefinitely
            response = requests.post(webhook_url, json=payload, timeout=10, headers=headers)
            
            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"Webhook dispatched successfully: {response.status_code}")
                return True
            else:
                logger.warning(f"Webhook dispatch failed with status {response.status_code}: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to dispatch webhook (Attempt {attempt}/{max_retries}): {e}")
            
        if attempt < max_retries:
            sleep_time = initial_backoff * (2 ** (attempt - 1))
            logger.info(f"Retrying webhook in {sleep_time} seconds...")
            time.sleep(sleep_time)
            
    logger.error(f"Failed to dispatch webhook after {max_retries} attempts.")
    return False

