from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Branch, Transaction, TransactionItem, Document, AuditFlag

init_db()
db = SessionLocal()

# مسح كافة البيانات الوهمية القديمة
deleted_flags = db.query(AuditFlag).delete()
deleted_items = db.query(TransactionItem).delete()
deleted_txs = db.query(Transaction).delete()
deleted_docs = db.query(Document).delete()
deleted_branches = db.query(Branch).delete()
deleted_orgs = db.query(Organization).delete()

# إنشاء منشأة نظيفة وواحدة فقط بدون أي عمليات وهمية
clean_org = Organization(
    name="المؤسسة التجارية",
    industry_type="تجارة وخدمات",
    currency="JOD",
    is_tax_registered=True,
    tax_filing_period="MONTHLY"
)
db.add(clean_org)
db.commit()

print(f"تم تنظيف قاعدة البيانات بنجاح: تم حذف {deleted_txs} عملية قديمة وتصفير كافة السجلات.")
print(f"المنشأة الحالية النظيفة: {clean_org.name} (ID: {clean_org.id})")
db.close()
