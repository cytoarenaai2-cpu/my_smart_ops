import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import documents, analytics, webhooks, tax

# تحديد مسار مجلد واجهة المستخدم frontend
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", "frontend"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # تهيئة جداول قاعدة البيانات عند الإطلاق
    init_db()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="نظام المساعد المالي والتنفيذي والامتثال الضريبي الذكي للمنشآت في الأردن (JoFotara Ready)",
    lifespan=lifespan
)

# تمكين CORS لربط لوحة التحكم بسلاسة
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تضمين نقاط النهاية البرمجية API Routes
app.include_router(documents.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(webhooks.router, prefix=settings.API_V1_STR)
app.include_router(tax.router, prefix=settings.API_V1_STR)

# تقديم ملفات الواجهة الأمامية Dashboard
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/dashboard")
def get_dashboard():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend index.html not found"}

@app.get("/")
def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "dashboard_url": "/dashboard",
        "docs_url": "/docs"
    }

@app.get("/api/health")
def health_check():
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "currency": settings.DEFAULT_CURRENCY
    }
