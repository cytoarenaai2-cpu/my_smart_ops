let trendChartInstance = null;
let paymentChartInstance = null;

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
  fetchDashboardData();
  setupUploadForm();
  setupBriefButton();

  document.getElementById("refreshBtn").addEventListener("click", () => {
    fetchDashboardData();
  });
});

// 1. Fetch and render dashboard metrics
async function fetchDashboardData() {
  try {
    const res = await fetch("/api/v1/analytics/dashboard-summary?days=7");
    if (!res.ok) throw new Error("فشل جلب بيانات لوحة التحكم");
    const data = await res.json();

    renderKPIs(data.kpis, data.recent_audit_flags);
    renderTrendChart(data.daily_trend);
    renderPaymentChart(data.payment_distribution);
    renderAuditAlerts(data.recent_audit_flags);
    renderTaxWidget(data.kpis);
  } catch (err) {
    console.error("Dashboard data error:", err);
  }
}

// 2. Render KPIs
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
  document.getElementById("alertBadge").textContent = `${unresolvedCount} تنبيهات`;
  document.getElementById("kpiFlagsCount").textContent = `${unresolvedCount} تنبيهات تدقيق تحتاج مراجعة`;

  // Dynamic compliance score
  const score = Math.max(70, 100 - (unresolvedCount * 5));
  document.getElementById("kpiCompliance").textContent = `${score}%`;
}

// 3. Render Trend Chart (Sales vs Expenses)
function renderTrendChart(dailyData) {
  const ctx = document.getElementById("trendChart").getContext("2d");
  
  const labels = dailyData.map(d => d.date);
  const sales = dailyData.map(d => d.sales);
  const expenses = dailyData.map(d => d.expenses);

  if (trendChartInstance) {
    trendChartInstance.destroy();
  }

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
        legend: {
          labels: { color: "#94a3b8", font: { family: "Cairo" } }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#94a3b8", font: { family: "Cairo" } }
        },
        y: {
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: { color: "#94a3b8", font: { family: "Cairo" } }
        }
      }
    }
  });
}

// 4. Render Payment Channels Donut Chart
function renderPaymentChart(distribution) {
  const ctx = document.getElementById("paymentChart").getContext("2d");
  
  const cash = distribution.cash || 0;
  const card = distribution.card || 0;
  const cliq = distribution.cliq || 0;
  const delivery = distribution.delivery_apps || 0;

  const total = cash + card + cliq + delivery;
  const dataValues = total > 0 ? [cash, card, cliq, delivery] : [1, 0, 0, 0];

  if (paymentChartInstance) {
    paymentChartInstance.destroy();
  }

  paymentChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["كاش (نقدي)", "بطاقات (POS)", "كليك (CliQ)", "تطبيقات التوصيل"],
      datasets: [{
        data: dataValues,
        backgroundColor: ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b"],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      cutout: "70%"
    }
  });

  // Render Legend
  const legendEl = document.getElementById("paymentLegend");
  legendEl.innerHTML = `
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span><span>كاش: ${cash.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span><span>بطاقات: ${card.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span><span>كليك: ${cliq.toFixed(2)}</span></div>
    <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span><span>توصيل: ${delivery.toFixed(2)}</span></div>
  `;
}

// 5. Render Audit Alerts
function renderAuditAlerts(flags) {
  const container = document.getElementById("auditAlertsContainer");
  if (!flags || flags.length === 0) {
    container.innerHTML = `<p class="text-xs text-slate-400 text-center py-8">✅ لا توجد تنبيهات محاسبية حالياً. جميع العمليات متطابقة وسليمة.</p>`;
    return;
  }

  container.innerHTML = flags.map(f => {
    const isCrit = f.severity === "CRITICAL";
    const bgClass = isCrit ? "bg-rose-950/40 border-rose-500/30 text-rose-300" : "bg-amber-950/40 border-amber-500/30 text-amber-300";
    const icon = isCrit ? "alert-circle" : "alert-triangle";

    return `
      <div class="border ${bgClass} p-3 rounded-xl text-xs flex items-start gap-2.5">
        <i data-lucide="${icon}" class="w-4 h-4 flex-shrink-0 mt-0.5"></i>
        <div class="flex-1">
          <div class="font-semibold mb-0.5">[${f.severity}] ${f.flag_type}</div>
          <div class="text-slate-300 leading-relaxed">${f.message}</div>
        </div>
      </div>
    `;
  }).join("");

  if (window.lucide) lucide.createIcons();
}

// 6. Render Jordan Tax Widget
function renderTaxWidget(kpis) {
  const output = Number(kpis.total_tax_collected || 0);
  const input = Number(kpis.total_expenses * 0.16 * 0.8 || 0); // تقدير ضريبة المدخلات المقبولة
  const netTax = Math.max(0, output - input);

  document.getElementById("taxOutput").textContent = `${output.toFixed(3)} د.أ`;
  document.getElementById("taxInput").textContent = `${input.toFixed(3)} د.أ`;
  document.getElementById("taxNet").textContent = `${netTax.toFixed(3)} د.أ`;
}

// 7. Setup Upload Form (Drag & Drop + Quick text)
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

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("border-emerald-500");
  });
  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-emerald-500");
  });
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
      alert("يرجى اختيار صورة فاتورة أو كتابة ملاحظة/كشف سريع.");
      return;
    }

    const formData = new FormData();
    if (file) formData.append("file", file);
    if (notes) formData.append("text_notes", notes);

    // UI Loading state
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span>جاري المعالجة بالذكاء الاصطناعي...</span>`;
    feedback.className = "mt-4 p-4 rounded-xl text-xs bg-slate-900 border border-slate-700 text-slate-300 block";
    feedback.textContent = "⏳ جاري قراءة وتدقيق أرقام المستند واستخراج الحسابات...";

    try {
      const res = await fetch("/api/v1/documents/upload", {
        method: "POST",
        body: formData
      });

      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.detail || "فشل معالجة المستند");
      }

      feedback.className = "mt-4 p-4 rounded-xl text-xs bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 block";
      feedback.innerHTML = `
        <div class="font-bold text-sm mb-1">✅ ${result.message}</div>
        <div>نوع العملية: <strong>${result.extracted_summary.type}</strong> | القيمة: <strong>${Number(result.extracted_summary.total_amount).toFixed(3)} د.أ</strong></div>
        <div class="mt-1">حالة الاعتماد: <span class="bg-emerald-500/20 px-2 py-0.5 rounded">${result.validation_status}</span></div>
      `;

      // Reset fields & refresh dashboard
      fileInput.value = "";
      textInput.value = "";
      document.getElementById("selectedFileName").textContent = "يدعم JPG, PNG, PDF حتى 10MB";
      document.getElementById("selectedFileName").classList.remove("text-emerald-400");

      fetchDashboardData();
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

// 8. Setup WhatsApp Brief Button
function setupBriefButton() {
  const btn = document.getElementById("copyBriefBtn");
  btn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/v1/analytics/daily-brief");
      if (!res.ok) throw new Error("فشل استخراج التقرير");
      const data = await res.json();

      await navigator.clipboard.writeText(data.whatsapp_formatted_text);
      
      const originalText = btn.innerHTML;
      btn.innerHTML = `<span>✅ تم نسخ تقرير الصباح!</span>`;
      setTimeout(() => {
        btn.innerHTML = originalText;
        if (window.lucide) lucide.createIcons();
      }, 2500);
    } catch (err) {
      alert("تعذر نسخ التقرير: " + err.message);
    }
  });
}
