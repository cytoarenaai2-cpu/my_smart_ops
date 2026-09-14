import uuid
from datetime import date, timedelta
from app.core.database import SessionLocal, init_db
from app.models.schema import Organization, Branch, Transaction, AuditFlag

def seed_demo_data():
    init_db()
    db = SessionLocal()

    # 1. Clean existing demo data if needed
    db.query(AuditFlag).delete()
    db.query(Transaction).delete()
    db.query(Branch).delete()
    db.query(Organization).delete()
    db.commit()

    # 2. Create Organization
    org = Organization(
        id=str(uuid.uuid4()),
        name="سلسلة مطاعم ومخابز الأفق",
        industry_type="مطاعم ومخابز",
        currency="JOD",
        tax_number="100482910",
        is_tax_registered=True,
        tax_filing_period="MONTHLY"
    )
    db.add(org)
    db.commit()
    db.refresh(org)

    # 3. Create Branches
    b1 = Branch(id=str(uuid.uuid4()), organization_id=org.id, name="فرع خلدا", manager_name="أحمد الخالدي")
    b2 = Branch(id=str(uuid.uuid4()), organization_id=org.id, name="فرع العبدلي مول", manager_name="سالم النجار")
    b3 = Branch(id=str(uuid.uuid4()), organization_id=org.id, name="فرع الشميساني", manager_name="عمر حداد")
    db.add_all([b1, b2, b3])
    db.commit()

    # 4. Create Historical & Today Transactions (past 5 days)
    today = date.today()

    demo_days = [
        {"days_ago": 4, "sales": 820.0, "tax": 131.2, "exp": 180.0, "cash": 350.0, "card": 320.0, "cliq": 150.0},
        {"days_ago": 3, "sales": 950.0, "tax": 152.0, "exp": 220.0, "cash": 400.0, "card": 380.0, "cliq": 170.0},
        {"days_ago": 2, "sales": 1100.0, "tax": 176.0, "exp": 150.0, "cash": 450.0, "card": 450.0, "cliq": 200.0},
        {"days_ago": 1, "sales": 1350.0, "tax": 216.0, "exp": 310.0, "cash": 600.0, "card": 500.0, "cliq": 250.0},
        {"days_ago": 0, "sales": 1420.0, "tax": 227.2, "exp": 190.0, "cash": 620.0, "card": 540.0, "cliq": 260.0},
    ]

    for d in demo_days:
        tx_date = today - timedelta(days=d["days_ago"])
        
        # Sales Z-Report
        sale_tx = Transaction(
            organization_id=org.id,
            branch_id=b1.id if d["days_ago"] % 2 == 0 else b2.id,
            transaction_type="SALE",
            transaction_date=tx_date,
            invoice_number=f"Z-{tx_date.strftime('%Y%m%d')}-01",
            merchant_or_supplier_name="فرع خلدا" if d["days_ago"] % 2 == 0 else "فرع العبدلي مول",
            subtotal=d["sales"],
            tax_amount=d["tax"],
            total_amount=round(d["sales"] + d["tax"], 3),
            payment_breakdown={
                "cash": d["cash"],
                "card": d["card"],
                "cliq": d["cliq"],
                "delivery_apps": round((d["sales"] + d["tax"]) - (d["cash"] + d["card"] + d["cliq"]), 3)
            },
            tax_status="STANDARD_16",
            notes="كشف إغلاق كاشير يومي معتمد"
        )
        
        # Expense receipt
        exp_tx = Transaction(
            organization_id=org.id,
            branch_id=b1.id,
            transaction_type="EXPENSE",
            transaction_date=tx_date,
            invoice_number=f"EXP-{tx_date.strftime('%Y%m%d')}-09",
            merchant_or_supplier_name="شركة التوريدات الوطنية",
            subtotal=d["exp"],
            tax_amount=round(d["exp"] * 0.16, 3),
            total_amount=round(d["exp"] * 1.16, 3),
            payment_breakdown={"cash": round(d["exp"] * 1.16, 3)},
            supplier_tax_id="20039182" if d["days_ago"] != 0 else None, # Today missing tax ID for audit flag demo
            is_deductible_expense=(d["days_ago"] != 0),
            notes="شراء زيوت ومواد غذائية خام"
        )
        db.add_all([sale_tx, exp_tx])

    # 5. Add a realistic Audit Flag for the demo
    flag = AuditFlag(
        organization_id=org.id,
        severity="WARNING",
        flag_type="MISSING_TAX_INVOICE",
        message="تنبيه ضريبي (JoFotara): فاتورة توريد زيوت بقيمة 620.000 د.أ غير معززة بالرقم الضريبي للمورد. بموجب تعليمات نيسان 2025 قد لا تُقبل ضريبياً."
    )
    db.add(flag)
    db.commit()
    db.close()
    print("Demo data seeded successfully!")

if __name__ == "__main__":
    seed_demo_data()
