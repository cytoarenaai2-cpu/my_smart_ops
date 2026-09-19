import os
import sys
import asyncio

# ضبط مخرجات الشاشة لتدعم UTF-8 على ويندوز
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

# إضافة مجلد backend إلى مسار بايثون
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CURRENT_DIR, "backend"))

import uvicorn
from app.main import app
from app.core.config import settings
from app.services.telegram_bot import multi_bot_manager

async def main():
    print("=" * 60)
    print(f"Starting {settings.PROJECT_NAME} (Multi-Tenant SaaS)...")
    print(f"Web Dashboard: http://127.0.0.1:8000/dashboard")
    print("=" * 60)

    # تشغيل منظومة البوتات المتعددة للمنشآت
    bot_init_task = asyncio.create_task(multi_bot_manager.start_all_bots())

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
        if not bot_init_task.done():
            bot_init_task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
