let trendChartInstance = null;
let paymentChartInstance = null;

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
  fetchAllData();
  setupUploadForm();
  setupBriefButton();
  setupTaxModal();
  setupResetButton();

  document.getElementById("refreshBtn").addEventListener("click", () => {
    fetchAllData();
  });
});

async function fetchAllData() {
  await Promise.all([
    fetchDashboardData(),
    fetchTaxData(),
    fetchRecentTransactions()
  ]);
}

// 1. Fetch dashboard metrics
async function fetchDashboardData() {
  try {
    const res = await fetch("/api/v1/analytics/dashboard-summary?days=30");
    if (!res.ok) throw new Error("فشل جلب بيانات لوحة التحكم");
    const data = await res.json();

    renderKPIs(data.kpis, data.recent_audit_flags);
    renderTrendChart(data.daily_trend);
    renderPaymentChart(data.payment_distribution);
  } catch (err) {
    console.error("Dashboard data error:", err);
  }
}

// 2. Fetch Phase 2 Tax & JoFotara Data
async function fetchTaxData() {
  try {
    const sumRes = await fetch("/api/v1/tax/summary?days=30");
    if (sumRes.ok) {
      const sumData = await sumRes.json();
      renderTaxPanel(sumData.tax_position);
    }

    const riskRes = await fetch("/api/v1/tax/risk-invoices");
    if (riskRes.ok) {
      const riskData = await riskRes.json();
      renderRiskInvoices(riskData);
    }
  } catch (err) {
    console.error("Tax data error:", err);
  }
}

// 3. Fetch Recent Transactions (The Real Audit Log)
async function fetchRecentTransactions() {
  try {
    const res = await fetch("/api/v1/analytics/recent-transactions?limit=50");
    if (!res.ok) throw new Error("فشل جلب سجل العمليات");
    const txs = await res.json();

    const badge = document.getElementById("txCountBadge");
    badge.textContent = `${txs.length} عمليات مسجلة`;

    const tbody = document.getElementById("transactionsTableBody");
    if (!txs || txs.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-8 text-slate-400">
            لا توجد أي عمليات مسجلة حتى الآن. سجل أول عملية من هاتفك عبر تيليجرام أو ارفع صورة فاتورة لتظهر هنا فوراً!
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = txs.map(t => {
      const pb = t.payment_breakdown || {};
      const paymentsText = [];
      if (pb.cash) paymentsText.push(`كاش: ${Number(pb.cash).toFixed(2)}`);
      if (pb.card) paymentsText.push(`بطاقة: ${Number(pb.card).toFixed(2)}`);
      if (pb.cliq) paymentsText.push(`كليك: ${Number(pb.cliq).toFixed(2)}`);
      if (pb.delivery_apps) paymentsText.push(`توصيل: ${Number(pb.delivery_apps).toFixed(2)}`);
      
      const isSale = t.raw_type === "SALE";
      const typeBadgeClass = isSale ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" : "bg-rose-500/20 text-rose-300 border-rose-500/30";
      const isApproved = t.status === "معتمد";
      const statusBadgeClass = isApproved ? "text-emerald-400 font-semibold" : "text-amber-400 font-semibold";

      let statusHtml = `<div class="${statusBadgeClass}">${t.status}</div>`;
      if (!isApproved && t.flags && t.flags.length > 0) {
        statusHtml += `
          <div class="text-[10px] text-amber-300/80 mt-1 max-w-[220px] truncate" title="${t.flags.join(' | ')}">
            ⚠️ ${t.flags[0]}
          </div>
        `;
      }

      let actionHtml = '';
      if (!isApproved) {
        actionHtml = `
          <button onclick="approveTransaction('${t.id}')" 
                  id="approve-btn-${t.id}"
                  title="اعتماد وتأكيد مطابقة العملية بعد مراجعتها"
                  class="bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white border border-emerald-500/40 hover:border-emerald-500 px-3 py-1.5 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer">
            <i data-lucide="check-check" class="w-3.5 h-3.5"></i>
            <span>اعتماد العملية</span>
          </button>
        `;
      } else {
        actionHtml = `
          <span class="inline-flex items-center gap-1 text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 px-2.5 py-1 rounded-full text-[11px] font-medium">
            <i data-lucide="shield-check" class="w-3.5 h-3.5"></i>
            <span>معتمد</span>
          </span>
        `;
      }

      return `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="p-3 text-slate-400 font-mono">${t.date}</td>
          <td class="p-3">
            <span class="border ${typeBadgeClass} px-2 py-0.5 rounded text-[11px] font-semibold">${t.type}</span>
          </td>
          <td class="p-3 font-semibold text-slate-200">${t.merchant_or_branch}</td>
          <td class="p-3 font-mono font-bold text-white text-sm">${Number(t.total_amount).toFixed(3)} د.أ</td>
          <td class="p-3 text-slate-300 text-[11px]">
            ${paymentsText.length > 0 ? paymentsText.join(" | ") : "نقد"}
          </td>
          <td class="p-3 font-mono text-slate-400">${Number(t.tax_amount).toFixed(3)} د.أ</td>
          <td class="p-3">${statusHtml}</td>
          <td class="p-3 text-center">${actionHtml}</td>
        </tr>
      `;
    }).join("");

    if (window.lucide) {
      window.lucide.createIcons();
    }

  } catch (err) {
    console.error("Transactions log error:", err);
  }
}

// Handler for manual approval of reviewed transactions
window.approveTransaction = async function(txId) {
  const btn = document.getElementById(`approve-btn-${txId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block animate-spin text-xs">⏳</span> جاري الاعتماد...`;
  }

  try {
    const res = await fetch(`/api/v1/analytics/transactions/${txId}/approve`, {
      method: "POST"
    });
    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(errJson.detail || "فشل اعتماد العملية");
    }

    const data = await res.json();
    showToast(data.message, "success");

    // تحديث كافة البيانات في لوحة التحكم وسجل العمليات فورياً
    await fetchAllData();
  } catch (err) {
    alert("حدث خطأ أثناء اعتماد العملية: " + err.message);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="check-check" class="w-3.5 h-3.5"></i> <span>اعتماد العملية</span>`;
      if (window.lucide) window.lucide.createIcons();
    }
  }
};

// Toast notification helper
function showToast(message, type = "success") {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    container.className = "fixed bottom-5 left-5 z-50 flex flex-col gap-2 pointer-events-none";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  const isSuccess = type === "success";
  const bg = isSuccess ? "bg-emerald-950/95 border-emerald-500/50 text-emerald-200" : "bg-rose-950/95 border-rose-500/50 text-rose-200";
  const icon = isSuccess ? "check-circle-2" : "alert-circle";
  toast.className = `pointer-events-auto px-4 py-3 rounded-xl border shadow-2xl text-xs font-medium transition-all duration-300 transform translate-y-2 opacity-0 flex items-center gap-2.5 backdrop-blur-md ${bg}`;
  toast.innerHTML = `<i data-lucide="${icon}" class="w-4 h-4 flex-shrink-0 text-emerald-400"></i> <span>${message}</span>`;
  container.appendChild(toast);

  if (window.lucide) window.lucide.createIcons();

  setTimeout(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  }, 10);

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// 4. Render KPIs
function renderKPIs(kpis, flags) {
  document.getElementById("kpiSales").innerHTML = `${Number(kpis.total_sales).toFixed(3)} <span class="text-base font-normal text-slate-400">د.أ</span>`;
  document.getElementById("kpiExpenses").innerHTML = `${Number(kpis.total_expenses).toFixed(3)} <span class="text-base font-normal text-slate-400">د.أ</span>`;
  
  const net = Number(kpis.net_cash_flow);
  const netEl = document.getElementById("kpiNet");
  netEl.innerHTML = `${net.toFixed(3)} <span class="text-base font-normal text-slate-400">د.أ</span>`;
  if (net < 0) {
    netEl.classList.remove("text-white");
    netEl.classList.add("text-rose-400");
  } else {
    netEl.classList.remove("text-rose-400");
    netEl.classList.add("text-white");
  }

  const unresolvedCount = flags.length;
  document.getElementById("kpiFlagsCount").textContent = `${unresolvedCount} تنبيهات تدقيق`;

  const score = Math.max(70, 100 - (unresolvedCount * 5));
  document.getElementById("kpiCompliance").textContent = `${score}%`;
}

// 5. Render Jordan Tax Panel
function renderTaxPanel(pos) {
  document.getElementById("taxOutput").textContent = `${Number(pos.output_tax_collected).toFixed(3)} د.أ`;
  document.getElementById("taxInput").textContent = `${Number(pos.eligible_input_tax).toFixed(3)} د.أ`;
  document.getElementById("taxLost").textContent = `${Number(pos.lost_input_tax_deduction).toFixed(3)} د.أ`;

  const netEl = document.getElementById("taxNet");
  const netLabel = document.getElementById("taxNetLabel");

  if (pos.net_sales_tax_payable > 0) {
    netEl.textContent = `${Number(pos.net_sales_tax_payable).toFixed(3)} د.أ`;
    netLabel.textContent = "مستحق للدائرة (للدفع)";
    netLabel.className = "text-[10px] text-amber-400 font-semibold";
  } else {
    netEl.textContent = `${Number(pos.tax_credit_carried_forward).toFixed(3)} د.أ`;
    netLabel.textContent = "رصيد دائن مدور (لصالحك)";
    netLabel.className = "text-[10px] text-emerald-400 font-semibold";
  }
}

// 6. Render Risk Invoices Table
function renderRiskInvoices(invoices) {
  const badge = document.getElementById("riskInvoicesBadge");
  badge.textContent = `${invoices.length} فواتير`;
  if (invoices.length > 0) {
    badge.className = "text-xs bg-rose-500/20 text-rose-300 border border-rose-500/30 px-2.5 py-1 rounded-full font-semibold";
  } else {
    badge.className = "text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-full font-semibold";
    badge.textContent = "0 مخاطر";
  }

  const tbody = document.getElementById("riskInvoicesTable");
  if (!invoices || invoices.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center py-6 text-emerald-400 font-medium">
          ✅ جميع فواتير المشتريات معززة بأرقام ضريبية ومطابقة لنظام الفوترة الوطني.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = invoices.map(inv => `
    <tr class="hover:bg-slate-800/40 transition">
      <td class="p-2.5 font-mono text-slate-200">${inv.invoice_number}</td>
      <td class="p-2.5 text-slate-400">${inv.date}</td>
      <td class="p-2.5 text-slate-200 font-medium">${inv.supplier_or_merchant}</td>
      <td class="p-2.5 font-mono font-bold text-white">${Number(inv.amount).toFixed(3)} د.أ</td>
      <td class="p-2.5 font-mono text-rose-400 font-semibold">${Number(inv.tax_amount).toFixed(3)} د.أ</td>
      <td class="p-2.5 text-rose-300">
        <span class="bg-rose-950/60 border border-rose-500/30 px-2 py-0.5 rounded text-[11px]">${inv.risk_reason}</span>
      </td>
    </tr>
  `).join("");
}

// 7. Trend Chart
function renderTrendChart(dailyData) {
  const ctx = document.getElementById("trendChart").getContext("2d");
  const labels = dailyData.map(d => d.date);
  const sales = dailyData.map(d => d.sales);
  const expenses = dailyData.map(d => d.expenses);

  if (trendChartInstance) trendChartInstance.destroy();

  trendChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels.length > 0 ? labels : ["اليوم"],
      datasets: [
        {
          label: "المبيعات (د.أ)",
          data: sales.length > 0 ? sales : [0],
          backgroundColor: "#10b981",
          borderRadius: 6,
        },
        {
          label: "المصروفات (د.أ)",
          data: expenses.length > 0 ? expenses : [0],
          backgroundColor: "#f43f5e",
          borderRadius: 6,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: "#94a3b8", font: { family: "Cairo" } } }
      },
      scales: {
        x: { grid: { color: "rgba(51, 65, 85, 0.4)" }, ticks: { color: "#94a3b8", font: { family: "Cairo" } } },
        y: { grid: { color: "rgba(51, 65, 85, 0.4)" }, ticks: { color: "#94a3b8", font: { family: "Cairo" } } }
      }
    }
  });
}

// 8. Payment Chart
function renderPaymentChart(distribution) {
  const ctx = document.getElementById("paymentChart").getContext("2d");
  const cash = distribution.cash || 0;
  const card = distribution.card || 0;
  const cliq = distribution.cliq || 0;
  const delivery = distribution.delivery_apps || 0;

  const total = cash + card + cliq + delivery;
  const dataValues = total > 0 ? [cash, card, cliq, delivery] : [0, 0, 0, 0];

  if (paymentChartInstance) paymentChartInstance.destroy();

  paymentChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["كاش (نقدي)", "بطاقات (POS)", "كليك (CliQ)", "تطبيقات التوصيل"],
      datasets: [{
        data: total > 0 ? dataValues : [1],
        backgroundColor: total > 0 ? ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b"] : ["#334155"],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      cutout: "70%"
    }
  });

  const legendEl = document.getElementById("paymentLegend");
  legendEl.innerHTML = `
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span><span>كاش: ${cash.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span><span>بطاقات: ${card.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span><span>كليك: ${cliq.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span><span>توصيل: ${delivery.toFixed(2)}</span></div>
  `;
}

// 9. Setup Upload Form
function setupUploadForm() {
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const uploadForm = document.getElementById("uploadForm");
  const textInput = document.getElementById("textNotesInput");
  const feedback = document.getElementById("uploadFeedback");
  const submitBtn = document.getElementById("submitBtn");

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      document.getElementById("selectedFileName").textContent = `📄 الملف المختار: ${fileInput.files[0].name}`;
      document.getElementById("selectedFileName").classList.add("text-emerald-400");
    }
  });

  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("border-emerald-500"); });
  dropZone.addEventListener("dragleave", () => { dropZone.classList.remove("border-emerald-500"); });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-emerald-500");
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      document.getElementById("selectedFileName").textContent = `📄 الملف المختار: ${fileInput.files[0].name}`;
      document.getElementById("selectedFileName").classList.add("text-emerald-400");
    }
  });

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    const notes = textInput.value.trim();

    if (!file && !notes) {
      alert("يرجى اختيار صورة فاتورة أو كتابة تسجيل مبيعات سريع.");
      return;
    }

    const formData = new FormData();
    if (file) formData.append("file", file);
    if (notes) formData.append("text_notes", notes);

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span>جاري المعالجة بالذكاء الاصطناعي...</span>`;
    feedback.className = "mt-4 p-4 rounded-xl text-xs bg-slate-900 border border-slate-700 text-slate-300 block";
    feedback.textContent = "⏳ جاري قراءة وتدقيق أرقام المستند الحقيقية...";

    try {
      const res = await fetch("/api/v1/documents/upload", { method: "POST", body: formData });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || "فشل معالجة المستند");

      feedback.className = "mt-4 p-4 rounded-xl text-xs bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 block";
      feedback.innerHTML = `
        <div class="font-bold text-sm mb-1">✅ ${result.message}</div>
        <div>نوع العملية: <strong>${result.extracted_summary.type}</strong> | القيمة المسجلة: <strong>${Number(result.extracted_summary.total_amount).toFixed(3)} د.أ</strong></div>
        <div class="mt-1">حالة الاعتماد: <span class="bg-emerald-500/20 px-2 py-0.5 rounded font-semibold">${result.validation_status}</span></div>
      `;

      fileInput.value = "";
      textInput.value = "";
      document.getElementById("selectedFileName").textContent = "يدعم JPG, PNG, PDF حتى 10MB";
      document.getElementById("selectedFileName").classList.remove("text-emerald-400");

      fetchAllData();
    } catch (err) {
      feedback.className = "mt-4 p-4 rounded-xl text-xs bg-rose-950/40 border border-rose-500/30 text-rose-300 block";
      feedback.textContent = `❌ خطأ: ${err.message}`;
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<i data-lucide="send" class="w-4 h-4"></i><span>تحليل وتدقيق</span>`;
      if (window.lucide) lucide.createIcons();
    }
  });
}

// 10. Setup WhatsApp Brief Button
function setupBriefButton() {
  const btn = document.getElementById("copyBriefBtn");
  btn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/v1/analytics/daily-brief");
      if (!res.ok) throw new Error("فشل استخراج التقرير");
      const data = await res.json();

      await navigator.clipboard.writeText(data.whatsapp_formatted_text);
      const original = btn.innerHTML;
      btn.innerHTML = `<span>✅ تم نسخ تقرير الصباح!</span>`;
      setTimeout(() => { btn.innerHTML = original; if (window.lucide) lucide.createIcons(); }, 2500);
    } catch (err) {
      alert("تعذر نسخ التقرير: " + err.message);
    }
  });
}

// 11. Setup Reset Data Button
function setupResetButton() {
  const resetBtn = document.getElementById("resetDataBtn");
  resetBtn.addEventListener("click", async () => {
    if (!confirm("هل أنت متأكد من رغبتك في تصفير كافة العمليات والمعاملات؟ سيعود النظام فارغاً 100% لتسجيل عملياتك الجديدة.")) {
      return;
    }

    try {
      const res = await fetch("/api/v1/analytics/reset-data", { method: "POST" });
      const data = await res.json();
      alert(data.message);
      fetchAllData();
    } catch (err) {
      alert("فشل تصفير البيانات: " + err.message);
    }
  });
}

// 12. Setup Tax Pre-Filing Report Modal
function setupTaxModal() {
  const modal = document.getElementById("taxModal");
  const openBtn = document.getElementById("openTaxReportBtn");
  const closeBtn1 = document.getElementById("closeTaxModalBtn");
  const closeBtn2 = document.getElementById("closeTaxModalBtn2");
  const printBtn = document.getElementById("printTaxReportBtn");
  const content = document.getElementById("taxModalContent");

  openBtn.addEventListener("click", async () => {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    content.innerHTML = `<p class="text-center py-8 text-slate-400">جاري تجميع بيانات الإقرار بناءً على العمليات الحقيقية...</p>`;

    try {
      const res = await fetch("/api/v1/tax/pre-filing-report?days=30");
      if (!res.ok) throw new Error("فشل جلب تقرير الإقرار");
      const r = await res.json();

      const m = r.metadata;
      const p = r.tax_position;
      const rec = r.payment_reconciliation;

      content.innerHTML = `
        <div class="bg-slate-800/80 p-4 rounded-xl border border-slate-700 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div><span class="text-slate-400">اسم المنشأة:</span> <div class="font-bold text-white">${m.organization_name}</div></div>
          <div><span class="text-slate-400">الرقم الضريبي:</span> <div class="font-bold text-sky-400 font-mono">${m.tax_number}</div></div>
          <div><span class="text-slate-400">تاريخ الإعداد:</span> <div class="font-medium text-slate-300">${m.report_generated_date}</div></div>
          <div><span class="text-slate-400">درجة الجاهزية:</span> <div class="font-bold ${m.is_audit_ready ? 'text-emerald-400' : 'text-amber-400'}">${m.compliance_score}% (${m.is_audit_ready ? 'جاهز للتقديم' : 'يتطلب مراجعة'})</div></div>
        </div>

        <div class="space-y-2">
          <h4 class="font-bold text-white text-sm">1. ملخص ضريبة المبيعات العامة (16%)</h4>
          <table class="w-full text-right border-collapse border border-slate-800 rounded-lg overflow-hidden">
            <tbody class="divide-y divide-slate-800 text-slate-200">
              <tr class="bg-slate-800/40"><td class="p-2 text-slate-300">إجمالي المبيعات الخاضعة للضريبة:</td><td class="p-2 font-mono font-bold">${Number(p.taxable_sales_subtotal).toFixed(3)} د.أ</td></tr>
              <tr><td class="p-2 text-slate-300">ضريبة المبيعات المحصلة (Output Tax 16%):</td><td class="p-2 font-mono font-bold text-sky-400">${Number(p.output_tax_collected).toFixed(3)} د.أ</td></tr>
              <tr class="bg-slate-800/40"><td class="p-2 text-slate-300">ضريبة المدخلات المقبولة للخصم (Input Tax):</td><td class="p-2 font-mono font-bold text-emerald-400">(${Number(p.eligible_input_tax).toFixed(3)}) د.أ</td></tr>
              <tr class="bg-sky-950/60 font-bold"><td class="p-2.5 text-sky-200 text-sm">صافي الضريبة العامة المستحقة للدائرة (أو رصيد دائن):</td><td class="p-2.5 font-mono text-base text-sky-300">${p.net_sales_tax_payable > 0 ? Number(p.net_sales_tax_payable).toFixed(3) + ' د.أ (للدفع)' : Number(p.tax_credit_carried_forward).toFixed(3) + ' د.أ (رصيد دائن)'}</td></tr>
            </tbody>
          </table>
        </div>

        <div class="space-y-2">
          <h4 class="font-bold text-white text-sm">2. مطابقة المبيعات مع وسائل التحصيل الفعلية (Reconciliation)</h4>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-slate-800/40 p-3 rounded-xl border border-slate-800">
            <div><span class="text-slate-400">كاش الصندوق:</span> <div class="font-mono font-bold">${Number(rec.cash_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">بطاقات (POS):</span> <div class="font-mono font-bold">${Number(rec.cards_pos_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">كليك (CliQ):</span> <div class="font-mono font-bold text-purple-400">${Number(rec.cliq_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">تطبيقات التوصيل:</span> <div class="font-mono font-bold">${Number(rec.delivery_collected).toFixed(3)} د.أ</div></div>
          </div>
        </div>

        <div class="bg-slate-800/50 p-4 rounded-xl border border-slate-700 space-y-2">
          <h4 class="font-bold text-amber-300 flex items-center gap-1.5">
            <i data-lucide="check-circle" class="w-4 h-4"></i>
            توصيات وملاحظات المحاسب القانوني (CPA Notes):
          </h4>
          <ul class="list-disc list-inside space-y-1 text-slate-300">
            ${r.cpa_recommendations.map(recText => `<li>${recText}</li>`).join("")}
          </ul>
        </div>

        <div class="text-[11px] text-slate-500 italic text-center pt-2">
          ${m.disclaimer}
        </div>
      `;

      if (window.lucide) lucide.createIcons();
    } catch (err) {
      content.innerHTML = `<p class="text-center py-8 text-rose-400">❌ حدث خطأ أثناء إعداد التقرير: ${err.message}</p>`;
    }
  });

  const closeModal = () => {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  };

  closeBtn1.addEventListener("click", closeModal);
  closeBtn2.addEventListener("click", closeModal);
  printBtn.addEventListener("click", () => window.print());
}
