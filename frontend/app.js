let trendChartInstance = null;
let paymentChartInstance = null;
let cachedTransactions = [];
let currentOrgData = null;
let currentOrgBranches = [];
let currentToken = localStorage.getItem("smart_ops_token") || null;
let currentUser = null;
let selectedTenantOrgId = null;
let platformOrgsList = [];
let isInspectingTenant = false;
let inspectingOrgData = null;
let saasOrgsCache = [];
let saasPlatformSummary = null;
let selectedOrgForPasswordModal = null;

const INDUSTRY_LABELS = {
  "restaurant": "مطاعم وكافيهات",
  "retail": "تجزئة وسوبرماركت",
  "pharmacy": "صيدليات ومستلزمات",
  "fashion": "أزياء وملابس",
  "contracting": "مقاولات وإنشاءات",
  "services": "خدمات وصيانة",
  "wholesale": "تجارة جملة وتوزيع",
  "other": "نشاط تجاري عام"
};

function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (currentToken) {
    headers["Authorization"] = `Bearer ${currentToken}`;
  }
  return headers;
}

async function authFetch(url, options = {}) {
  const opts = { ...options };
  opts.headers = getAuthHeaders(opts.headers || {});

  // Append organization_id if Super Admin selected a tenant
  if (currentUser && currentUser.role === "SUPER_ADMIN" && selectedTenantOrgId) {
    const sep = url.includes("?") ? "&" : "?";
    if (!url.includes("organization_id=") && !url.includes("/api/v1/auth") && !url.includes("/api/v1/admin")) {
      url = `${url}${sep}organization_id=${encodeURIComponent(selectedTenantOrgId)}`;
    }
  }

  const res = await fetch(url, opts);
  if (res.status === 401) {
    console.warn("Session expired or unauthorized (401). Redirecting to login.");
    currentToken = null;
    currentUser = null;
    localStorage.removeItem("smart_ops_token");
    openLoginModal();
    throw new Error("انتهت جلسة العمل، يرجى تسجيل الدخول مجدداً");
  }
  return res;
}

function openLoginModal() {
  const modal = document.getElementById("loginModal");
  if (modal) {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    if (window.lucide) lucide.createIcons();
  }
}

function closeLoginModal() {
  const modal = document.getElementById("loginModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
}

window.fillDemoLogin = (username, password) => {
  const u = document.getElementById("loginUsernameInput");
  const p = document.getElementById("loginPasswordInput");
  if (u) u.value = username;
  if (p) p.value = password;
  const btn = document.getElementById("submitLoginBtn");
  if (btn) btn.click();
};

let currentForgotResetToken = null;

function openForgotPasswordModal() {
  closeLoginModal();
  const modal = document.getElementById("forgotPasswordModal");
  if (modal) {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    const form1 = document.getElementById("forgotPasswordForm");
    const form2 = document.getElementById("forgotResetPassForm");
    const alert1 = document.getElementById("forgotAlert");
    const alert2 = document.getElementById("forgotResetAlert");
    const input = document.getElementById("forgotIdentifierInput");
    if (form1) form1.reset();
    if (form2) {
      form2.reset();
      form2.classList.add("hidden");
    }
    if (alert1) {
      alert1.className = "hidden p-3 rounded-xl text-xs text-right";
      alert1.textContent = "";
    }
    if (alert2) {
      alert2.className = "hidden p-3 rounded-xl text-xs text-right";
      alert2.textContent = "";
    }
    if (input) {
      const loginU = document.getElementById("loginUsernameInput");
      if (loginU && loginU.value) {
        input.value = loginU.value.trim();
      }
      setTimeout(() => input.focus(), 50);
    }
    if (window.lucide) lucide.createIcons();
  }
}

function closeForgotPasswordModal() {
  const modal = document.getElementById("forgotPasswordModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
}

function setupForgotPasswordEvents() {
  const openBtn = document.getElementById("openForgotPassBtn");
  if (openBtn) {
    openBtn.addEventListener("click", openForgotPasswordModal);
  }

  const closeBtn = document.getElementById("closeForgotPassModalBtn");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      closeForgotPasswordModal();
      openLoginModal();
    });
  }

  const backBtn = document.getElementById("backToLoginBtn");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      closeForgotPasswordModal();
      openLoginModal();
    });
  }

  const forgotModal = document.getElementById("forgotPasswordModal");
  if (forgotModal) {
    forgotModal.addEventListener("click", (e) => {
      if (e.target === forgotModal) {
        closeForgotPasswordModal();
        openLoginModal();
      }
    });
  }

  const forgotForm = document.getElementById("forgotPasswordForm");
  if (forgotForm) {
    forgotForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("forgotIdentifierInput");
      const alertBox = document.getElementById("forgotAlert");
      const submitBtn = document.getElementById("submitForgotBtn");
      const resetForm = document.getElementById("forgotResetPassForm");
      const foundUserEl = document.getElementById("forgotFoundUsername");

      const identifier = input ? input.value.trim() : "";
      if (!identifier) return;

      const origBtn = submitBtn.innerHTML;
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span>جاري التحقق من الحساب...</span>`;

      try {
        const res = await fetch("/api/v1/auth/forgot-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identifier })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "فشل التحقق من الحساب");
        }

        if (data.success) {
          if (alertBox) {
            alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold block text-right";
            alertBox.textContent = `✅ ${data.message}`;
          }
          currentForgotResetToken = data.reset_token;
          if (foundUserEl) {
            foundUserEl.textContent = data.username;
          }
          if (resetForm) {
            resetForm.classList.remove("hidden");
            const newPassInput = document.getElementById("forgotNewPassInput");
            if (newPassInput) newPassInput.focus();
          }
        } else {
          if (alertBox) {
            alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold block text-right";
            alertBox.textContent = `⚠️ ${data.message}`;
          }
          if (resetForm) resetForm.classList.add("hidden");
        }
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold block text-right";
          alertBox.textContent = `❌ ${err.message}`;
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origBtn;
        if (window.lucide) lucide.createIcons();
      }
    });
  }

  const resetPassForm = document.getElementById("forgotResetPassForm");
  if (resetPassForm) {
    resetPassForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const p1 = document.getElementById("forgotNewPassInput").value;
      const p2 = document.getElementById("forgotConfirmPassInput").value;
      const alertBox = document.getElementById("forgotResetAlert");
      const submitBtn = document.getElementById("submitForgotResetBtn");

      if (p1 !== p2) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold block text-right";
          alertBox.textContent = "❌ كلمتا المرور غير متطابقتين!";
        }
        return;
      }

      if (p1.length < 6) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold block text-right";
          alertBox.textContent = "❌ يجب أن تتكون كلمة المرور من 6 خانات على الأقل.";
        }
        return;
      }

      const origBtn = submitBtn.innerHTML;
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span>جاري حفظ كلمة المرور...</span>`;

      try {
        const res = await fetch("/api/v1/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: currentForgotResetToken,
            new_password: p1
          })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "فشل تعيين كلمة المرور");
        }

        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold block text-right";
          alertBox.textContent = `✅ ${data.message}`;
        }

        setTimeout(() => {
          closeForgotPasswordModal();
          openLoginModal();
          const uInput = document.getElementById("loginUsernameInput");
          const pInput = document.getElementById("loginPasswordInput");
          if (uInput && data.username) uInput.value = data.username;
          if (pInput) {
            pInput.value = p1;
            pInput.focus();
          }
        }, 1500);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold block text-right";
          alertBox.textContent = `❌ ${err.message}`;
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origBtn;
        if (window.lucide) lucide.createIcons();
      }
    });
  }
}

function setupAuthSystem() {
  setupForgotPasswordEvents();

  const form = document.getElementById("loginForm");
  if (form) {
    form.addEventListener("submit", handleLoginSubmit);
  }

  const togglePassBtn = document.getElementById("toggleLoginPasswordBtn");
  if (togglePassBtn) {
    togglePassBtn.addEventListener("click", () => {
      const inp = document.getElementById("loginPasswordInput");
      if (inp) {
        inp.type = inp.type === "password" ? "text" : "password";
      }
    });
  }

  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", handleLogout);
  }

  const superAdminOrgSelect = document.getElementById("superAdminOrgSelect");
  if (superAdminOrgSelect) {
    superAdminOrgSelect.addEventListener("change", (e) => {
      selectedTenantOrgId = e.target.value || null;
      fetchAllData();
    });
  }
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const uInput = document.getElementById("loginUsernameInput");
  const pInput = document.getElementById("loginPasswordInput");
  const errAlert = document.getElementById("loginErrorAlert");
  const submitBtn = document.getElementById("submitLoginBtn");

  if (errAlert) {
    errAlert.classList.add("hidden");
    errAlert.textContent = "";
  }

  const originalHtml = submitBtn.innerHTML;
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>جاري التحقق والدخول...</span>`;

  try {
    const payload = {
      username: uInput.value.trim(),
      password: pInput.value.trim()
    };

    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      let errMsg = "اسم المستخدم أو كلمة المرور غير صحيحة";
      try {
        const err = await res.json();
        if (typeof err.detail === "string") {
          errMsg = err.detail;
        } else if (Array.isArray(err.detail) && err.detail.length > 0) {
          errMsg = err.detail.map(d => d.msg || JSON.stringify(d)).join(" - ");
        } else if (err.detail && typeof err.detail === "object") {
          errMsg = JSON.stringify(err.detail);
        }
      } catch (_) {}
      throw new Error(errMsg);
    }

    const data = await res.json();
    currentToken = data.access_token;
    localStorage.setItem("smart_ops_token", currentToken);

    closeLoginModal();
    await initAuthenticatedUser();
  } catch (err) {
    if (errAlert) {
      errAlert.innerHTML = `
        <div class="space-y-1">
          <div>${err.message}</div>
          <div class="text-[11px] text-slate-300">نسيت بيانات الدخول؟ اضغط على <strong>"نسيت كلمة المرور أو الإيميل؟"</strong> بالأسفل لاستعادة حسابك.</div>
        </div>
      `;
      errAlert.classList.remove("hidden");
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = originalHtml;
    if (window.lucide) lucide.createIcons();
  }
}

function handleLogout() {
  currentToken = null;
  currentUser = null;
  selectedTenantOrgId = null;
  isInspectingTenant = false;
  inspectingOrgData = null;
  localStorage.removeItem("smart_ops_token");
  openLoginModal();
}

async function initAuthenticatedUser() {
  if (!currentToken) {
    openLoginModal();
    return false;
  }
  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { "Authorization": `Bearer ${currentToken}` }
    });
    if (!res.ok) {
      throw new Error("Invalid token");
    }
    const data = await res.json();
    currentUser = data.user;
    if (data.organization) {
      currentOrgData = data.organization;
    }

    renderAppView();

    if (currentUser.role === "SUPER_ADMIN" && !isInspectingTenant) {
      await loadSuperAdminConsoleData();
    } else {
      await fetchAllData();
    }
    return true;
  } catch (err) {
    console.warn("initAuthenticatedUser failed:", err);
    currentToken = null;
    currentUser = null;
    localStorage.removeItem("smart_ops_token");
    openLoginModal();
    return false;
  }
}

function renderAppView() {
  const superAdminDashboard = document.getElementById("superAdminDashboardView");
  const tenantDashboard = document.getElementById("tenantDashboardView");
  const inspectionBanner = document.getElementById("tenantInspectionBanner");
  const tenantHeaderActions = document.getElementById("tenantHeaderActions");
  const superAdminHeaderActions = document.getElementById("superAdminHeaderActions");
  const currentOrgBadge = document.getElementById("currentOrgBadge");
  const headerPlatformSubtitle = document.getElementById("headerPlatformSubtitle");
  const headerExitInspectionBtn = document.getElementById("headerExitInspectionBtn");
  const headerMainTitle = document.getElementById("headerMainTitle");
  const headerTitleBadge = document.getElementById("headerTitleBadge");

  if (currentUser && currentUser.role === "SUPER_ADMIN") {
    if (isInspectingTenant) {
      // Viewing as tenant store
      if (superAdminDashboard) superAdminDashboard.classList.add("hidden");
      if (tenantDashboard) tenantDashboard.classList.remove("hidden");
      if (inspectionBanner) inspectionBanner.classList.remove("hidden");
      if (tenantHeaderActions) tenantHeaderActions.classList.remove("hidden");
      if (superAdminHeaderActions) superAdminHeaderActions.classList.add("hidden");
      if (currentOrgBadge) currentOrgBadge.classList.remove("hidden");
      if (headerPlatformSubtitle) headerPlatformSubtitle.classList.add("hidden");
      if (headerExitInspectionBtn) {
        headerExitInspectionBtn.classList.remove("hidden");
        headerExitInspectionBtn.classList.add("inline-flex");
      }

      const orgName = inspectingOrgData ? inspectingOrgData.name : (currentOrgData ? currentOrgData.name : "المنشأة");
      const inspName = document.getElementById("inspectingOrgName");
      if (inspName) inspName.textContent = orgName;

      if (headerMainTitle) headerMainTitle.textContent = "المساعد المالي والتنفيذي الذكي";
      if (headerTitleBadge) {
        headerTitleBadge.textContent = "وضع المعاينة";
        headerTitleBadge.className = "text-[10px] sm:text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded-full whitespace-nowrap";
      }
    } else {
      // Platform Owner SaaS Command Center
      if (superAdminDashboard) superAdminDashboard.classList.remove("hidden");
      if (tenantDashboard) tenantDashboard.classList.add("hidden");
      if (inspectionBanner) inspectionBanner.classList.add("hidden");
      if (tenantHeaderActions) tenantHeaderActions.classList.add("hidden");
      if (superAdminHeaderActions) {
        superAdminHeaderActions.classList.remove("hidden");
        superAdminHeaderActions.classList.add("flex");
      }
      if (currentOrgBadge) currentOrgBadge.classList.add("hidden");
      if (headerPlatformSubtitle) {
        headerPlatformSubtitle.classList.remove("hidden");
        headerPlatformSubtitle.classList.add("inline-flex");
      }
      if (headerExitInspectionBtn) {
        headerExitInspectionBtn.classList.add("hidden");
        headerExitInspectionBtn.classList.remove("inline-flex");
      }

      if (headerMainTitle) headerMainTitle.textContent = "لوحة قيادة المنصة المركزية";
      if (headerTitleBadge) {
        headerTitleBadge.textContent = "SaaS Super Admin";
        headerTitleBadge.className = "text-[10px] sm:text-xs bg-purple-500/20 text-purple-400 border border-purple-500/30 px-2 py-0.5 rounded-full whitespace-nowrap";
      }
    }
  } else {
    // Normal tenant store users
    if (superAdminDashboard) superAdminDashboard.classList.add("hidden");
    if (tenantDashboard) tenantDashboard.classList.remove("hidden");
    if (inspectionBanner) inspectionBanner.classList.add("hidden");
    if (tenantHeaderActions) tenantHeaderActions.classList.remove("hidden");
    if (superAdminHeaderActions) superAdminHeaderActions.classList.add("hidden");
    if (currentOrgBadge) currentOrgBadge.classList.remove("hidden");
    if (headerPlatformSubtitle) headerPlatformSubtitle.classList.add("hidden");
    if (headerExitInspectionBtn) {
      headerExitInspectionBtn.classList.add("hidden");
      headerExitInspectionBtn.classList.remove("inline-flex");
    }

    if (headerMainTitle) headerMainTitle.textContent = "المساعد المالي والتنفيذي الذكي";
    if (headerTitleBadge) {
      headerTitleBadge.textContent = "بيانات حقيقية 100%";
      headerTitleBadge.className = "text-[10px] sm:text-xs bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full whitespace-nowrap";
    }
  }

  updateHeaderUserUI();
  if (window.lucide) lucide.createIcons();
}

function updateHeaderUserUI() {
  if (!currentUser) return;

  const nameLabel = document.getElementById("headerUserName");
  if (nameLabel) {
    nameLabel.textContent = currentUser.full_name || currentUser.username;
  }

  const roleBadge = document.getElementById("headerUserRoleBadge");
  if (roleBadge) {
    const roleMap = {
      "SUPER_ADMIN": { label: "👑 مالك المنصة", class: "bg-purple-500/20 text-purple-300 border-purple-500/30" },
      "ORG_ADMIN": { label: "🏢 مدير المنشأة", class: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
      "ACCOUNTANT": { label: "📊 محاسب قانوني", class: "bg-sky-500/20 text-sky-300 border-sky-500/30" },
      "CASHIER": { label: "🛒 كاشير فروع", class: "bg-amber-500/20 text-amber-300 border-amber-500/30" }
    };
    const meta = roleMap[currentUser.role] || { label: currentUser.role, class: "bg-slate-700 text-slate-300 border-slate-600" };
    roleBadge.textContent = meta.label;
    roleBadge.className = `px-1.5 py-0.2 rounded text-[10px] font-bold border ${meta.class}`;
  }

  // RBAC UI visibility
  const taxBtn = document.getElementById("openTaxReportBtn");
  const resetBtn = document.getElementById("resetDataBtn");

  if (currentUser.role === "CASHIER") {
    if (taxBtn) taxBtn.classList.add("hidden");
    if (resetBtn) resetBtn.classList.add("hidden");
  } else {
    if (taxBtn) taxBtn.classList.remove("hidden");
    if (resetBtn) {
      if (currentUser.role === "SUPER_ADMIN" || currentUser.role === "ORG_ADMIN") {
        resetBtn.classList.remove("hidden");
      } else {
        resetBtn.classList.add("hidden");
      }
    }
  }

  if (window.lucide) lucide.createIcons();
}

async function loadPlatformOrganizations() {
  try {
    const res = await authFetch("/api/v1/admin/organizations");
    if (!res.ok) return;
    platformOrgsList = await res.json();

    const select = document.getElementById("superAdminOrgSelect");
    if (select) {
      select.innerHTML = `<option value="">🏢 كافة المنشآت (تلقائي)</option>` +
        platformOrgsList.map(o => `<option value="${o.id}" ${o.id === selectedTenantOrgId ? 'selected' : ''}>${o.name} (${o.tax_number || 'بدون ضريبي'})</option>`).join("");
    }

    const userOrgSelect = document.getElementById("newUserOrgSelect");
    if (userOrgSelect) {
      userOrgSelect.innerHTML = `<option value="">بدون منشأة (لمالك المنصة فقط)</option>` +
        platformOrgsList.map(o => `<option value="${o.id}">${o.name}</option>`).join("");
    }
  } catch (err) {
    console.error("loadPlatformOrganizations error:", err);
  }
}


// Initial Load
document.addEventListener("DOMContentLoaded", async () => {
  setupAuthSystem();
  setupSuperAdminConsole();
  setupSuperAdminModal();
  setupOrgSettingsModal();
  setupTransactionFilters();
  setupUploadForm();
  setupBriefButton();
  setupTaxModal();
  setupReviewModal();
  setupBatchModal();
  setupResetButton();
  setupJoFotaraModal();
  checkPublicResetPasswordParam();

  const refreshBtn = document.getElementById("refreshBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => fetchAllData());
  }
  const refreshBtnMobile = document.getElementById("refreshBtnMobile");
  if (refreshBtnMobile) {
    refreshBtnMobile.addEventListener("click", () => fetchAllData());
  }

  // Initialize Auth
  await initAuthenticatedUser();
});

async function fetchAllData() {
  await Promise.all([
    fetchOrgProfile(),
    fetchDashboardData(),
    fetchTaxData(),
    fetchRecentTransactions()
  ]);
}

// 1. Fetch dashboard metrics
async function fetchDashboardData() {
  try {
    const res = await authFetch("/api/v1/analytics/dashboard-summary?days=30");
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
    const sumRes = await authFetch("/api/v1/tax/summary?days=30");
    if (sumRes.ok) {
      const sumData = await sumRes.json();
      renderTaxPanel(sumData.tax_position);
    }

    const riskRes = await authFetch("/api/v1/tax/risk-invoices");
    if (riskRes.ok) {
      const riskData = await riskRes.json();
      renderRiskInvoices(riskData);
    }
  } catch (err) {
    console.error("Tax data error:", err);
  }
}

// 3. Fetch Recent Transactions (The Real Audit Log with Filters)
function getFilterQueryParams() {
  const params = new URLSearchParams();
  params.append("limit", "100");

  const searchInput = document.getElementById("filterSearchInput");
  if (searchInput && searchInput.value.trim()) {
    params.append("search", searchInput.value.trim());
  }

  const branchSelect = document.getElementById("filterBranchSelect");
  if (branchSelect && branchSelect.value && branchSelect.value !== "ALL") {
    params.append("branch", branchSelect.value);
  }

  const typeSelect = document.getElementById("filterTypeSelect");
  if (typeSelect && typeSelect.value && typeSelect.value !== "ALL") {
    params.append("tx_type", typeSelect.value);
  }

  const statusSelect = document.getElementById("filterStatusSelect");
  if (statusSelect && statusSelect.value && statusSelect.value !== "ALL") {
    params.append("status", statusSelect.value);
  }

  const daysSelect = document.getElementById("filterDaysSelect");
  if (daysSelect && daysSelect.value && daysSelect.value !== "ALL") {
    params.append("days", daysSelect.value);
  }

  return params.toString();
}

async function fetchRecentTransactions() {
  try {
    const qs = getFilterQueryParams();
    const res = await authFetch(`/api/v1/analytics/recent-transactions?${qs}`);
    if (!res.ok) throw new Error("فشل جلب سجل العمليات");
    const txs = await res.json();
    cachedTransactions = txs;

    const badge = document.getElementById("txCountBadge");
    if (badge) badge.textContent = `${txs.length} عمليات مسجلة`;

    const tbody = document.getElementById("transactionsTableBody");
    if (!txs || txs.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-8 text-slate-400">
            لا توجد أي عمليات تطابق معايير البحث والفلترة المحددة.
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

      let statusHtml = `<div class="${statusBadgeClass} flex items-center gap-1">`;
      if (isApproved) {
        statusHtml += `<span>✅ معتمد ومطابق</span>`;
      } else {
        statusHtml += `<span>⚠️ يحتاج مراجعة</span>`;
      }
      statusHtml += `</div>`;

      if (!isApproved && t.flags && t.flags.length > 0) {
        statusHtml += `
          <button onclick="openReviewModal('${t.id}')" 
                  class="text-[11px] text-amber-300 hover:text-amber-200 underline mt-1 text-right block max-w-[240px] truncate" 
                  title="${t.flags.join(' | ')} (اضغط لمراجعة الفارق وتعديل البيانات)">
            ⚠️ ${t.flags[0]}
          </button>
        `;
      }

      let actionHtml = '';
      const isCashier = Boolean(currentUser && currentUser.role === 'CASHIER');
      if (!isApproved) {
        actionHtml = `
          <div class="flex items-center justify-center gap-1.5 flex-nowrap">
            <button onclick="window.openJoFotaraModal('${t.id}')"
                    title="فحص رمز الاستجابة السريعة وحزمة الفوترة الإلكترونية JoFotara"
                    class="p-1.5 rounded-lg bg-sky-950/60 hover:bg-sky-900 text-sky-400 border border-sky-500/30 hover:border-sky-400 transition cursor-pointer active:scale-95">
              <i data-lucide="qr-code" class="w-3.5 h-3.5 pointer-events-none"></i>
            </button>
            ${!isCashier ? `
            <button onclick="window.openReviewModal('${t.id}')" 
                    title="مراجعة وتعديل المبالغ وإدخال البيانات الناقصة"
                    class="bg-amber-600/20 hover:bg-amber-600 text-amber-300 hover:text-white border border-amber-500/40 hover:border-amber-500 px-2.5 py-1 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1 shadow-sm active:scale-95 cursor-pointer whitespace-nowrap">
              <i data-lucide="edit-3" class="w-3.5 h-3.5 pointer-events-none"></i>
              <span class="pointer-events-none">مراجعة وتعديل</span>
            </button>
            <button onclick="approveTransaction('${t.id}')" 
                    id="approve-btn-${t.id}"
                    title="اعتماد وتأكيد مطابقة العملية كما هي"
                    class="bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white border border-emerald-500/40 hover:border-emerald-500 px-2.5 py-1 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1 shadow-sm active:scale-95 cursor-pointer whitespace-nowrap">
              <i data-lucide="check" class="w-3.5 h-3.5 pointer-events-none"></i>
              <span class="pointer-events-none">اعتماد</span>
            </button>` : ''}
          </div>
        `;
      } else {
        actionHtml = `
          <div class="flex items-center justify-center gap-1.5">
            <span class="inline-flex items-center gap-1 text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 px-2.5 py-1 rounded-full text-[11px] font-medium whitespace-nowrap">
              <i data-lucide="shield-check" class="w-3.5 h-3.5 pointer-events-none"></i>
              <span class="pointer-events-none">معتمد</span>
            </span>
            <button onclick="window.openJoFotaraModal('${t.id}')"
                    title="فحص رمز الاستجابة السريعة وحزمة الفوترة الإلكترونية JoFotara"
                    class="p-1 rounded-lg bg-sky-950/60 hover:bg-sky-900 text-sky-400 border border-sky-500/30 hover:border-sky-400 transition cursor-pointer active:scale-95">
              <i data-lucide="qr-code" class="w-3.5 h-3.5 pointer-events-none"></i>
            </button>
            ${!isCashier ? `
            <button onclick="window.openReviewModal('${t.id}')"
                    title="تعديل بيانات هذه العملية"
                    class="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition cursor-pointer active:scale-95">
              <i data-lucide="edit-2" class="w-3.5 h-3.5 pointer-events-none"></i>
            </button>` : ''}
          </div>
        `;
      }

      return `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="p-2.5 sm:p-3 text-slate-400 font-mono whitespace-nowrap">${t.date}</td>
          <td class="p-2.5 sm:p-3 whitespace-nowrap">
            <span class="border ${typeBadgeClass} px-2 py-0.5 rounded text-[11px] font-semibold">${t.type}</span>
          </td>
          <td class="p-2.5 sm:p-3 font-semibold text-slate-200 whitespace-nowrap">${t.merchant_or_branch}</td>
          <td class="p-2.5 sm:p-3 font-mono font-bold text-white text-xs sm:text-sm whitespace-nowrap">${Number(t.total_amount).toFixed(3)} د.أ</td>
          <td class="p-2.5 sm:p-3 text-slate-300 text-[11px] whitespace-nowrap">
            ${paymentsText.length > 0 ? paymentsText.join(" | ") : "نقد"}
          </td>
          <td class="p-2.5 sm:p-3 font-mono text-slate-400 whitespace-nowrap">${Number(t.tax_amount).toFixed(3)} د.أ</td>
          <td class="p-2.5 sm:p-3">${statusHtml}</td>
          <td class="p-2.5 sm:p-3 text-center whitespace-nowrap">${actionHtml}</td>
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

// 3.1 Open Interactive Review Modal
window.openReviewModal = async function(txId) {
  let t = cachedTransactions.find(x => String(x.id) === String(txId));
  if (!t) {
    try {
      const res = await authFetch(`/api/v1/analytics/recent-transactions`);
      if (res.ok) {
        cachedTransactions = await res.json();
        t = cachedTransactions.find(x => String(x.id) === String(txId));
      }
    } catch (err) {
      console.error("Error fetching transactions for review modal:", err);
    }
  }

  if (!t) {
    alert("تعذر العثور على بيانات العملية في السجل، يرجى إعادة تحميل الصفحة.");
    return;
  }

  const modal = document.getElementById("reviewTxModal");
  if (!modal) return;

  try {
    const editTxIdEl = document.getElementById("editTxId");
    if (editTxIdEl) editTxIdEl.value = t.id;

    const editTxTypeEl = document.getElementById("editTxType");
    if (editTxTypeEl) editTxTypeEl.value = t.raw_type || "EXPENSE";

    const editTxMerchantEl = document.getElementById("editTxMerchant");
    if (editTxMerchantEl) editTxMerchantEl.value = t.merchant_or_branch || "";

    const editTxTotalEl = document.getElementById("editTxTotal");
    if (editTxTotalEl) editTxTotalEl.value = Number(t.total_amount || 0).toFixed(3);

    const editTxSubtotalEl = document.getElementById("editTxSubtotal");
    if (editTxSubtotalEl) editTxSubtotalEl.value = Number(t.subtotal || t.total_amount || 0).toFixed(3);

    const editTxServiceEl = document.getElementById("editTxService");
    if (editTxServiceEl) editTxServiceEl.value = t.service_charge ? Number(t.service_charge).toFixed(3) : "0.000";

    const editTxTaxEl = document.getElementById("editTxTax");
    if (editTxTaxEl) editTxTaxEl.value = Number(t.tax_amount || 0).toFixed(3);

    const editTxTaxIdEl = document.getElementById("editTxTaxId");
    if (editTxTaxIdEl) editTxTaxIdEl.value = t.supplier_tax_id || "";

    const pb = t.payment_breakdown || {};
    const editTxCashEl = document.getElementById("editTxCash");
    if (editTxCashEl) editTxCashEl.value = pb.cash !== undefined ? Number(pb.cash).toFixed(3) : Number(t.total_amount || 0).toFixed(3);

    const editTxCardEl = document.getElementById("editTxCard");
    if (editTxCardEl) editTxCardEl.value = pb.card !== undefined ? Number(pb.card).toFixed(3) : "0.000";

    const editTxCliqEl = document.getElementById("editTxCliq");
    if (editTxCliqEl) editTxCliqEl.value = pb.cliq !== undefined ? Number(pb.cliq).toFixed(3) : "0.000";

    const editTxDeliveryEl = document.getElementById("editTxDelivery");
    if (editTxDeliveryEl) editTxDeliveryEl.value = pb.delivery_apps !== undefined ? Number(pb.delivery_apps).toFixed(3) : "0.000";

    const editTxNotesEl = document.getElementById("editTxNotes");
    if (editTxNotesEl) editTxNotesEl.value = t.notes || "";

    // Populate Flags list
    const flagsList = document.getElementById("reviewFlagsList");
    if (flagsList) {
      if (t.flags && t.flags.length > 0) {
        flagsList.innerHTML = t.flags.map(f => `<div>• ${f}</div>`).join("");
      } else {
        flagsList.innerHTML = `<div>• العملية معتمدة أو لا توجد فروقات تدقيقية غير محلولة. يمكنك تعديل الحقول لتصحيح أو إعادة تصنيف المبالغ.</div>`;
      }
    }
    const alertBox = document.getElementById("reviewAlertBox");
    if (alertBox) alertBox.classList.remove("hidden");

    modal.classList.remove("hidden");
    modal.classList.add("flex");
  } catch (domErr) {
    console.error("Error populating review modal fields:", domErr);
  } finally {
    if (window.lucide) lucide.createIcons();
  }
};

window.closeReviewModal = function() {
  const modal = document.getElementById("reviewTxModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
};

// 3.2 Setup Review Modal Event Listeners
function setupReviewModal() {
  const modal = document.getElementById("reviewTxModal");
  const closeBtn1 = document.getElementById("closeReviewModalBtn");
  const closeBtn2 = document.getElementById("closeReviewModalBtn2");
  const form = document.getElementById("reviewTxForm");

  if (closeBtn1) closeBtn1.addEventListener("click", closeReviewModal);
  if (closeBtn2) closeBtn2.addEventListener("click", closeReviewModal);

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeReviewModal();
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const txId = document.getElementById("editTxId").value;
      if (!txId) return;

      const saveBtn = document.getElementById("saveReviewBtn");
      saveBtn.disabled = true;
      const originalText = saveBtn.innerHTML;
      saveBtn.innerHTML = `<span>⏳ جاري حفظ التعديلات والاعتماد...</span>`;

      const payload = {
        transaction_type: document.getElementById("editTxType").value,
        merchant_or_supplier_name: document.getElementById("editTxMerchant").value.trim(),
        total_amount: parseFloat(document.getElementById("editTxTotal").value) || 0,
        subtotal: parseFloat(document.getElementById("editTxSubtotal").value) || 0,
        service_charge: parseFloat(document.getElementById("editTxService").value) || 0,
        tax_amount: parseFloat(document.getElementById("editTxTax").value) || 0,
        supplier_tax_id: document.getElementById("editTxTaxId").value.trim(),
        payment_breakdown: {
          cash: parseFloat(document.getElementById("editTxCash").value) || 0,
          card: parseFloat(document.getElementById("editTxCard").value) || 0,
          cliq: parseFloat(document.getElementById("editTxCliq").value) || 0,
          delivery_apps: parseFloat(document.getElementById("editTxDelivery").value) || 0
        },
        notes: document.getElementById("editTxNotes").value.trim(),
        approve: true
      };

      try {
        const res = await authFetch(`/api/v1/analytics/transactions/${txId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "فشل حفظ التعديلات");

        closeReviewModal();
        await fetchAllData();
        showToast(data.message || "تم حفظ التعديلات واعتماد وتحديث الحسابات بنجاح!", "success");
      } catch (err) {
        alert("خطأ أثناء حفظ العملية: " + err.message);
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalText;
        if (window.lucide) lucide.createIcons();
      }
    });
  }
}

// ----------------------------------------------------
// JoFotara QR & e-Invoice Inspector Modal Logic
// ----------------------------------------------------
let currentJoFotaraTxId = null;
let currentJoFotaraPayload = null;
let currentJoFotaraQrData = null;
let currentJoFotaraMode = "readable"; // 'readable' or 'tlv'

window.closeJoFotaraModal = function() {
  const modal = document.getElementById("jofotaraModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
};

window.switchJoFotaraMode = function(mode) {
  currentJoFotaraMode = mode;
  const tabReadable = document.getElementById("tabQrReadable");
  const tabTlv = document.getElementById("tabQrTlv");
  const qrImg = document.getElementById("jofotaraQrImg");
  const desc = document.getElementById("jofotaraModeDesc");
  const downloadBtnText = document.getElementById("downloadQrBtnText");
  const readableSec = document.getElementById("readableTextSection");
  const tlvSec = document.getElementById("tlvSection");

  if (mode === "readable") {
    if (tabReadable) {
      tabReadable.className = "flex-1 py-2 px-3 rounded-lg font-bold transition flex items-center justify-center gap-1.5 bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 cursor-pointer";
    }
    if (tabTlv) {
      tabTlv.className = "flex-1 py-2 px-3 rounded-lg font-medium text-slate-400 hover:text-slate-200 transition flex items-center justify-center gap-1.5 cursor-pointer";
    }
    if (qrImg && currentJoFotaraQrData) {
      qrImg.src = currentJoFotaraQrData.readable_qr_data_uri || currentJoFotaraQrData.qr_data_uri;
    }
    if (desc) {
      desc.textContent = "مسح هذا الرمز بكاميرا الهاتف العادية يظهر بيانات الفاتورة بنص عربي مقروء ومباشر";
      desc.className = "text-[10px] text-emerald-400/90 leading-tight";
    }
    if (downloadBtnText) downloadBtnText.textContent = "تنزيل رمز QR المقروء (PNG)";
    if (readableSec) readableSec.classList.remove("hidden");
    if (tlvSec) tlvSec.classList.add("hidden");
  } else {
    if (tabTlv) {
      tabTlv.className = "flex-1 py-2 px-3 rounded-lg font-bold transition flex items-center justify-center gap-1.5 bg-sky-600/30 text-sky-300 border border-sky-500/40 cursor-pointer";
    }
    if (tabReadable) {
      tabReadable.className = "flex-1 py-2 px-3 rounded-lg font-medium text-slate-400 hover:text-slate-200 transition flex items-center justify-center gap-1.5 cursor-pointer";
    }
    if (qrImg && currentJoFotaraQrData) {
      qrImg.src = currentJoFotaraQrData.tlv_qr_data_uri || currentJoFotaraQrData.qr_data_uri;
    }
    if (desc) {
      desc.textContent = "رمز TLV المشفر المعتمد رسمياً للربط والتدقيق لدى دائرة ضريبة الدخل والمبيعات ISTD";
      desc.className = "text-[10px] text-sky-400/90 leading-tight";
    }
    if (downloadBtnText) downloadBtnText.textContent = "تنزيل رمز QR المشفر TLV (PNG)";
    if (readableSec) readableSec.classList.add("hidden");
    if (tlvSec) tlvSec.classList.remove("hidden");
  }
  if (window.lucide) lucide.createIcons();
};

function setupJoFotaraModal() {
  const modal = document.getElementById("jofotaraModal");
  const closeBtn1 = document.getElementById("closeJoFotaraModalBtn");
  const closeBtn2 = document.getElementById("closeJoFotaraModalBtn2");
  const downloadBtn = document.getElementById("downloadJoFotaraQrBtn");
  const toggleBtn = document.getElementById("togglePayloadBtn");
  const copyBtn = document.getElementById("copyPayloadBtn");
  const copyReadableBtn = document.getElementById("copyReadableTextBtn");
  const tabReadable = document.getElementById("tabQrReadable");
  const tabTlv = document.getElementById("tabQrTlv");

  if (closeBtn1) closeBtn1.addEventListener("click", window.closeJoFotaraModal);
  if (closeBtn2) closeBtn2.addEventListener("click", window.closeJoFotaraModal);

  if (tabReadable) {
    tabReadable.addEventListener("click", () => window.switchJoFotaraMode("readable"));
  }
  if (tabTlv) {
    tabTlv.addEventListener("click", () => window.switchJoFotaraMode("tlv"));
  }

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) window.closeJoFotaraModal();
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      if (!currentJoFotaraTxId) return;
      window.location.href = `/api/v1/tax/transactions/${currentJoFotaraTxId}/jofotara-qr?format=png&mode=${currentJoFotaraMode}`;
    });
  }

  if (copyReadableBtn) {
    copyReadableBtn.addEventListener("click", () => {
      const text = document.getElementById("readableTextContent")?.textContent;
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        const originalHtml = copyReadableBtn.innerHTML;
        copyReadableBtn.innerHTML = `<span>✅ تم النسخ</span>`;
        setTimeout(() => {
          copyReadableBtn.innerHTML = originalHtml;
        }, 1800);
      });
    });
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const section = document.getElementById("payloadViewerSection");
      const btnText = document.getElementById("togglePayloadBtnText");
      if (section) {
        const isHidden = section.classList.contains("hidden");
        if (isHidden) {
          section.classList.remove("hidden");
          if (btnText) btnText.textContent = "إخفاء حزمة الربط (JSON Payload)";
        } else {
          section.classList.add("hidden");
          if (btnText) btnText.textContent = "عرض حزمة الربط (JSON Payload)";
        }
      }
    });
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      if (!currentJoFotaraPayload) return;
      const text = JSON.stringify(currentJoFotaraPayload, null, 2);
      navigator.clipboard.writeText(text).then(() => {
        const originalHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = `<span>✅ تم النسخ</span>`;
        setTimeout(() => {
          copyBtn.innerHTML = originalHtml;
        }, 1800);
      });
    });
  }
}

window.openJoFotaraModal = async function(txId) {
  currentJoFotaraTxId = txId;
  const modal = document.getElementById("jofotaraModal");
  if (!modal) return;

  const qrImg = document.getElementById("jofotaraQrImg");
  const sellerName = document.getElementById("jofotaraSellerName");
  const taxId = document.getElementById("jofotaraTaxId");
  const timestamp = document.getElementById("jofotaraTimestamp");
  const total = document.getElementById("jofotaraTotal");
  const tax = document.getElementById("jofotaraTax");
  const rawTlv = document.getElementById("jofotaraTlvRaw");
  const jsonCode = document.getElementById("jofotaraJsonCode");
  const badge = document.getElementById("jofotaraComplianceBadge");
  const section = document.getElementById("payloadViewerSection");
  const btnText = document.getElementById("togglePayloadBtnText");
  const readableContent = document.getElementById("readableTextContent");

  if (section) section.classList.add("hidden");
  if (btnText) btnText.textContent = "عرض حزمة الربط (JSON Payload)";

  if (sellerName) sellerName.textContent = "جاري التحميل...";
  if (taxId) taxId.textContent = "...";
  if (timestamp) timestamp.textContent = "...";
  if (total) total.textContent = "...";
  if (tax) tax.textContent = "...";
  if (rawTlv) rawTlv.value = "";
  if (readableContent) readableContent.textContent = "جاري إعداد نص الفاتورة...";
  if (jsonCode) jsonCode.textContent = "جاري تحضير حزمة ISTD القياسية...";

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  if (window.lucide) lucide.createIcons();

  try {
    const [qrRes, payloadRes] = await Promise.all([
      authFetch(`/api/v1/tax/transactions/${txId}/jofotara-qr`),
      authFetch(`/api/v1/tax/transactions/${txId}/jofotara-payload`)
    ]);

    if (!qrRes.ok) throw new Error("تعذر جلب بيانات JoFotara للعملية");
    const qrData = await qrRes.json();
    currentJoFotaraQrData = qrData;
    
    if (payloadRes.ok) {
      currentJoFotaraPayload = await payloadRes.json();
      if (jsonCode) jsonCode.textContent = JSON.stringify(currentJoFotaraPayload, null, 2);
    }

    if (sellerName) sellerName.textContent = qrData.seller_name;
    if (taxId) taxId.textContent = qrData.tax_id || "غير مسجل ضريبياً";
    if (timestamp) timestamp.textContent = qrData.timestamp;
    if (total) total.textContent = `${Number(qrData.total_amount).toFixed(3)} د.أ`;
    if (tax) tax.textContent = `${Number(qrData.tax_amount).toFixed(3)} د.أ`;
    if (rawTlv) rawTlv.value = qrData.tlv_base64;
    if (readableContent) readableContent.textContent = qrData.readable_text || "";

    window.switchJoFotaraMode("readable");

    if (badge) {
      if (qrData.is_compliant) {
        badge.className = "inline-flex items-center gap-1 text-[11px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold";
        badge.innerHTML = `<i data-lucide="check-circle" class="w-3 h-3"></i><span>معتمد ومطابق للمعايير 2025</span>`;
      } else {
        badge.className = "inline-flex items-center gap-1 text-[11px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded-full font-semibold";
        badge.innerHTML = `<i data-lucide="alert-triangle" class="w-3 h-3"></i><span>بيانات ناقصة (رقم ضريبي)</span>`;
      }
    }
  } catch (err) {
    if (sellerName) sellerName.textContent = `خطأ: ${err.message}`;
  } finally {
    if (window.lucide) lucide.createIcons();
  }
};

// 12. Setup Batch PDF Summary Modal & Viewer
function setupBatchModal() {
  const modal = document.getElementById("pdfBatchModal");
  const closeBtn1 = document.getElementById("closeBatchModalBtn");
  const closeBtn2 = document.getElementById("closeBatchModalBtn2");

  const close = () => {
    if (modal) {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }
  };

  if (closeBtn1) closeBtn1.addEventListener("click", close);
  if (closeBtn2) closeBtn2.addEventListener("click", close);
}

function showBatchSummaryModal(batch) {
  const modal = document.getElementById("pdfBatchModal");
  if (!modal || !batch) return;

  const fileNameEl = document.getElementById("batchModalFileName");
  if (fileNameEl) fileNameEl.textContent = batch.file_name || "ملف PDF";

  const invCountEl = document.getElementById("batchSummaryInvoicesCount");
  if (invCountEl) invCountEl.textContent = batch.total_invoices || 0;

  const pagesCountEl = document.getElementById("batchSummaryPagesCount");
  if (pagesCountEl) pagesCountEl.textContent = `من ${batch.total_pages || 0} صفحة`;

  const salesAmountEl = document.getElementById("batchSummarySalesAmount");
  if (salesAmountEl) salesAmountEl.textContent = Number(batch.total_sales_amount || 0).toFixed(3);

  const salesCountEl = document.getElementById("batchSummarySalesCount");
  if (salesCountEl) salesCountEl.textContent = `${batch.sales_count || 0} فاتورة مبيعات`;

  const totalPurchasesAndExpenses = (batch.total_purchases_amount || 0) + (batch.total_expenses_amount || 0);
  const purchasesAmountEl = document.getElementById("batchSummaryPurchasesAmount");
  if (purchasesAmountEl) purchasesAmountEl.textContent = Number(totalPurchasesAndExpenses).toFixed(3);

  const purchasesCountEl = document.getElementById("batchSummaryPurchasesCount");
  if (purchasesCountEl) purchasesCountEl.textContent = `${(batch.purchases_count || 0) + (batch.expenses_count || 0)} فاتورة مشتريات/مصاريف`;

  const netTaxEl = document.getElementById("batchSummaryNetTax");
  if (netTaxEl) netTaxEl.textContent = Number(batch.net_tax_liability || 0).toFixed(3);

  const taxBreakdownEl = document.getElementById("batchSummaryTaxBreakdown");
  if (taxBreakdownEl) taxBreakdownEl.textContent = `مخرجات: ${Number(batch.total_output_tax || 0).toFixed(3)} | مدخلات: ${Number(batch.total_input_tax || 0).toFixed(3)}`;

  const approvedCountEl = document.getElementById("batchApprovedCount");
  if (approvedCountEl) approvedCountEl.textContent = batch.approved_count || 0;

  const reviewCountEl = document.getElementById("batchReviewCount");
  if (reviewCountEl) reviewCountEl.textContent = batch.needs_review_count || 0;

  // Warnings
  const warnContainer = document.getElementById("batchWarningsContainer");
  const warnList = document.getElementById("batchWarningsList");
  if (warnContainer && warnList) {
    if (batch.warnings && batch.warnings.length > 0) {
      warnList.innerHTML = batch.warnings.map(w => `<li>${w}</li>`).join("");
      warnContainer.classList.remove("hidden");
    } else {
      warnContainer.classList.add("hidden");
    }
  }

  // Invoices table
  const tbody = document.getElementById("batchInvoicesTableBody");
  if (tbody) {
    if (!batch.invoices || batch.invoices.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="p-4 text-center text-slate-500">لم يتم استخراج أي فواتير</td></tr>`;
    } else {
      tbody.innerHTML = batch.invoices.map(inv => {
        const isSale = inv.type === "SALE";
        const isVerified = inv.status === "PROCESSED";
        const typeBadge = isSale 
          ? `<span class="bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-[11px] font-semibold">مبيعات</span>`
          : (inv.type === "PURCHASE" 
              ? `<span class="bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded text-[11px] font-semibold">مشتريات مورد</span>`
              : `<span class="bg-rose-500/20 text-rose-400 px-2 py-0.5 rounded text-[11px] font-semibold">مصروف</span>`);

        const statusBadge = isVerified
          ? `<span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded text-[10px]">مطابقة ✅</span>`
          : `<span class="bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded text-[10px]">مراجعة ⚠️</span>`;

        return `
          <tr class="hover:bg-slate-800/40 transition">
            <td class="p-2.5 text-slate-400">صفحة ${inv.page_number}</td>
            <td class="p-2.5 font-bold text-slate-200">${inv.invoice_number || "-"}</td>
            <td class="p-2.5">${typeBadge}</td>
            <td class="p-2.5 text-slate-300">${inv.merchant_or_supplier || "-"}</td>
            <td class="p-2.5 font-bold text-slate-100">${Number(inv.total_amount).toFixed(3)}</td>
            <td class="p-2.5 text-sky-400">${Number(inv.tax_amount).toFixed(3)}</td>
            <td class="p-2.5 text-center">${statusBadge}</td>
          </tr>
        `;
      }).join("");
    }
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  if (window.lucide) lucide.createIcons();
}

// Handler for quick manual approval of reviewed transactions
window.approveTransaction = async function(txId) {
  const btn = document.getElementById(`approve-btn-${txId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block animate-spin text-xs">⏳</span> جاري الاعتماد...`;
  }

  try {
    const res = await authFetch(`/api/v1/analytics/transactions/${txId}/approve`, {
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
      btn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i> <span>اعتماد</span>`;
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
      <td class="p-2 sm:p-2.5 font-mono text-slate-200 whitespace-nowrap">${inv.invoice_number}</td>
      <td class="p-2 sm:p-2.5 text-slate-400 whitespace-nowrap">${inv.date}</td>
      <td class="p-2 sm:p-2.5 text-slate-200 font-medium whitespace-nowrap">${inv.supplier_or_merchant}</td>
      <td class="p-2 sm:p-2.5 font-mono font-bold text-white whitespace-nowrap">${Number(inv.amount).toFixed(3)} د.أ</td>
      <td class="p-2 sm:p-2.5 font-mono text-rose-400 font-semibold whitespace-nowrap">${Number(inv.tax_amount).toFixed(3)} د.أ</td>
      <td class="p-2 sm:p-2.5 text-rose-300">
        <span class="bg-rose-950/60 border border-rose-500/30 px-2 py-0.5 rounded text-[11px] whitespace-nowrap">${inv.risk_reason}</span>
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
      const res = await authFetch("/api/v1/documents/upload", { method: "POST", body: formData });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || "فشل معالجة المستند");

      if (result.is_batch && result.batch_summary) {
        showBatchSummaryModal(result.batch_summary);
        feedback.className = "mt-4 p-4 rounded-xl text-xs bg-purple-950/40 border border-purple-500/30 text-purple-300 block";
        feedback.innerHTML = `
          <div class="font-bold text-sm mb-1">📑 ${result.message}</div>
          <div>تم استخراج <strong>${result.batch_summary.total_invoices}</strong> فاتورة مستقلة | إجمالي المبيعات: <strong>${Number(result.batch_summary.total_sales_amount).toFixed(3)} د.أ</strong> | إجمالي المشتريات: <strong>${Number(result.batch_summary.total_purchases_amount).toFixed(3)} د.أ</strong></div>
          <div class="mt-1">حالة الحزمة: <span class="bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded font-semibold">${result.batch_summary.approved_count} معتمدة</span> | <span class="bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded font-semibold">${result.batch_summary.needs_review_count} بحاجة لمراجعة</span></div>
        `;
      } else {
        feedback.className = "mt-4 p-4 rounded-xl text-xs bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 block";
        feedback.innerHTML = `
          <div class="font-bold text-sm mb-1">✅ ${result.message}</div>
          <div>نوع العملية: <strong>${result.extracted_summary.type}</strong> | القيمة المسجلة: <strong>${Number(result.extracted_summary.total_amount).toFixed(3)} د.أ</strong></div>
          <div class="mt-1">حالة الاعتماد: <span class="bg-emerald-500/20 px-2 py-0.5 rounded font-semibold">${result.validation_status}</span></div>
        `;
      }

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
      const res = await authFetch("/api/v1/analytics/daily-brief");
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
      const res = await authFetch("/api/v1/analytics/reset-data", { method: "POST" });
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
  const periodBtns = document.querySelectorAll(".tax-period-btn");

  let currentTaxPeriod = "all";

  async function fetchAndRenderTaxReport(period = "all") {
    currentTaxPeriod = period;

    // Update active tab styles
    periodBtns.forEach(b => {
      if (b.getAttribute("data-period") === period) {
        b.className = "tax-period-btn px-2.5 py-1 rounded-lg text-xs font-semibold bg-sky-600 text-white transition shadow-sm";
      } else {
        b.className = "tax-period-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition";
      }
    });

    content.innerHTML = `<p class="text-center py-8 text-slate-400">جاري تجميع بيانات الإقرار ومطابقة الفواتير والتحصيلات...</p>`;

    try {
      const url = period === "all" 
        ? "/api/v1/tax/pre-filing-report?all_time=true" 
        : `/api/v1/tax/pre-filing-report?days=${period}`;
      
      const res = await authFetch(url);
      if (!res.ok) throw new Error("فشل جلب تقرير الإقرار");
      const r = await res.json();

      const m = r.metadata;
      const p = r.tax_position;
      const rec = r.payment_reconciliation;

      const otherPayments = (Number(rec.bank_transfer_collected) || 0) + (Number(rec.other_collected) || 0);

      content.innerHTML = `
        <div class="bg-slate-800/80 p-4 rounded-xl border border-slate-700 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div><span class="text-slate-400">اسم المنشأة:</span> <div class="font-bold text-white">${m.organization_name}</div></div>
          <div><span class="text-slate-400">الرقم الضريبي:</span> <div class="font-bold text-sky-400 font-mono">${m.tax_number}</div></div>
          <div><span class="text-slate-400">فترة الإقرار:</span> <div class="font-medium text-amber-300">${m.period || "كافة العمليات"}</div></div>
          <div><span class="text-slate-400">العمليات المشمولة:</span> <div class="font-bold text-white font-mono">${m.transactions_count !== undefined ? m.transactions_count + ' فاتورة' : '—'}</div></div>
          <div><span class="text-slate-400">تاريخ الإعداد:</span> <div class="font-medium text-slate-300">${m.report_generated_date}</div></div>
          <div><span class="text-slate-400">نطاق التواريخ:</span> <div class="font-medium text-slate-300 font-mono text-[11px]">${m.date_range?.from ? `${m.date_range.from} إلى ${m.date_range.to}` : '—'}</div></div>
          <div class="col-span-2"><span class="text-slate-400">درجة الجاهزية:</span> <div class="font-bold ${m.is_audit_ready ? 'text-emerald-400' : 'text-amber-400'}">${m.compliance_score}% (${m.is_audit_ready ? 'جاهز للتقديم' : 'يتطلب مراجعة'})</div></div>
        </div>

        <!-- 1. Sales & Output Tax Breakdown -->
        <div class="space-y-2">
          <h4 class="font-bold text-white text-sm flex items-center justify-between">
            <span>1. ملخص المبيعات وضريبة المخرجات (16% ISTD)</span>
            <span class="text-xs font-normal text-slate-400">النظام الضريبي الأردني (ISTD / JoFotara)</span>
          </h4>
          <table class="w-full text-right border-collapse border border-slate-800 rounded-lg overflow-hidden text-xs">
            <tbody class="divide-y divide-slate-800 text-slate-200">
              <tr class="bg-slate-800/40">
                <td class="p-2 text-slate-300">المبيعات الأساسية (قبل بدل الخدمة والضريبة):</td>
                <td class="p-2 font-mono font-bold">${Number(p.base_sales_subtotal || (p.taxable_sales_subtotal - (p.service_charge_total || 0))).toFixed(3)} د.أ</td>
              </tr>
              ${Number(p.service_charge_total) > 0 ? `
              <tr>
                <td class="p-2 text-slate-300">إجمالي بدل الخدمة الخاضع للضريبة (قطاع المطاعم):</td>
                <td class="p-2 font-mono font-bold text-amber-300">${Number(p.service_charge_total).toFixed(3)} د.أ</td>
              </tr>` : ''}
              <tr class="bg-slate-800/60 font-semibold">
                <td class="p-2 text-slate-200">الوعاء الإجمالي الخاضع لضريبة المبيعات 16%:</td>
                <td class="p-2 font-mono font-bold text-sky-300">${Number(p.taxable_sales_subtotal).toFixed(3)} د.أ</td>
              </tr>
              <tr>
                <td class="p-2 text-slate-300">ضريبة المبيعات العامة المحصلة (Output Tax 16%):</td>
                <td class="p-2 font-mono font-bold text-sky-400">${Number(p.output_tax_collected).toFixed(3)} د.أ</td>
              </tr>
              <tr class="bg-slate-800/40">
                <td class="p-2 text-slate-300">مبيعات معفاة أو بنسبة صفرية (غير خاضعة للضريبة):</td>
                <td class="p-2 font-mono font-bold text-slate-300">${Number(p.exempt_or_zero_sales || 0).toFixed(3)} د.أ</td>
              </tr>
              <tr class="bg-sky-950/70 font-bold border-t-2 border-sky-800">
                <td class="p-2.5 text-sky-200 text-xs">إجمالي المبيعات الشامل للضريبة (مطابق للمقبوضات):</td>
                <td class="p-2.5 font-mono text-sm text-sky-300">${Number(p.gross_sales).toFixed(3)} د.أ</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 2. Purchases & Input Tax Breakdown -->
        <div class="space-y-2">
          <h4 class="font-bold text-white text-sm flex items-center justify-between">
            <span>2. المشتريات والمصروفات وضريبة المدخلات (JoFotara Compliance)</span>
            <span class="text-xs font-normal text-emerald-400">رد وخصم الضريبة قانونياً</span>
          </h4>
          <table class="w-full text-right border-collapse border border-slate-800 rounded-lg overflow-hidden text-xs">
            <tbody class="divide-y divide-slate-800 text-slate-200">
              <tr class="bg-slate-800/40">
                <td class="p-2 text-slate-300">إجمالي المشتريات والمصروفات المسجلة:</td>
                <td class="p-2 font-mono font-bold">${Number(p.gross_expenses_and_purchases || 0).toFixed(3)} د.أ</td>
              </tr>
              <tr>
                <td class="p-2 text-slate-300">مشتريات مؤهلة معززة برقم ضريبي للمورد (JoFotara):</td>
                <td class="p-2 font-mono font-bold text-emerald-400">${Number(p.eligible_purchases_subtotal || 0).toFixed(3)} د.أ</td>
              </tr>
              <tr class="bg-slate-800/40">
                <td class="p-2 text-slate-300">ضريبة المدخلات المقبولة للخصم قانونياً (رد الضريبة):</td>
                <td class="p-2 font-mono font-bold text-emerald-400">(${Number(p.eligible_input_tax || 0).toFixed(3)}) د.أ</td>
              </tr>
              ${Number(p.ineligible_expenses_subtotal) > 0 ? `
              <tr class="bg-rose-950/30 text-rose-300">
                <td class="p-2">نفقات ومصروفات فاقدة للرقم الضريبي (غير مقبولة):</td>
                <td class="p-2 font-mono font-bold">${Number(p.ineligible_expenses_subtotal).toFixed(3)} د.أ</td>
              </tr>` : ''}
            </tbody>
          </table>
          ${Number(p.gross_expenses_and_purchases) === 0 ? `
          <p class="text-[11px] text-slate-400 italic bg-slate-800/30 p-2 rounded-lg border border-slate-800">
            ℹ️ لا توجد فواتير مشتريات أو مصروفات موردين مسجلة في هذه الفترة (كافة العمليات مبيعات زبائن).
          </p>` : ''}
        </div>

        <!-- 3. Net Tax Position & Estimated Income Tax -->
        <div class="space-y-2">
          <h4 class="font-bold text-white text-sm">3. الموقف الضريبي النهائي وصافي الالتزام</h4>
          <table class="w-full text-right border-collapse border border-slate-800 rounded-lg overflow-hidden text-xs">
            <tbody class="divide-y divide-slate-800 text-slate-200">
              <tr class="bg-sky-950/80 font-bold">
                <td class="p-2.5 text-sky-200 text-xs sm:text-sm">صافي ضريبة المبيعات المستحقة للدفع للدائرة (أو رصيد دائن):</td>
                <td class="p-2.5 font-mono text-sm sm:text-base text-sky-300">
                  ${p.net_sales_tax_payable > 0 
                    ? Number(p.net_sales_tax_payable).toFixed(3) + ' د.أ (مستحق للدفع للدائرة)' 
                    : Number(p.tax_credit_carried_forward).toFixed(3) + ' د.أ (رصيد دائن مدور)'}
                </td>
              </tr>
              <tr class="bg-slate-800/50">
                <td class="p-2 text-slate-300">صافي الدخل التقديري للأعمال (الخاضع لضريبة الدخل ISTD):</td>
                <td class="p-2 font-mono font-bold text-amber-300">${Number(p.estimated_taxable_income || 0).toFixed(3)} د.أ</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="font-bold text-white text-sm">2. مطابقة المبيعات مع وسائل التحصيل الفعلية (Reconciliation)</h4>
            <span class="text-xs px-2 py-0.5 rounded-full font-medium ${rec.has_discrepancy ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'}">
              ${rec.has_discrepancy ? `⚠️ فارق: ${Number(rec.variance).toFixed(3)} د.أ` : '✅ مطابقة تامة'}
            </span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 bg-slate-800/40 p-3 rounded-xl border border-slate-800 text-xs">
            <div><span class="text-slate-400">كاش الصندوق:</span> <div class="font-mono font-bold">${Number(rec.cash_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">بطاقات (POS):</span> <div class="font-mono font-bold">${Number(rec.cards_pos_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">كليك (CliQ):</span> <div class="font-mono font-bold text-purple-400">${Number(rec.cliq_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">تطبيقات توصيل:</span> <div class="font-mono font-bold">${Number(rec.delivery_collected).toFixed(3)} د.أ</div></div>
            <div><span class="text-slate-400">تحويل / أخرى:</span> <div class="font-mono font-bold text-slate-300">${otherPayments.toFixed(3)} د.أ</div></div>
          </div>
          <div class="flex justify-between items-center bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800 text-xs text-slate-300">
            <span>إجمالي المقبوضات المطابقة: <strong class="text-white font-mono">${Number(rec.total_payments_reconciled).toFixed(3)} د.أ</strong></span>
            <span>إجمالي المبيعات المصرحة: <strong class="text-white font-mono">${Number(rec.total_sales_reported).toFixed(3)} د.أ</strong></span>
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
  }

  // Setup period tab listeners
  periodBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const p = btn.getAttribute("data-period");
      fetchAndRenderTaxReport(p);
    });
  });

  openBtn.addEventListener("click", () => {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    fetchAndRenderTaxReport(currentTaxPeriod);
  });

  const closeModal = () => {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  };

  closeBtn1.addEventListener("click", closeModal);
  closeBtn2.addEventListener("click", closeModal);

  printBtn.addEventListener("click", async () => {
    const originalContent = printBtn.innerHTML;
    try {
      printBtn.disabled = true;
      printBtn.innerHTML = `
        <svg class="animate-spin h-4 w-4 text-white inline ml-1" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>جاري تنزيل ملف PDF...</span>
      `;

      let pdfUrl = currentTaxPeriod === "all"
        ? "/api/v1/tax/pre-filing-report/pdf?all_time=true"
        : `/api/v1/tax/pre-filing-report/pdf?days=${currentTaxPeriod}`;

      const res = await authFetch(pdfUrl);
      if (!res.ok) throw new Error("فشل تنزيل ملف الـ PDF");
      const blob = await res.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const downloadLink = document.createElement("a");
      downloadLink.href = blobUrl;
      const orgNameSafe = currentOrgData && currentOrgData.name ? currentOrgData.name.replace(/\s+/g, '_') : 'org';
      downloadLink.download = `tax_return_report_${orgNameSafe}.pdf`;
      document.body.appendChild(downloadLink);
      downloadLink.click();
      downloadLink.remove();
      window.URL.revokeObjectURL(blobUrl);
    } catch (err) {
      alert("حدث خطأ أثناء تحميل ملف PDF: " + err.message);
    } finally {
      setTimeout(() => {
        printBtn.disabled = false;
        printBtn.innerHTML = originalContent;
        if (window.lucide) lucide.createIcons();
      }, 1000);
    }
  });
}

// Organization Profile & Branches Management
function renderBranchFilterOptions() {
  const sel = document.getElementById("filterBranchSelect");
  if (!sel) return;
  const currentVal = sel.value;
  sel.innerHTML = `<option value="ALL">🏢 كل الفروع</option>`;
  if (Array.isArray(currentOrgBranches)) {
    currentOrgBranches.forEach(b => {
      sel.innerHTML += `<option value="${b}">${b}</option>`;
    });
  }
  if (currentVal && Array.isArray(currentOrgBranches) && currentOrgBranches.includes(currentVal)) {
    sel.value = currentVal;
  }
}

let filterSearchTimeout = null;
function setupTransactionFilters() {
  const searchInput = document.getElementById("filterSearchInput");
  const branchSelect = document.getElementById("filterBranchSelect");
  const typeSelect = document.getElementById("filterTypeSelect");
  const statusSelect = document.getElementById("filterStatusSelect");
  const daysSelect = document.getElementById("filterDaysSelect");
  const clearBtn = document.getElementById("clearFiltersBtn");
  const exportBtn = document.getElementById("exportCsvBtn");

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(filterSearchTimeout);
      filterSearchTimeout = setTimeout(() => {
        fetchRecentTransactions();
      }, 300);
    });
  }

  [branchSelect, typeSelect, statusSelect, daysSelect].forEach(sel => {
    if (sel) {
      sel.addEventListener("change", () => fetchRecentTransactions());
    }
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      if (branchSelect) branchSelect.value = "ALL";
      if (typeSelect) typeSelect.value = "ALL";
      if (statusSelect) statusSelect.value = "ALL";
      if (daysSelect) daysSelect.value = "ALL";
      fetchRecentTransactions();
    });
  }

  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const qs = getFilterQueryParams();
      window.location.href = `/api/v1/analytics/export/transactions?${qs}`;
    });
  }
}

async function fetchOrgProfile() {
  try {
    const res = await authFetch("/api/v1/analytics/organization-profile");
    if (!res.ok) return;
    const data = await res.json();
    currentOrgData = data;
    currentOrgBranches = Array.isArray(data.branches) ? [...data.branches] : [];

    const nameEl = document.getElementById("headerOrgName");
    if (nameEl) nameEl.textContent = data.name || "المؤسسة التجارية";

    const indEl = document.getElementById("headerOrgIndustry");
    if (indEl) {
      indEl.textContent = INDUSTRY_LABELS[data.industry_type] || data.industry_type || "نشاط تجاري";
    }

    const branchesEl = document.getElementById("branchesCountBadge");
    if (branchesEl) {
      const count = currentOrgBranches.length;
      branchesEl.textContent = count > 0 ? `(${count} فروع)` : "(الفرع الرئيسي)";
    }

    renderBranchFilterOptions();
  } catch (err) {
    console.error("fetchOrgProfile error:", err);
  }
}

function setupOrgSettingsModal() {
  const modal = document.getElementById("orgSettingsModal");
  const openBtn = document.getElementById("openOrgSettingsBtn");
  const badgeBtn = document.getElementById("currentOrgBadge");
  const closeBtn1 = document.getElementById("closeOrgModalBtn");
  const closeBtn2 = document.getElementById("closeOrgModalBtn2");
  const form = document.getElementById("orgSettingsForm");
  const addBranchBtn = document.getElementById("addBranchBtn");
  const newBranchInput = document.getElementById("newBranchInput");
  const chipsContainer = document.getElementById("branchesChipsContainer");
  const alertBox = document.getElementById("orgModalAlert");

  const lockNotice = document.getElementById("orgLockNotice");
  const nameInput = document.getElementById("orgNameInput");
  const industryInput = document.getElementById("orgIndustryInput");
  const taxInput = document.getElementById("orgTaxInput");

  if (!modal) return;

  const renderChips = () => {
    if (!chipsContainer) return;
    if (currentOrgBranches.length === 0) {
      chipsContainer.innerHTML = `<span class="text-slate-500 text-[11px] italic">لم يتم إضافة فروع منفصلة بعد (سيتم اعتماد الفرع الرئيسي تلقائياً).</span>`;
      return;
    }
    const isSuper = Boolean(currentUser && currentUser.role === "SUPER_ADMIN");
    chipsContainer.innerHTML = currentOrgBranches.map((b, idx) => `
      <span class="inline-flex items-center gap-1.5 bg-indigo-950/80 border border-indigo-500/30 text-indigo-200 px-2.5 py-1 rounded-lg text-xs font-medium">
        <span>${b}</span>
        ${isSuper ? `
        <button type="button" data-index="${idx}" class="remove-branch-btn text-indigo-400 hover:text-rose-400 hover:bg-slate-800 rounded p-0.5 transition cursor-pointer" title="حذف الفرع">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>` : ''}
      </span>
    `).join("");

    if (isSuper) {
      chipsContainer.querySelectorAll(".remove-branch-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
          const idx = parseInt(btn.getAttribute("data-index"), 10);
          currentOrgBranches.splice(idx, 1);
          renderChips();
        });
      });
    }
  };

  const addBranch = () => {
    const isSuper = Boolean(currentUser && currentUser.role === "SUPER_ADMIN");
    if (!isSuper) return;
    const val = newBranchInput.value.trim();
    if (!val) return;
    if (!currentOrgBranches.includes(val)) {
      currentOrgBranches.push(val);
      renderChips();
    }
    newBranchInput.value = "";
    newBranchInput.focus();
  };

  if (addBranchBtn) {
    addBranchBtn.addEventListener("click", (e) => {
      e.preventDefault();
      addBranch();
    });
  }

  if (newBranchInput) {
    newBranchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addBranch();
      }
    });
  }

  const openModal = () => {
    if (alertBox) {
      alertBox.className = "hidden rounded-xl p-3 text-xs";
      alertBox.textContent = "";
    }
    if (currentOrgData) {
      document.getElementById("orgNameInput").value = currentOrgData.name || "";
      document.getElementById("orgIndustryInput").value = currentOrgData.industry_type || "restaurant";
      document.getElementById("orgTaxInput").value = currentOrgData.tax_number || "";
      currentOrgBranches = Array.isArray(currentOrgData.branches) ? [...currentOrgData.branches] : [];

      const autoToggle = document.getElementById("autoBriefToggle");
      if (autoToggle) autoToggle.checked = currentOrgData.auto_daily_brief_enabled !== false;
      const briefTime = document.getElementById("dailyBriefTimeInput");
      if (briefTime) briefTime.value = currentOrgData.daily_brief_time || "08:30";
    }

    const isSuper = Boolean(currentUser && currentUser.role === "SUPER_ADMIN");
    if (!isSuper) {
      if (lockNotice) lockNotice.classList.remove("hidden");
      if (nameInput) { nameInput.disabled = true; nameInput.classList.add("opacity-60", "cursor-not-allowed"); }
      if (industryInput) { industryInput.disabled = true; industryInput.classList.add("opacity-60", "cursor-not-allowed"); }
      if (taxInput) { taxInput.disabled = true; taxInput.classList.add("opacity-60", "cursor-not-allowed"); }
      if (newBranchInput) { newBranchInput.disabled = true; newBranchInput.placeholder = "إدارة الفروع محصورة بمالك المنصة"; newBranchInput.classList.add("opacity-60", "cursor-not-allowed"); }
      if (addBranchBtn) { addBranchBtn.disabled = true; addBranchBtn.classList.add("opacity-60", "cursor-not-allowed"); }
    } else {
      if (lockNotice) lockNotice.classList.add("hidden");
      if (nameInput) { nameInput.disabled = false; nameInput.classList.remove("opacity-60", "cursor-not-allowed"); }
      if (industryInput) { industryInput.disabled = false; industryInput.classList.remove("opacity-60", "cursor-not-allowed"); }
      if (taxInput) { taxInput.disabled = false; taxInput.classList.remove("opacity-60", "cursor-not-allowed"); }
      if (newBranchInput) { newBranchInput.disabled = false; newBranchInput.placeholder = "اسم الفرع الجديد (مثال: فرع خلدا...)"; newBranchInput.classList.remove("opacity-60", "cursor-not-allowed"); }
      if (addBranchBtn) { addBranchBtn.disabled = false; addBranchBtn.classList.remove("opacity-60", "cursor-not-allowed"); }
    }

    renderChips();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    if (window.lucide) lucide.createIcons();
  };

  const closeModal = () => {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  };

  if (openBtn) openBtn.addEventListener("click", openModal);
  if (badgeBtn) badgeBtn.addEventListener("click", openModal);
  if (closeBtn1) closeBtn1.addEventListener("click", closeModal);
  if (closeBtn2) closeBtn2.addEventListener("click", closeModal);

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saveBtn = document.getElementById("saveOrgBtn");
      const originalHtml = saveBtn.innerHTML;
      saveBtn.disabled = true;
      saveBtn.innerHTML = `<span>جاري حفظ وتطبيق الإعدادات...</span>`;

      try {
        const autoToggle = document.getElementById("autoBriefToggle");
        const briefTime = document.getElementById("dailyBriefTimeInput");
        const isSuper = Boolean(currentUser && currentUser.role === "SUPER_ADMIN");

        let res;
        if (!isSuper) {
          // Non-super admins only update briefing schedule
          const schedulePayload = {
            auto_daily_brief_enabled: autoToggle ? autoToggle.checked : true,
            daily_brief_time: briefTime ? briefTime.value.trim() : "08:30"
          };
          res = await authFetch("/api/v1/analytics/briefing-schedule", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(schedulePayload)
          });
        } else {
          // Super Admin can update all fields
          const fullPayload = {
            name: document.getElementById("orgNameInput").value.trim(),
            industry_type: document.getElementById("orgIndustryInput").value,
            tax_number: document.getElementById("orgTaxInput").value.trim() || null,
            branches: currentOrgBranches,
            auto_daily_brief_enabled: autoToggle ? autoToggle.checked : true,
            daily_brief_time: briefTime ? briefTime.value.trim() : "08:30"
          };
          res = await authFetch("/api/v1/analytics/organization-profile", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fullPayload)
          });
        }

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل حفظ بيانات المنشأة");
        }

        const updated = await res.json();
        currentOrgData = updated;
        if (updated.branches) {
          currentOrgBranches = Array.isArray(updated.branches) ? [...updated.branches] : [];
        }

        // Update header UI
        const nameEl = document.getElementById("headerOrgName");
        if (nameEl && updated.name) nameEl.textContent = updated.name;
        const indEl = document.getElementById("headerOrgIndustry");
        if (indEl && updated.industry_type) indEl.textContent = INDUSTRY_LABELS[updated.industry_type] || updated.industry_type;
        const branchesEl = document.getElementById("branchesCountBadge");
        if (branchesEl) {
          branchesEl.textContent = currentOrgBranches.length > 0 ? `(${currentOrgBranches.length} فروع)` : "(الفرع الرئيسي)";
        }

        renderBranchFilterOptions();

        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 rounded-xl p-3 text-xs flex items-center gap-2";
          alertBox.innerHTML = `<span>✅ تم حفظ الإعدادات بنجاح!</span>`;
        }

        setTimeout(() => {
          closeModal();
          fetchAllData();
        }, 900);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 rounded-xl p-3 text-xs flex items-center gap-2";
          alertBox.innerHTML = `<span>❌ خطأ: ${err.message}</span>`;
        }
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalHtml;
        if (window.lucide) lucide.createIcons();
      }
    });
  }
}

function setupSuperAdminModal() {
  const modal = document.getElementById("superAdminModal");
  const openBtn = document.getElementById("openSuperAdminBtn");
  const closeBtn1 = document.getElementById("closeSuperAdminModalBtn");
  const closeBtn2 = document.getElementById("closeSuperAdminModalBtn2");
  const tabOrgsBtn = document.getElementById("adminTabOrgsBtn");
  const tabUsersBtn = document.getElementById("adminTabUsersBtn");
  const tabOrgsContent = document.getElementById("adminTabOrgsContent");
  const tabUsersContent = document.getElementById("adminTabUsersContent");
  const openNewOrgBtn = document.getElementById("openNewOrgFormBtn");
  const newOrgForm = document.getElementById("newOrgForm");
  const openNewUserBtn = document.getElementById("openNewUserFormBtn");
  const newUserForm = document.getElementById("newUserForm");

  if (!modal) return;

  const openModal = () => {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    loadAdminOrganizationsList();
    loadAdminUsersList();
    if (window.lucide) lucide.createIcons();
  };

  const closeModal = () => {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  };

  if (openBtn) openBtn.addEventListener("click", openModal);
  if (closeBtn1) closeBtn1.addEventListener("click", closeModal);
  if (closeBtn2) closeBtn2.addEventListener("click", closeModal);

  // Tabs
  if (tabOrgsBtn && tabUsersBtn) {
    tabOrgsBtn.addEventListener("click", () => {
      tabOrgsBtn.className = "px-4 py-2 text-purple-400 border-b-2 border-purple-500 transition flex items-center gap-1.5 cursor-pointer";
      tabUsersBtn.className = "px-4 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
      tabOrgsContent.classList.remove("hidden");
      tabUsersContent.classList.add("hidden");
    });

    tabUsersBtn.addEventListener("click", () => {
      tabUsersBtn.className = "px-4 py-2 text-indigo-400 border-b-2 border-indigo-500 transition flex items-center gap-1.5 cursor-pointer";
      tabOrgsBtn.className = "px-4 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
      tabUsersContent.classList.remove("hidden");
      tabOrgsContent.classList.add("hidden");
      loadAdminUsersList();
    });
  }

  // Toggle Add Forms
  if (openNewOrgBtn && newOrgForm) {
    openNewOrgBtn.addEventListener("click", () => {
      newOrgForm.classList.toggle("hidden");
    });
  }
  if (openNewUserBtn && newUserForm) {
    openNewUserBtn.addEventListener("click", () => {
      newUserForm.classList.toggle("hidden");
      loadPlatformOrganizations();
    });
  }

  // Create Org Submit
  if (newOrgForm) {
    newOrgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const payload = {
          name: document.getElementById("newOrgName").value.trim(),
          tax_number: document.getElementById("newOrgTax").value.trim() || null,
          industry_type: document.getElementById("newOrgIndustry").value,
          branches: document.getElementById("newOrgBranches").value.split(",").map(s => s.trim()).filter(Boolean),
          telegram_bot_token: document.getElementById("newOrgBotToken").value.trim() || null,
          admin_username: document.getElementById("newOrgAdminUser").value.trim(),
          admin_password: document.getElementById("newOrgAdminPass").value.trim(),
          admin_full_name: `مدير ${document.getElementById("newOrgName").value.trim()}`
        };

        const res = await authFetch("/api/v1/admin/organizations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تسجيل المنشأة");
        }

        alert("✅ تم تسجيل المنشأة وتخصيص البوت والمستخدم الإداري بنجاح!");
        newOrgForm.reset();
        newOrgForm.classList.add("hidden");
        loadAdminOrganizationsList();
        loadPlatformOrganizations();
      } catch (err) {
        alert(`❌ خطأ: ${err.message}`);
      }
    });
  }

  // Create User Submit
  if (newUserForm) {
    newUserForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const orgIdVal = document.getElementById("newUserOrgSelect").value.trim() || null;
        const payload = {
          username: document.getElementById("newUsername").value.trim(),
          full_name: document.getElementById("newFullName").value.trim(),
          password: document.getElementById("newUserPass").value.trim(),
          role: document.getElementById("newUserRole").value,
          organization_id: orgIdVal
        };

        const res = await authFetch("/api/v1/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل إنشاء المستخدم");
        }

        alert("✅ تم إنشاء المستخدم وتعيين دوره بنجاح!");
        newUserForm.reset();
        newUserForm.classList.add("hidden");
        loadAdminUsersList();
      } catch (err) {
        alert(`❌ خطأ: ${err.message}`);
      }
    });
  }
}

// ==========================================
// Super Admin SaaS Console & Platform Management
// ==========================================

function checkPublicResetPasswordParam() {
  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get("reset_token");
  if (resetToken) {
    const modal = document.getElementById("publicResetPasswordModal");
    const tokenHidden = document.getElementById("publicResetTokenHidden");
    if (modal && tokenHidden) {
      tokenHidden.value = resetToken;
      modal.classList.remove("hidden");
      modal.classList.add("flex");
      if (window.lucide) lucide.createIcons();
    }
  }
}

let saasPlansCache = [];

async function loadSuperAdminConsoleData() {
  await Promise.all([
    fetchPlatformSummary(),
    fetchPlatformPlans(),
    fetchPlatformOrganizations(),
    fetchPlatformUsers()
  ]);
}

async function fetchPlatformSummary() {
  try {
    const res = await authFetch("/api/v1/admin/platform-summary");
    if (!res.ok) return;
    const summary = await res.json();
    saasPlatformSummary = summary;

    const totalOrgsEl = document.getElementById("saasTotalOrgs");
    if (totalOrgsEl) totalOrgsEl.textContent = summary.total_organizations;

    const activeSubsEl = document.getElementById("saasActiveSubs");
    if (activeSubsEl) activeSubsEl.textContent = summary.active_subscriptions;

    const trialSubsEl = document.getElementById("saasTrialSubs");
    if (trialSubsEl) trialSubsEl.textContent = summary.trial_subscriptions;

    const expiredSubsEl = document.getElementById("saasExpiredSubs");
    if (expiredSubsEl) expiredSubsEl.textContent = summary.expired_subscriptions;

    const totalSalesEl = document.getElementById("saasTotalSales");
    if (totalSalesEl) totalSalesEl.textContent = Number(summary.total_sales_volume).toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 });

    const totalTxEl = document.getElementById("saasTotalTx");
    if (totalTxEl) totalTxEl.textContent = summary.total_transactions;

    const connectedBotsEl = document.getElementById("saasConnectedBots");
    if (connectedBotsEl) connectedBotsEl.textContent = summary.connected_bots;

    const mrrEl = document.getElementById("saasMrr");
    if (mrrEl) mrrEl.textContent = Number(summary.monthly_revenue_jod).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } catch (err) {
    console.error("fetchPlatformSummary error:", err);
  }
}

async function fetchPlatformPlans() {
  const container = document.getElementById("saasPlansCardsContainer");
  if (!container) return;

  try {
    const res = await authFetch("/api/v1/admin/plans");
    if (!res.ok) throw new Error("فشل جلب خطط الاشتراك");
    const plans = await res.json();
    saasPlansCache = plans;

    // Update plans filter in orgs table
    const planFilter = document.getElementById("saasPlanFilter");
    if (planFilter) {
      const currentVal = planFilter.value;
      planFilter.innerHTML = `<option value="ALL">كافة خطط الاشتراك</option>` +
        plans.map(p => `<option value="${p.code}">${p.name} (${p.code})</option>`).join("");
      planFilter.value = currentVal;
    }

    // Update New Org Plan dropdown
    const newOrgPlanSelect = document.getElementById("modalNewOrgPlan");
    if (newOrgPlanSelect) {
      const current = newOrgPlanSelect.value;
      newOrgPlanSelect.innerHTML = plans.filter(p => p.is_active).map(p => 
        `<option value="${p.code}" data-price="${p.price_monthly_jod}" ${p.code === current ? 'selected' : ''}>${p.name} - ${p.price_monthly_jod} د.أ/شهرياً</option>`
      ).join("");
    }

    // Update Edit Org Plan dropdown
    const editOrgPlanSelect = document.getElementById("editOrgPlanSelect");
    if (editOrgPlanSelect) {
      const current = editOrgPlanSelect.value;
      editOrgPlanSelect.innerHTML = plans.map(p => 
        `<option value="${p.code}" data-price="${p.price_monthly_jod}" ${p.code === current ? 'selected' : ''}>${p.name} (${p.code}) - ${p.price_monthly_jod} د.أ</option>`
      ).join("");
    }

    // Render cards
    container.innerHTML = plans.map(p => {
      const colorMap = {
        emerald: { border: "border-emerald-500/30", bg: "bg-emerald-500/10", text: "text-emerald-400", badge: "bg-emerald-950 text-emerald-300 border-emerald-500/30" },
        indigo: { border: "border-indigo-500/30", bg: "bg-indigo-500/10", text: "text-indigo-400", badge: "bg-indigo-950 text-indigo-300 border-indigo-500/30" },
        purple: { border: "border-purple-500/30", bg: "bg-purple-500/10", text: "text-purple-400", badge: "bg-purple-950 text-purple-300 border-purple-500/30" },
        amber: { border: "border-amber-500/30", bg: "bg-amber-500/10", text: "text-amber-400", badge: "bg-amber-950 text-amber-300 border-amber-500/30" },
        sky: { border: "border-sky-500/30", bg: "bg-sky-500/10", text: "text-sky-400", badge: "bg-sky-950 text-sky-300 border-sky-500/30" },
        rose: { border: "border-rose-500/30", bg: "bg-rose-500/10", text: "text-rose-400", badge: "bg-rose-950 text-rose-300 border-rose-500/30" }
      };
      const theme = colorMap[p.badge_color] || colorMap.indigo;

      return `
        <div class="glass-card rounded-xl p-4 border ${theme.border} relative flex flex-col justify-between hover:border-slate-600 transition shadow-lg">
          <div>
            <div class="flex items-start justify-between gap-2 mb-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold border ${theme.badge}">
                ${p.code}
              </span>
              ${p.is_active ? `
                <span class="text-[10px] text-emerald-400 bg-emerald-950/80 border border-emerald-500/30 px-2 py-0.5 rounded-full font-bold">متاحة</span>
              ` : `
                <span class="text-[10px] text-slate-400 bg-slate-900 border border-slate-700 px-2 py-0.5 rounded-full font-bold">معطلة</span>
              `}
            </div>

            <h4 class="font-extrabold text-white text-sm mb-1">${p.name}</h4>
            <p class="text-[11px] text-slate-400 mb-3 min-h-[32px]">${p.description || 'خطة اشتراك سحابية قياسية'}</p>

            <div class="mb-3 pb-3 border-b border-slate-800">
              <div class="text-2xl font-black text-white">
                ${p.price_monthly_jod} <span class="text-xs font-normal text-slate-400">د.أ / شهرياً</span>
              </div>
              <div class="text-[10px] text-slate-400">
                أو ${p.price_annual_jod} د.أ / سنوياً
              </div>
            </div>

            <div class="space-y-1.5 text-xs text-slate-300 mb-4">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">الفروع المسموحة:</span>
                <span class="font-bold text-white">${p.max_branches === -1 ? 'غير محدود ♾️' : p.max_branches}</span>
              </div>
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">المستخدمين:</span>
                <span class="font-bold text-white">${p.max_users === -1 ? 'غير محدود ♾️' : p.max_users}</span>
              </div>
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">الحد الشهري للفواتير:</span>
                <span class="font-bold text-white">${p.max_transactions_monthly === -1 ? 'غير محدود ♾️' : p.max_transactions_monthly.toLocaleString()}</span>
              </div>
              
              <div class="pt-2 border-t border-slate-800/80 space-y-1 text-[11px]">
                <div class="flex items-center gap-1.5 ${p.has_telegram_bot ? 'text-sky-300' : 'text-slate-500 line-through'}">
                  <i data-lucide="${p.has_telegram_bot ? 'check' : 'x'}" class="w-3 h-3"></i>
                  <span>بوت تلغرام مخصص</span>
                </div>
                <div class="flex items-center gap-1.5 ${p.has_jofotara_qr ? 'text-emerald-300' : 'text-slate-500 line-through'}">
                  <i data-lucide="${p.has_jofotara_qr ? 'check' : 'x'}" class="w-3 h-3"></i>
                  <span>فواتير JoFotara QR</span>
                </div>
                <div class="flex items-center gap-1.5 ${p.has_ai_daily_brief ? 'text-indigo-300' : 'text-slate-500 line-through'}">
                  <i data-lucide="${p.has_ai_daily_brief ? 'check' : 'x'}" class="w-3 h-3"></i>
                  <span>ملخص ذكاء اصطناعي</span>
                </div>
              </div>
            </div>
          </div>

          <div class="pt-2 border-t border-slate-800 flex items-center justify-between">
            <span class="text-[10px] text-slate-400">
              المشتركين: <strong class="text-white">${p.subscriber_count}</strong> منشأة
            </span>
            <button type="button" onclick="window.openEditPlanModal('${p.id}')" class="bg-indigo-600/20 hover:bg-indigo-600 text-indigo-300 hover:text-white border border-indigo-500/30 px-2.5 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1 cursor-pointer">
              <i data-lucide="edit" class="w-3 h-3"></i>
              <span>تعديل الخطة</span>
            </button>
          </div>
        </div>
      `;
    }).join("");

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("fetchPlatformPlans error:", err);
    container.innerHTML = `<div class="col-span-4 p-4 text-center text-rose-400 text-xs">فشل جلب خطط الاشتراك: ${err.message}</div>`;
  }
}

async function fetchPlatformOrganizations() {
  const tbody = document.getElementById("saasOrgsTableBody");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">جاري تحميل بيانات المنشآت والاشتراكات...</td></tr>`;
  }
  try {
    const res = await authFetch("/api/v1/admin/organizations");
    if (!res.ok) throw new Error("فشل جلب قائمة المنشآت");
    const orgs = await res.json();
    saasOrgsCache = orgs;
    platformOrgsList = orgs;
    filterAndRenderSaasTable();
  } catch (err) {
    console.error("fetchPlatformOrganizations error:", err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-rose-400">خطأ في التحميل: ${err.message}</td></tr>`;
    }
  }
}

function filterAndRenderSaasTable() {
  const tbody = document.getElementById("saasOrgsTableBody");
  if (!tbody) return;

  const searchVal = (document.getElementById("saasSearchInput")?.value || "").trim().toLowerCase();
  const statusVal = document.getElementById("saasStatusFilter")?.value || "ALL";
  const planVal = document.getElementById("saasPlanFilter")?.value || "ALL";

  let filtered = saasOrgsCache.filter(org => {
    // Status filter
    if (statusVal !== "ALL" && org.subscription_status !== statusVal) {
      return false;
    }
    // Plan filter
    if (planVal !== "ALL" && org.subscription_plan !== planVal) {
      return false;
    }
    // Search query
    if (searchVal) {
      const name = (org.name || "").toLowerCase();
      const tax = (org.tax_number || "").toLowerCase();
      const adminName = (org.admin_user?.full_name || "").toLowerCase();
      const adminUser = (org.admin_user?.username || "").toLowerCase();
      const email = (org.contact_email || "").toLowerCase();
      if (!name.includes(searchVal) && !tax.includes(searchVal) && !adminName.includes(searchVal) && !adminUser.includes(searchVal) && !email.includes(searchVal)) {
        return false;
      }
    }
    return true;
  });

  const countEl = document.getElementById("saasFilteredCount");
  if (countEl) countEl.textContent = filtered.length;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-slate-400">لا توجد منشآت مطابقة لمعايير البحث.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(o => {
    const branchesCount = (o.branches || []).length;
    const branchesBadge = branchesCount > 1 
      ? `<span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded border border-slate-700">${branchesCount} فروع</span>`
      : `<span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded border border-slate-700">فرع رئيسي</span>`;

    // Plan styling
    const planStyles = {
      "PRO": { badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30", label: "🟢 احترافية (PRO)" },
      "BASIC": { badge: "bg-sky-500/20 text-sky-300 border-sky-500/30", label: "🔵 أساسية (BASIC)" },
      "ENTERPRISE": { badge: "bg-purple-500/20 text-purple-300 border-purple-500/30", label: "🟣 مؤسسية (ENTERPRISE)" },
      "TRIAL": { badge: "bg-amber-500/20 text-amber-300 border-amber-500/30", label: "🟡 تجريبية (TRIAL)" }
    };
    const pMeta = planStyles[o.subscription_plan] || { badge: "bg-slate-700 text-slate-300 border-slate-600", label: o.subscription_plan };

    // Status styling
    const statusStyles = {
      "ACTIVE": { badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30", dot: "bg-emerald-400", label: "نشط" },
      "TRIAL": { badge: "bg-amber-500/20 text-amber-300 border-amber-500/30", dot: "bg-amber-400", label: "تجريبي" },
      "EXPIRED": { badge: "bg-rose-500/20 text-rose-300 border-rose-500/30", dot: "bg-rose-400", label: "منتهي" },
      "SUSPENDED": { badge: "bg-slate-700 text-slate-300 border-slate-600", dot: "bg-slate-400", label: "معلق" }
    };
    const sMeta = statusStyles[o.subscription_status] || { badge: "bg-slate-700 text-slate-300 border-slate-600", dot: "bg-slate-400", label: o.subscription_status };

    // Days remaining badge
    let daysRemainingBadge = "";
    if (o.subscription_status === "SUSPENDED" || !o.is_active) {
      daysRemainingBadge = `<span class="text-[10px] text-slate-400 font-mono">حساب موقوف</span>`;
    } else if (o.days_remaining > 0) {
      const color = o.days_remaining <= 7 ? "text-amber-400 font-bold" : "text-emerald-400";
      daysRemainingBadge = `<span class="text-[11px] font-mono ${color}">متبقي ${o.days_remaining} يوم</span>`;
    } else {
      daysRemainingBadge = `<span class="text-[11px] font-mono text-rose-400 font-bold">انتهى الاشتراك</span>`;
    }

    // Dedicated bot badge
    const botBadge = o.has_dedicated_bot 
      ? `<span class="inline-flex items-center gap-1 bg-sky-500/20 text-sky-300 border border-sky-500/30 px-2 py-0.5 rounded-full font-mono text-[10px]">🤖 متصل</span>`
      : `<span class="text-[10px] text-slate-500 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">غير مرتبط</span>`;

    const admin = o.admin_user || {};
    const salesFormatted = Number(o.total_sales || 0).toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 });

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <!-- 1. Org Info -->
        <td class="p-3">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-purple-900/60 to-indigo-900/60 border border-purple-500/30 flex items-center justify-center flex-shrink-0">
              <i data-lucide="building" class="w-4 h-4 text-purple-300"></i>
            </div>
            <div>
              <div class="font-bold text-white text-xs flex items-center gap-1.5">
                <span>${o.name}</span>
                ${branchesBadge}
              </div>
              <div class="flex items-center gap-2 text-[10px] text-slate-400 mt-0.5">
                <span>${INDUSTRY_LABELS[o.industry_type] || o.industry_type}</span>
                <span>•</span>
                <span class="font-mono ${o.tax_number ? 'text-indigo-300' : 'text-slate-500'}">${o.tax_number || 'بدون ضريبي'}</span>
              </div>
            </div>
          </div>
        </td>

        <!-- 2. Admin & Contact -->
        <td class="p-3 text-[11px]">
          <div class="font-semibold text-slate-200">${admin.full_name || 'مدير الحساب'}</div>
          <div class="font-mono text-[10px] text-purple-300">@${admin.username || '-'}</div>
          <div class="text-[10px] text-slate-400 truncate max-w-[140px] mt-0.5" title="${o.contact_email || ''}">${o.contact_email || ''}</div>
        </td>

        <!-- 3. Subscription Plan -->
        <td class="p-3 text-center">
          <span class="px-2 py-0.5 rounded-md text-[10px] font-bold border ${pMeta.badge}">
            ${pMeta.label}
          </span>
          <div class="text-[11px] font-mono text-slate-300 mt-1">
            ${o.subscription_price_jod} <span class="text-[9px] text-slate-500">د.أ/شهرياً</span>
          </div>
        </td>

        <!-- 4. Status & Expiration -->
        <td class="p-3 text-center">
          <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold border ${sMeta.badge}">
            <span class="w-1.5 h-1.5 rounded-full ${sMeta.dot}"></span>
            <span>${sMeta.label}</span>
          </div>
          <div class="mt-1">${daysRemainingBadge}</div>
          <div class="text-[9px] text-slate-500 font-mono mt-0.5">${o.subscription_expires_at || 'غير محدد'}</div>
        </td>

        <!-- 5. Sales Volume -->
        <td class="p-3 text-center">
          <div class="font-extrabold text-white text-xs font-mono">${salesFormatted} <span class="text-[10px] font-normal text-slate-400">د.أ</span></div>
          <div class="text-[10px] text-slate-500 font-mono mt-0.5">${o.transactions_count} حركة</div>
        </td>

        <!-- 6. Bot Token Status -->
        <td class="p-3 text-center">
          ${botBadge}
        </td>

        <!-- 7. Actions -->
        <td class="p-3 text-center">
          <div class="flex items-center justify-center gap-1">
            <!-- View As Tenant -->
            <button onclick="window.enterTenantView('${o.id}')" class="bg-indigo-950/80 hover:bg-indigo-900 text-indigo-200 border border-indigo-500/40 p-1.5 rounded-lg text-xs font-semibold transition active:scale-95 cursor-pointer" title="معاينة كمنشأة (الدخول لحساب المنشأة وتفقد مبيعاتها)">
              <i data-lucide="eye" class="w-3.5 h-3.5"></i>
            </button>

            <!-- Toggle Active / Suspend -->
            <button onclick="window.toggleOrgStatus('${o.id}')" class="${o.is_active ? 'bg-amber-950/70 hover:bg-amber-900 text-amber-300 border-amber-500/30' : 'bg-emerald-950/70 hover:bg-emerald-900 text-emerald-300 border-emerald-500/30'} border p-1.5 rounded-lg text-xs font-semibold transition active:scale-95 cursor-pointer" title="${o.is_active ? 'تعليق / إيقاف الحساب' : 'إعادة تفعيل الحساب'}">
              <i data-lucide="${o.is_active ? 'pause' : 'play'}" class="w-3.5 h-3.5"></i>
            </button>

            <!-- Edit Subscription -->
            <button onclick="window.openEditOrgModal('${o.id}')" class="bg-purple-950/70 hover:bg-purple-900 text-purple-200 border border-purple-500/30 p-1.5 rounded-lg text-xs font-semibold transition active:scale-95 cursor-pointer" title="تعديل خطة الاشتراك والسعر والبيانات">
              <i data-lucide="settings-2" class="w-3.5 h-3.5"></i>
            </button>

            <!-- Password Management -->
            <button onclick="window.openTenantPasswordModal('${o.id}')" class="bg-blue-950/70 hover:bg-blue-900 text-blue-200 border border-blue-500/30 p-1.5 rounded-lg text-xs font-semibold transition active:scale-95 cursor-pointer" title="إدارة كلمة المرور (تغيير مباشر أو رابط 24 ساعة)">
              <i data-lucide="key" class="w-3.5 h-3.5"></i>
            </button>

            <!-- Delete Org -->
            <button onclick="window.confirmDeleteOrg('${o.id}')" class="bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-500/30 p-1.5 rounded-lg text-xs font-semibold transition active:scale-95 cursor-pointer" title="حذف المنشأة بالكامل">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  if (window.lucide) lucide.createIcons();
}

async function fetchPlatformUsers() {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-slate-400">جاري تحميل المستخدمين...</td></tr>`;

  try {
    const res = await authFetch("/api/v1/admin/users");
    if (!res.ok) throw new Error("فشل جلب قائمة المستخدمين");
    const users = await res.json();

    const countBadge = document.getElementById("platformUsersCountBadge");
    if (countBadge) countBadge.textContent = `${users.length} مستخدم`;

    const roleMap = {
      "SUPER_ADMIN": { label: "👑 مالك المنصة", class: "bg-purple-500/20 text-purple-300 border-purple-500/30" },
      "ORG_ADMIN": { label: "🏢 مدير المنشأة", class: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
      "ACCOUNTANT": { label: "📊 محاسب قانوني", class: "bg-sky-500/20 text-sky-300 border-sky-500/30" },
      "CASHIER": { label: "🛒 كاشير فروع", class: "bg-amber-500/20 text-amber-300 border-amber-500/30" }
    };

    tbody.innerHTML = users.map(u => {
      const meta = roleMap[u.role] || { label: u.role, class: "bg-slate-700 text-slate-300 border-slate-600" };
      return `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="p-2.5 font-mono font-bold text-white">${u.username}</td>
          <td class="p-2.5 text-slate-200">${u.full_name || '-'}</td>
          <td class="p-2.5">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold border ${meta.class}">
              ${meta.label}
            </span>
          </td>
          <td class="p-2.5 text-slate-300">${u.organization_name || '<span class="text-purple-300">المنصة المركزية</span>'}</td>
          <td class="p-2.5 text-center">
            <div class="flex items-center justify-center gap-1.5">
              <button type="button" onclick="window.openUserPasswordModal('${u.id}', '${u.username}', '${u.full_name}')" title="إعادة تعيين كلمة المرور أو توليد رابط" class="p-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 transition cursor-pointer">
                <i data-lucide="key" class="w-3.5 h-3.5"></i>
              </button>
              ${u.role !== 'SUPER_ADMIN' ? `
                <button type="button" onclick="window.confirmDeleteUser('${u.id}', '${u.username}')" title="حذف المستخدم" class="p-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 transition cursor-pointer">
                  <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join("");
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-rose-400">خطأ: ${err.message}</td></tr>`;
  }
}

window.openUserPasswordModal = (userId, username, fullName) => {
  selectedOrgForPasswordModal = {
    id: "",
    name: fullName || "مستخدم النظام",
    admin_user: {
      id: userId,
      username: username,
      full_name: fullName
    }
  };

  const modal = document.getElementById("tenantPasswordModal");
  if (!modal) return;

  const orgNameEl = document.getElementById("tenantPassModalOrgName");
  if (orgNameEl) orgNameEl.textContent = fullName || username;
  const usernameEl = document.getElementById("tenantPassModalUsername");
  if (usernameEl) usernameEl.textContent = username;

  const directPass = document.getElementById("directResetNewPass");
  if (directPass) directPass.value = "";
  const directAlert = document.getElementById("directResetAlert");
  if (directAlert) {
    directAlert.className = "hidden p-3 rounded-xl text-xs font-semibold";
    directAlert.textContent = "";
  }
  const linkAlert = document.getElementById("resetLinkAlert");
  if (linkAlert) {
    linkAlert.className = "hidden p-2.5 rounded-xl text-xs font-semibold";
    linkAlert.textContent = "";
  }
  const linkContainer = document.getElementById("generatedLinkContainer");
  if (linkContainer) linkContainer.classList.add("hidden");

  // Default to Tab 1
  const tabDirectBtn = document.getElementById("tabDirectResetBtn");
  const tabLinkBtn = document.getElementById("tabResetLinkBtn");
  const tabDirectContent = document.getElementById("tabDirectResetContent");
  const tabLinkContent = document.getElementById("tabResetLinkContent");
  if (tabDirectBtn && tabLinkBtn && tabDirectContent && tabLinkContent) {
    tabDirectBtn.className = "px-3.5 py-2 text-indigo-400 border-b-2 border-indigo-500 transition flex items-center gap-1.5 cursor-pointer";
    tabLinkBtn.className = "px-3.5 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
    tabDirectContent.classList.remove("hidden");
    tabLinkContent.classList.add("hidden");
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  if (window.lucide) lucide.createIcons();
};

window.confirmDeleteUser = async (userId, username) => {
  if (!confirm(`⚠️ تحذير:\nهل أنت متأكد من حذف حساب المستخدم "${username}"؟`)) return;
  try {
    const res = await authFetch(`/api/v1/admin/users/${userId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "فشل حذف المستخدم");
    }
    await fetchPlatformUsers();
  } catch (err) {
    alert(`❌ خطأ: ${err.message}`);
  }
};

// Global actions exposed to window
window.enterTenantView = async (orgId) => {
  isInspectingTenant = true;
  selectedTenantOrgId = orgId;
  inspectingOrgData = saasOrgsCache.find(o => o.id === orgId) || null;
  renderAppView();
  await fetchAllData();
  window.scrollTo({ top: 0, behavior: "smooth" });
};

window.exitTenantView = async () => {
  isInspectingTenant = false;
  selectedTenantOrgId = null;
  inspectingOrgData = null;
  renderAppView();
  await loadSuperAdminConsoleData();
  window.scrollTo({ top: 0, behavior: "smooth" });
};

window.toggleOrgStatus = async (orgId) => {
  try {
    const res = await authFetch(`/api/v1/admin/organizations/${orgId}/toggle-status`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "فشل تغيير حالة المنشأة");
    }
    await loadSuperAdminConsoleData();
  } catch (err) {
    alert(`❌ خطأ: ${err.message}`);
  }
};

window.confirmDeleteOrg = async (orgId) => {
  const org = saasOrgsCache.find(o => o.id === orgId);
  const name = org ? org.name : orgId;
  if (!confirm(`⚠️ تحذير أمني:\nهل أنت متأكد من حذف منشأة "${name}" بالكامل؟\nسيتم حذف كافة العمليات والفروع وحسابات المستخدمين التابعة لها ولا يمكن التراجع.`)) {
    return;
  }
  try {
    const res = await authFetch(`/api/v1/admin/organizations/${orgId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "فشل حذف المنشأة");
    }
    alert(`✅ تم حذف منشأة "${name}" بنجاح.`);
    await loadSuperAdminConsoleData();
  } catch (err) {
    alert(`❌ خطأ: ${err.message}`);
  }
};

window.openEditOrgModal = (orgId) => {
  const org = saasOrgsCache.find(o => o.id === orgId);
  if (!org) return;

  const modal = document.getElementById("editOrgSubscriptionModal");
  if (!modal) return;

  document.getElementById("editOrgIdHidden").value = org.id;
  document.getElementById("editOrgModalName").textContent = org.name;
  document.getElementById("editOrgNameInput").value = org.name || "";
  document.getElementById("editOrgIndustrySelect").value = org.industry_type || "retail";
  document.getElementById("editOrgTaxInput").value = org.tax_number || "";
  document.getElementById("editOrgPlanSelect").value = org.subscription_plan || "PRO";
  document.getElementById("editOrgStatusSelect").value = org.subscription_status || "ACTIVE";
  document.getElementById("editOrgExpiryInput").value = org.subscription_expires_at || "";
  document.getElementById("editOrgPriceInput").value = org.subscription_price_jod || 0;
  document.getElementById("editOrgEmailInput").value = org.contact_email || "";
  document.getElementById("editOrgPhoneInput").value = org.contact_phone || "";
  document.getElementById("editOrgBotTokenInput").value = org.telegram_bot_token || "";

  const alertBox = document.getElementById("editOrgAlert");
  if (alertBox) {
    alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
    alertBox.textContent = "";
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  if (window.lucide) lucide.createIcons();
};

window.openTenantPasswordModal = (orgId) => {
  const org = saasOrgsCache.find(o => o.id === orgId);
  if (!org) return;

  selectedOrgForPasswordModal = org;
  const modal = document.getElementById("tenantPasswordModal");
  if (!modal) return;

  document.getElementById("tenantPassModalOrgName").textContent = org.name;
  document.getElementById("tenantPassModalUsername").textContent = org.admin_user ? org.admin_user.username : "مدير المنشأة";

  const directPass = document.getElementById("directResetNewPass");
  if (directPass) directPass.value = "";
  const directAlert = document.getElementById("directResetAlert");
  if (directAlert) {
    directAlert.className = "hidden p-3 rounded-xl text-xs font-semibold";
    directAlert.textContent = "";
  }
  const linkAlert = document.getElementById("resetLinkAlert");
  if (linkAlert) {
    linkAlert.className = "hidden p-2.5 rounded-xl text-xs font-semibold";
    linkAlert.textContent = "";
  }
  const linkContainer = document.getElementById("generatedLinkContainer");
  if (linkContainer) linkContainer.classList.add("hidden");

  // Default to Tab 1
  const tabDirectBtn = document.getElementById("tabDirectResetBtn");
  const tabLinkBtn = document.getElementById("tabResetLinkBtn");
  const tabDirectContent = document.getElementById("tabDirectResetContent");
  const tabLinkContent = document.getElementById("tabResetLinkContent");
  if (tabDirectBtn && tabLinkBtn && tabDirectContent && tabLinkContent) {
    tabDirectBtn.className = "px-3.5 py-2 text-indigo-400 border-b-2 border-indigo-500 transition flex items-center gap-1.5 cursor-pointer";
    tabLinkBtn.className = "px-3.5 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
    tabDirectContent.classList.remove("hidden");
    tabLinkContent.classList.add("hidden");
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  if (window.lucide) lucide.createIcons();
};

function setupSuperAdminConsole() {
  // 1. Search and Filters
  const searchInput = document.getElementById("saasSearchInput");
  const statusFilter = document.getElementById("saasStatusFilter");
  const planFilter = document.getElementById("saasPlanFilter");

  if (searchInput) searchInput.addEventListener("input", filterAndRenderSaasTable);
  if (statusFilter) statusFilter.addEventListener("change", filterAndRenderSaasTable);
  if (planFilter) planFilter.addEventListener("change", filterAndRenderSaasTable);

  // 2. Exit Inspection Buttons
  const exitBtn1 = document.getElementById("exitTenantInspectionBtn");
  const exitBtn2 = document.getElementById("headerExitInspectionBtn");
  if (exitBtn1) exitBtn1.addEventListener("click", window.exitTenantView);
  if (exitBtn2) exitBtn2.addEventListener("click", window.exitTenantView);

  // 3. Refresh Console Button
  const refreshAdminBtn = document.getElementById("headerRefreshAdminBtn");
  if (refreshAdminBtn) refreshAdminBtn.addEventListener("click", loadSuperAdminConsoleData);

  // 4. Users Accordion Toggle
  const toggleUsersBtn = document.getElementById("togglePlatformUsersBtn");
  const usersSection = document.getElementById("platformUsersSection");
  const toggleIcon = document.getElementById("togglePlatformUsersIcon");
  if (toggleUsersBtn && usersSection) {
    toggleUsersBtn.addEventListener("click", () => {
      const isHidden = usersSection.classList.contains("hidden");
      if (isHidden) {
        usersSection.classList.remove("hidden");
        if (toggleIcon) toggleIcon.style.transform = "rotate(180deg)";
        fetchPlatformUsers();
      } else {
        usersSection.classList.add("hidden");
        if (toggleIcon) toggleIcon.style.transform = "rotate(0deg)";
      }
    });
  }

  // 5. Create Org Modal
  const createModal = document.getElementById("createOrgModal");
  const openCreateBtns = [
    document.getElementById("headerAddOrgBtn"),
    document.getElementById("adminConsoleAddOrgBtn"),
    document.getElementById("saasAddNewOrgBtn")
  ];
  const closeCreateBtn = document.getElementById("closeCreateOrgModalBtn");
  const cancelCreateBtn = document.getElementById("cancelCreateOrgModalBtn");
  const createForm = document.getElementById("createOrgModalForm");

  openCreateBtns.forEach(btn => {
    if (btn && createModal) {
      btn.addEventListener("click", () => {
        createForm?.reset();
        const alertBox = document.getElementById("createOrgAlert");
        if (alertBox) {
          alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "";
        }
        createModal.classList.remove("hidden");
        createModal.classList.add("flex");
        if (window.lucide) lucide.createIcons();
      });
    }
  });

  const closeCreateModal = () => {
    if (createModal) {
      createModal.classList.add("hidden");
      createModal.classList.remove("flex");
    }
  };
  if (closeCreateBtn) closeCreateBtn.addEventListener("click", closeCreateModal);
  if (cancelCreateBtn) cancelCreateBtn.addEventListener("click", closeCreateModal);

  if (createForm) {
    createForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = document.getElementById("submitCreateOrgModalBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("createOrgAlert");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري إنشاء المنشأة والاشتراك...</span>`;
      }
      try {
        const payload = {
          name: document.getElementById("modalNewOrgName").value.trim(),
          industry_type: document.getElementById("modalNewOrgIndustry").value,
          tax_number: document.getElementById("modalNewOrgTax").value.trim() || null,
          branches: document.getElementById("modalNewOrgBranches").value.split(",").map(s => s.trim()).filter(Boolean),
          subscription_plan: document.getElementById("modalNewOrgPlan").value,
          subscription_duration_months: parseInt(document.getElementById("modalNewOrgDuration").value, 10) || 12,
          subscription_price_jod: parseFloat(document.getElementById("modalNewOrgPrice").value) || 0,
          contact_email: document.getElementById("modalNewOrgEmail").value.trim() || null,
          contact_phone: document.getElementById("modalNewOrgPhone").value.trim() || null,
          telegram_bot_token: document.getElementById("modalNewOrgBotToken").value.trim() || null,
          admin_username: document.getElementById("modalNewOrgAdminUser").value.trim(),
          admin_full_name: document.getElementById("modalNewOrgAdminName").value.trim(),
          admin_password: document.getElementById("modalNewOrgAdminPass").value.trim()
        };

        const res = await authFetch("/api/v1/admin/organizations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تسجيل المنشأة");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
        }

        setTimeout(() => {
          closeCreateModal();
          loadSuperAdminConsoleData();
        }, 1000);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  // 6. Admin Profile Modal (Super Admin Settings)
  const profileModal = document.getElementById("adminProfileModal");
  const openProfileBtns = [
    document.getElementById("headerAdminProfileBtn"),
    document.getElementById("adminConsoleProfileBtn")
  ];
  const closeProfileBtn = document.getElementById("closeAdminProfileModalBtn");
  const cancelProfileBtn = document.getElementById("cancelAdminProfileBtn");
  const profileForm = document.getElementById("adminProfileForm");

  openProfileBtns.forEach(btn => {
    if (btn && profileModal) {
      btn.addEventListener("click", () => {
        if (currentUser) {
          document.getElementById("adminProfileFullName").value = currentUser.full_name || "";
          document.getElementById("adminProfileEmail").value = currentUser.email || "";
        }
        document.getElementById("adminProfileCurrentPass").value = "";
        document.getElementById("adminProfileNewPass").value = "";
        const alertBox = document.getElementById("adminProfileAlert");
        if (alertBox) {
          alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "";
        }
        profileModal.classList.remove("hidden");
        profileModal.classList.add("flex");
        if (window.lucide) lucide.createIcons();
      });
    }
  });

  const closeProfileModal = () => {
    if (profileModal) {
      profileModal.classList.add("hidden");
      profileModal.classList.remove("flex");
    }
  };
  if (closeProfileBtn) closeProfileBtn.addEventListener("click", closeProfileModal);
  if (cancelProfileBtn) cancelProfileBtn.addEventListener("click", closeProfileModal);

  if (profileForm) {
    profileForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = document.getElementById("submitAdminProfileBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("adminProfileAlert");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري حفظ وتحديث الحساب...</span>`;
      }
      try {
        const payload = {
          full_name: document.getElementById("adminProfileFullName").value.trim(),
          email: document.getElementById("adminProfileEmail").value.trim()
        };

        const currentPass = document.getElementById("adminProfileCurrentPass").value;
        const newPass = document.getElementById("adminProfileNewPass").value;
        if (newPass) {
          if (!currentPass) {
            throw new Error("يرجى إدخال كلمة المرور الحالية لتأكيد التغيير.");
          }
          payload.current_password = currentPass;
          payload.new_password = newPass;
        }

        const res = await authFetch("/api/v1/admin/profile", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تحديث ملف الحساب");
        }

        const data = await res.json();
        currentUser = { ...currentUser, ...data.user };
        updateHeaderUserUI();

        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
        }

        setTimeout(() => {
          closeProfileModal();
        }, 1100);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  // 7. Edit Organization Subscription Modal
  const editOrgModal = document.getElementById("editOrgSubscriptionModal");
  const closeEditOrgBtn = document.getElementById("closeEditOrgModalBtn");
  const cancelEditOrgBtn = document.getElementById("cancelEditOrgBtn");
  const editOrgForm = document.getElementById("editOrgSubscriptionForm");

  const closeEditModal = () => {
    if (editOrgModal) {
      editOrgModal.classList.add("hidden");
      editOrgModal.classList.remove("flex");
    }
  };
  if (closeEditOrgBtn) closeEditOrgBtn.addEventListener("click", closeEditModal);
  if (cancelEditOrgBtn) cancelEditOrgBtn.addEventListener("click", closeEditModal);

  if (editOrgForm) {
    editOrgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const orgId = document.getElementById("editOrgIdHidden").value;
      const submitBtn = document.getElementById("submitEditOrgBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("editOrgAlert");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري حفظ التعديلات...</span>`;
      }
      try {
        const payload = {
          name: document.getElementById("editOrgNameInput").value.trim(),
          industry_type: document.getElementById("editOrgIndustrySelect").value,
          tax_number: document.getElementById("editOrgTaxInput").value.trim() || null,
          subscription_plan: document.getElementById("editOrgPlanSelect").value,
          subscription_status: document.getElementById("editOrgStatusSelect").value,
          subscription_expires_at: document.getElementById("editOrgExpiryInput").value || null,
          subscription_price_jod: parseFloat(document.getElementById("editOrgPriceInput").value) || 0,
          contact_email: document.getElementById("editOrgEmailInput").value.trim() || null,
          contact_phone: document.getElementById("editOrgPhoneInput").value.trim() || null,
          telegram_bot_token: document.getElementById("editOrgBotTokenInput").value.trim() || null
        };

        const res = await authFetch(`/api/v1/admin/organizations/${orgId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تعديل المنشأة");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
        }

        setTimeout(() => {
          closeEditModal();
          loadSuperAdminConsoleData();
        }, 900);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  // 8. Tenant Password Modal (Direct & Link Tabs)
  const passModal = document.getElementById("tenantPasswordModal");
  const closePassBtns = [
    document.getElementById("closeTenantPasswordModalBtn"),
    document.getElementById("closeTenantPassModalDirectBtn"),
    document.getElementById("closeTenantPassModalLinkBtn")
  ];
  closePassBtns.forEach(b => {
    if (b && passModal) {
      b.addEventListener("click", () => {
        passModal.classList.add("hidden");
        passModal.classList.remove("flex");
      });
    }
  });

  const tabDirectBtn = document.getElementById("tabDirectResetBtn");
  const tabLinkBtn = document.getElementById("tabResetLinkBtn");
  const tabDirectContent = document.getElementById("tabDirectResetContent");
  const tabLinkContent = document.getElementById("tabResetLinkContent");

  if (tabDirectBtn && tabLinkBtn && tabDirectContent && tabLinkContent) {
    tabDirectBtn.addEventListener("click", () => {
      tabDirectBtn.className = "px-3.5 py-2 text-indigo-400 border-b-2 border-indigo-500 transition flex items-center gap-1.5 cursor-pointer";
      tabLinkBtn.className = "px-3.5 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
      tabDirectContent.classList.remove("hidden");
      tabLinkContent.classList.add("hidden");
    });

    tabLinkBtn.addEventListener("click", () => {
      tabLinkBtn.className = "px-3.5 py-2 text-indigo-400 border-b-2 border-indigo-500 transition flex items-center gap-1.5 cursor-pointer";
      tabDirectBtn.className = "px-3.5 py-2 text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center gap-1.5 cursor-pointer";
      tabLinkContent.classList.remove("hidden");
      tabDirectContent.classList.add("hidden");
    });
  }

  // Direct Password Reset Submit
  const submitDirectBtn = document.getElementById("submitDirectResetBtn");
  if (submitDirectBtn) {
    submitDirectBtn.addEventListener("click", async () => {
      if (!selectedOrgForPasswordModal || !selectedOrgForPasswordModal.admin_user) {
        alert("لم يتم العثور على حساب المدير لهذه المنشأة.");
        return;
      }
      const newPass = document.getElementById("directResetNewPass")?.value;
      const alertBox = document.getElementById("directResetAlert");
      if (!newPass || newPass.length < 6) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "يجب ألا تقل كلمة المرور عن 6 خانات.";
          alertBox.classList.remove("hidden");
        }
        return;
      }

      submitDirectBtn.disabled = true;
      try {
        const userId = selectedOrgForPasswordModal.admin_user.id;
        const res = await authFetch(`/api/v1/admin/users/${userId}/reset-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: newPass })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تعيين كلمة المرور");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
          alertBox.classList.remove("hidden");
        }
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
          alertBox.classList.remove("hidden");
        }
      } finally {
        submitDirectBtn.disabled = false;
      }
    });
  }

  // Generate 24h Reset Link Submit
  const generateLinkBtn = document.getElementById("generateResetLinkBtn");
  if (generateLinkBtn) {
    generateLinkBtn.addEventListener("click", async () => {
      if (!selectedOrgForPasswordModal || !selectedOrgForPasswordModal.admin_user) {
        alert("لم يتم العثور على حساب المدير لهذه المنشأة.");
        return;
      }

      generateLinkBtn.disabled = true;
      generateLinkBtn.innerHTML = `<span>جاري توليد الرابط الأمني...</span>`;
      try {
        const userId = selectedOrgForPasswordModal.admin_user.id;
        const res = await authFetch(`/api/v1/admin/users/${userId}/generate-reset-link`, {
          method: "POST"
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل توليد رابط إعادة التعيين");
        }

        const data = await res.json();
        const fullUrl = `${window.location.origin}${data.reset_url}`;

        const linkInput = document.getElementById("generatedResetLinkInput");
        if (linkInput) linkInput.value = fullUrl;

        const linkContainer = document.getElementById("generatedLinkContainer");
        if (linkContainer) linkContainer.classList.remove("hidden");

        const linkAlert = document.getElementById("resetLinkAlert");
        if (linkAlert) {
          linkAlert.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-2.5 rounded-xl text-xs font-semibold";
          linkAlert.textContent = `✅ تم توليد الرابط بنجاح وهو صالح لمدة 24 ساعة لمرة واحدة.`;
          linkAlert.classList.remove("hidden");
        }

        // Wire Copy Button
        const copyBtn = document.getElementById("copyResetLinkBtn");
        if (copyBtn) {
          copyBtn.onclick = () => {
            navigator.clipboard.writeText(fullUrl);
            copyBtn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-400"></i><span>تم النسخ!</span>`;
            if (window.lucide) lucide.createIcons();
            setTimeout(() => {
              copyBtn.innerHTML = `<i data-lucide="copy" class="w-3.5 h-3.5"></i><span>نسخ</span>`;
              if (window.lucide) lucide.createIcons();
            }, 2000);
          };
        }

        // Wire WhatsApp Button
        const waBtn = document.getElementById("sendResetLinkWhatsAppBtn");
        if (waBtn) {
          waBtn.onclick = () => {
            const orgName = selectedOrgForPasswordModal.name || "المنشأة";
            const msg = `مرحباً بك، هذا رابط إعادة تعيين كلمة المرور لحساب منشأة "${orgName}" في المنصة السحابية (الرابط صالح لمدة 24 ساعة لمرة واحدة فقط):\n${fullUrl}`;
            const waUrl = `https://wa.me/?text=${encodeURIComponent(msg)}`;
            window.open(waUrl, "_blank");
          };
        }

        // Wire Email Simulation Button
        const emailBtn = document.getElementById("simulateEmailResetLinkBtn");
        if (emailBtn) {
          emailBtn.onclick = () => {
            const email = selectedOrgForPasswordModal.contact_email || selectedOrgForPasswordModal.admin_user?.email || "البريد الإلكتروني للعميل";
            if (linkAlert) {
              linkAlert.className = "bg-sky-950/70 border border-sky-500/40 text-sky-300 p-2.5 rounded-xl text-xs font-semibold";
              linkAlert.textContent = `📧 تم إرسال رسالة بريد إلكتروني تحتوي على الرابط الأمني وتعليمات إعادة التعيين إلى: ${email}`;
              linkAlert.classList.remove("hidden");
            }
          };
        }
      } catch (err) {
        alert(`❌ خطأ: ${err.message}`);
      } finally {
        generateLinkBtn.disabled = false;
        generateLinkBtn.innerHTML = `<i data-lucide="sparkles" class="w-4 h-4"></i><span>توليد رابط إعادة التعيين الآمن الآن</span>`;
        if (window.lucide) lucide.createIcons();
      }
    });
  }

  // 9. Public Reset Password Modal Form Submit
  const publicResetForm = document.getElementById("publicResetPasswordForm");
  if (publicResetForm) {
    publicResetForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const token = document.getElementById("publicResetTokenHidden")?.value;
      const pass1 = document.getElementById("publicResetNewPass")?.value;
      const pass2 = document.getElementById("publicResetConfirmPass")?.value;
      const alertBox = document.getElementById("publicResetAlert");
      const submitBtn = document.getElementById("submitPublicResetBtn");

      if (pass1 !== pass2) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "كلمتا المرور غير متطابقتين.";
          alertBox.classList.remove("hidden");
        }
        return;
      }

      if (!pass1 || pass1.length < 6) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "يجب ألا تقل كلمة المرور عن 6 خانات.";
          alertBox.classList.remove("hidden");
        }
        return;
      }

      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch("/api/v1/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, new_password: pass1 })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تعيين كلمة المرور");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
          alertBox.classList.remove("hidden");
        }

        setTimeout(() => {
          window.location.href = "/index.html";
        }, 1500);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
          alertBox.classList.remove("hidden");
        }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // 10. Super Admin Add User Modal Wireup
  const adminAddUserModal = document.getElementById("adminCreateUserModal");
  const openAdminAddUserBtn = document.getElementById("adminAddNewUserBtn");
  const closeAdminAddUserBtn = document.getElementById("closeAdminCreateUserModalBtn");
  const cancelAdminAddUserBtn = document.getElementById("cancelAdminCreateUserModalBtn");
  const adminAddUserForm = document.getElementById("adminCreateUserModalForm");

  const closeAdminAddUserModal = () => {
    if (adminAddUserModal) {
      adminAddUserModal.classList.add("hidden");
      adminAddUserModal.classList.remove("flex");
    }
  };

  if (openAdminAddUserBtn && adminAddUserModal) {
    openAdminAddUserBtn.addEventListener("click", () => {
      adminAddUserForm?.reset();
      const alertBox = document.getElementById("adminCreateUserAlert");
      if (alertBox) {
        alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
        alertBox.textContent = "";
      }

      // Populate Org select
      const orgSelect = document.getElementById("modalAdminUserOrgSelect");
      if (orgSelect) {
        orgSelect.innerHTML = `<option value="">👑 المنصة المركزية (Super Admin فقط)</option>` +
          saasOrgsCache.map(o => `<option value="${o.id}">${o.name} (${o.tax_number || 'بدون ضريبي'})</option>`).join("");
      }

      adminAddUserModal.classList.remove("hidden");
      adminAddUserModal.classList.add("flex");
      if (window.lucide) lucide.createIcons();
    });
  }

  if (closeAdminAddUserBtn) closeAdminAddUserBtn.addEventListener("click", closeAdminAddUserModal);
  if (cancelAdminAddUserBtn) cancelAdminAddUserBtn.addEventListener("click", closeAdminAddUserModal);

  if (adminAddUserForm) {
    adminAddUserForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = document.getElementById("submitAdminCreateUserModalBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("adminCreateUserAlert");
      
      const orgIdVal = document.getElementById("modalAdminUserOrgSelect").value.trim() || null;
      const roleVal = document.getElementById("modalAdminUserRole").value;

      if (roleVal !== "SUPER_ADMIN" && !orgIdVal) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = "⚠️ يرجى اختيار المنشأة التابع لها هذا المستخدم، أو اختيار رتبة 'مالك منصة' لحسابات المنصة العامة.";
          alertBox.classList.remove("hidden");
        }
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري إنشاء المستخدم...</span>`;
      }

      try {
        const payload = {
          organization_id: orgIdVal,
          username: document.getElementById("modalAdminUserUsername").value.trim(),
          full_name: document.getElementById("modalAdminUserFullName").value.trim(),
          email: document.getElementById("modalAdminUserEmail").value.trim() || null,
          password: document.getElementById("modalAdminUserPass").value.trim(),
          role: roleVal
        };

        const res = await authFetch("/api/v1/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل إنشاء المستخدم");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
          alertBox.classList.remove("hidden");
        }

        setTimeout(() => {
          closeAdminAddUserModal();
          fetchPlatformUsers();
          fetchPlatformOrganizations();
        }, 900);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
          alertBox.classList.remove("hidden");
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  // 11. Create Plan Modal Wireup
  const createPlanModal = document.getElementById("createPlanModal");
  const openCreatePlanBtn = document.getElementById("saasAddNewPlanBtn");
  const closeCreatePlanBtn = document.getElementById("closeCreatePlanModalBtn");
  const cancelCreatePlanBtn = document.getElementById("cancelCreatePlanModalBtn");
  const createPlanForm = document.getElementById("createPlanModalForm");

  const closeCreatePlanModal = () => {
    if (createPlanModal) {
      createPlanModal.classList.add("hidden");
      createPlanModal.classList.remove("flex");
    }
  };

  if (openCreatePlanBtn && createPlanModal) {
    openCreatePlanBtn.addEventListener("click", () => {
      createPlanForm?.reset();
      const alertBox = document.getElementById("createPlanAlert");
      if (alertBox) {
        alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
        alertBox.textContent = "";
      }
      createPlanModal.classList.remove("hidden");
      createPlanModal.classList.add("flex");
      if (window.lucide) lucide.createIcons();
    });
  }

  if (closeCreatePlanBtn) closeCreatePlanBtn.addEventListener("click", closeCreatePlanModal);
  if (cancelCreatePlanBtn) cancelCreatePlanBtn.addEventListener("click", closeCreatePlanModal);

  if (createPlanForm) {
    createPlanForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = document.getElementById("submitCreatePlanModalBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("createPlanAlert");

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري حفظ الخطة...</span>`;
      }

      try {
        const payload = {
          code: document.getElementById("modalNewPlanCode").value.trim(),
          name: document.getElementById("modalNewPlanName").value.trim(),
          price_monthly_jod: parseFloat(document.getElementById("modalNewPlanPriceMonthly").value) || 0,
          price_annual_jod: parseFloat(document.getElementById("modalNewPlanPriceAnnual").value) || 0,
          max_branches: parseInt(document.getElementById("modalNewPlanBranches").value) || 1,
          max_users: parseInt(document.getElementById("modalNewPlanUsers").value) || 3,
          max_transactions_monthly: parseInt(document.getElementById("modalNewPlanTx").value) || 1000,
          badge_color: document.getElementById("modalNewPlanBadgeColor").value,
          description: document.getElementById("modalNewPlanDesc").value.trim() || null,
          has_telegram_bot: document.getElementById("modalNewPlanBot").checked,
          has_jofotara_qr: document.getElementById("modalNewPlanJoFotara").checked,
          has_ai_daily_brief: document.getElementById("modalNewPlanBrief").checked,
          has_tax_reports: document.getElementById("modalNewPlanTax").checked,
          is_active: true
        };

        const res = await authFetch("/api/v1/admin/plans", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل إنشاء الخطة");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
          alertBox.classList.remove("hidden");
        }

        setTimeout(() => {
          closeCreatePlanModal();
          fetchPlatformPlans();
        }, 900);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
          alertBox.classList.remove("hidden");
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  // 12. Edit Plan Modal Wireup
  const editPlanModal = document.getElementById("editPlanModal");
  const closeEditPlanBtn = document.getElementById("closeEditPlanModalBtn");
  const cancelEditPlanBtn = document.getElementById("cancelEditPlanModalBtn");
  const editPlanForm = document.getElementById("editPlanModalForm");
  const deletePlanBtn = document.getElementById("deletePlanModalBtn");

  const closeEditPlanModal = () => {
    if (editPlanModal) {
      editPlanModal.classList.add("hidden");
      editPlanModal.classList.remove("flex");
    }
  };

  if (closeEditPlanBtn) closeEditPlanBtn.addEventListener("click", closeEditPlanModal);
  if (cancelEditPlanBtn) cancelEditPlanBtn.addEventListener("click", closeEditPlanModal);

  window.openEditPlanModal = (planId) => {
    const plan = saasPlansCache.find(p => p.id === planId);
    if (!plan || !editPlanModal) return;

    document.getElementById("modalEditPlanId").value = plan.id;
    document.getElementById("modalEditPlanCode").value = plan.code;
    document.getElementById("modalEditPlanName").value = plan.name;
    document.getElementById("modalEditPlanPriceMonthly").value = plan.price_monthly_jod;
    document.getElementById("modalEditPlanPriceAnnual").value = plan.price_annual_jod;
    document.getElementById("modalEditPlanBranches").value = plan.max_branches;
    document.getElementById("modalEditPlanUsers").value = plan.max_users;
    document.getElementById("modalEditPlanTx").value = plan.max_transactions_monthly;
    document.getElementById("modalEditPlanBadgeColor").value = plan.badge_color || "emerald";
    document.getElementById("modalEditPlanDesc").value = plan.description || "";
    document.getElementById("modalEditPlanIsActive").checked = !!plan.is_active;

    document.getElementById("modalEditPlanBot").checked = !!plan.has_telegram_bot;
    document.getElementById("modalEditPlanJoFotara").checked = !!plan.has_jofotara_qr;
    document.getElementById("modalEditPlanBrief").checked = !!plan.has_ai_daily_brief;
    document.getElementById("modalEditPlanTax").checked = !!plan.has_tax_reports;

    const alertBox = document.getElementById("editPlanAlert");
    if (alertBox) {
      alertBox.className = "hidden p-3 rounded-xl text-xs font-semibold";
      alertBox.textContent = "";
    }

    editPlanModal.classList.remove("hidden");
    editPlanModal.classList.add("flex");
    if (window.lucide) lucide.createIcons();
  };

  if (editPlanForm) {
    editPlanForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const planId = document.getElementById("modalEditPlanId").value;
      const submitBtn = document.getElementById("submitEditPlanModalBtn");
      const originalHtml = submitBtn ? submitBtn.innerHTML : "";
      const alertBox = document.getElementById("editPlanAlert");

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>جاري حفظ التعديلات...</span>`;
      }

      try {
        const payload = {
          name: document.getElementById("modalEditPlanName").value.trim(),
          price_monthly_jod: parseFloat(document.getElementById("modalEditPlanPriceMonthly").value) || 0,
          price_annual_jod: parseFloat(document.getElementById("modalEditPlanPriceAnnual").value) || 0,
          max_branches: parseInt(document.getElementById("modalEditPlanBranches").value) || 1,
          max_users: parseInt(document.getElementById("modalEditPlanUsers").value) || 3,
          max_transactions_monthly: parseInt(document.getElementById("modalEditPlanTx").value) || 1000,
          badge_color: document.getElementById("modalEditPlanBadgeColor").value,
          description: document.getElementById("modalEditPlanDesc").value.trim() || null,
          has_telegram_bot: document.getElementById("modalEditPlanBot").checked,
          has_jofotara_qr: document.getElementById("modalEditPlanJoFotara").checked,
          has_ai_daily_brief: document.getElementById("modalEditPlanBrief").checked,
          has_tax_reports: document.getElementById("modalEditPlanTax").checked,
          is_active: document.getElementById("modalEditPlanIsActive").checked
        };

        const res = await authFetch(`/api/v1/admin/plans/${planId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل تعديل الخطة");
        }

        const data = await res.json();
        if (alertBox) {
          alertBox.className = "bg-emerald-950/70 border border-emerald-500/40 text-emerald-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `✅ ${data.message}`;
          alertBox.classList.remove("hidden");
        }

        setTimeout(() => {
          closeEditPlanModal();
          fetchPlatformPlans();
          loadSuperAdminConsoleData();
        }, 900);
      } catch (err) {
        if (alertBox) {
          alertBox.className = "bg-rose-950/70 border border-rose-500/40 text-rose-300 p-3 rounded-xl text-xs font-semibold";
          alertBox.textContent = `❌ ${err.message}`;
          alertBox.classList.remove("hidden");
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalHtml;
        }
      }
    });
  }

  if (deletePlanBtn) {
    deletePlanBtn.addEventListener("click", async () => {
      const planId = document.getElementById("modalEditPlanId").value;
      const plan = saasPlansCache.find(p => p.id === planId);
      const planName = plan ? plan.name : planId;

      if (!confirm(`⚠️ تأكيد حذف الخطة:\nهل أنت متأكد من حذف باقة "${planName}" نهائياً من المنصة؟`)) {
        return;
      }

      try {
        const res = await authFetch(`/api/v1/admin/plans/${planId}`, { method: "DELETE" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "فشل حذف الخطة");
        }

        const data = await res.json();
        alert(`✅ ${data.message}`);
        closeEditPlanModal();
        fetchPlatformPlans();
      } catch (err) {
        alert(`❌ خطأ: ${err.message}`);
      }
    });
  }
}

