import httpx
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.schema import Organization, Branch
from app.models.extraction_schemas import ExtractedDocumentData
from app.services.ai_parser import AIParserService
from app.services.validator import FinancialValidator

router = APIRouter(prefix="/webhooks", tags=["Chat Webhooks (Telegram / WhatsApp)"])

@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    نقطة استقبال رسائل تيليجرام عبر الويب هوك (في حال الرغبة بالربط عبر Webhook).
    """
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    photo = message.get("photo", [])

    if not chat_id:
        return {"status": "ignored"}

    # الرد على أمر البدء الترحيبي
    if text == "/start":
        welcome_msg = (
            "👋 أهلاً بك في المساعد المالي والتنفيذي والضريبي الذكي!\n\n"
            "📸 يمكنك إرسال صورة إغلاق الكاشير (Z-Report) أو أي إيصال مشتريات ومصروفات وسنقوم بتدقيقها فورياً."
        )
        return {"status": "ok", "reply": welcome_msg}

    return {
        "status": "received",
        "chat_id": chat_id,
        "note": "تم استلام الرسالة وجاري المعالجة."
    }

@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    نقطة استقبال رسائل واتساب عبر WhatsApp Business Cloud API.
    """
    data = await request.json()
    return {"status": "ok", "provider": "whatsapp_cloud_api"}
