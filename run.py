import os
import sys
import asyncio

# ضبط مخرجات الشاشة لتدعم UTF-8 على ويندوز
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# إضافة مجلد backend إلى مسار بايثون
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CURRENT_DIR, "backend"))

import uvicorn
from app.main import app
from app.core.config import settings
from app.services.telegram_bot import TelegramBotRunner

async def main():
    print("=" * 60)
    print(f"Starting {settings.PROJECT_NAME}...")
    print(f"Web Dashboard: http://127.0.0.1:8000/dashboard")
    print(f"Telegram Bot: https://t.me/my_smart_ops_bot")
    print("=" * 60)

    tasks = []

    # تشغيل بوت تيليجرام في الخلفية
    if settings.TELEGRAM_BOT_TOKEN:
        bot_runner = TelegramBotRunner()
        bot_task = asyncio.create_task(bot_runner.start_polling())
        tasks.append(bot_task)
        print("Telegram Bot connected and polling active.")

    # تشغيل خادم Uvicorn للوحة التحكم
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
