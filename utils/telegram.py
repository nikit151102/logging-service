import requests
import os
import logging

logger = logging.getLogger("telegram-sender")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7352736287:AAEbcAIG7Re5C93yoGRzXK66opRw7EZ0zgo")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002326002578")

def send_error_to_telegram(message: str, topic_id: str, level: str):
    """
    Отправляет сообщение в Telegram.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured. Skipping send.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    if len(message) > 4000:
        message = message[:4000] + "\n... (trimmed)"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "message_thread_id": topic_id,
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False