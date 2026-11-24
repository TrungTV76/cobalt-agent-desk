/* Top-level shell controller for Cobalt Agent Desk (Theme, EN|VI, Privacy Mask, Worktrees)
   External JS only — satisfies strict Content-Security-Policy: script-src 'self'. */

window.DeskApp = (function () {
  "use strict";

  const st = {
    section: "agents",
    connected: true,
    worktreesPayload: null,
  };

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function showToast(msg) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => el.classList.add("hidden"), 2400);
  }

  function setConnStatus(online) {
    st.connected = Boolean(online);
    const badge = document.getElementById("connBadge");
    if (!badge) return;
    badge.className = st.connected ? "c3 c3-blue" : "c3 c3-red";
    badge.textContent = st.connected
      ? CobaltI18n.t("liveBadge")
      : CobaltI18n.t("offlineBadge");
  }

  function applyStaticTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const k = el.getAttribute("data-i18n");
      if (k) el.textContent = CobaltI18n.t(k);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const k = el.getAttribute("data-i18n-placeholder");
      if (k) el.setAttribute("placeholder", CobaltI18n.t(k));
    });

    const curTheme = document.documentElement.getAttribute("data-theme") || "light";
    const btnTheme = document.getElementById("btnTheme");
    if (btnTheme) {
      btnTheme.textContent =
        curTheme === "dark" ? CobaltI18n.t("themeLight") : CobaltI18n.t("themeDark");
    }

    const btnMask = document.getElementById("btnPrivacyMask");
    if (btnMask) {
      const active = CobaltI18n.isPrivacyMask();
      btnMask.textContent = active
        ? CobaltI18n.t("privacyMaskOn")
        : CobaltI18n.t("privacyMaskBtn");
      btnMask.classList.toggle("mask-active", active);
    }

    const lang = CobaltI18n.getLang();
    const bEn = document.getElementById("btnLangEn");
    const bVi = document.getElementById("btnLangVi");
    if (bEn) bEn.classList.toggle("active", lang === "en");
    if (bVi) bVi.classList.toggle("active", lang === "vi");

    const hostPill = document.getElementById("hostPill");
    if (hostPill) {
      const host = window.location.host || "127.0.0.1:18780";
      hostPill.textContent = `${CobaltI18n.t("readonlyPrefix")} · ${host}`;
    }

    setConnStatus(st.connected);
  }

  function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("agent_desk_theme", next);
    applyStaticTranslations();
  }

  function switchLang(lang) {
    CobaltI18n.setLang(lang);
    applyStaticTranslations();
    AgentDesk.renderAll();
    renderWorktrees();
  }

  function togglePrivacyMask() {
    CobaltI18n.togglePrivacyMask();
    applyStaticTranslations();
    AgentDesk.renderAll();
    renderWorktrees();
  }

  function switchSection(sec) {
    const target = sec === "worktrees" ? "worktrees" : "agents";
    st.section = target;
    localStorage.setItem("agent_desk_section", target);
    document.getElementById("sec-agents").classList.toggle("hidden", target !== "agents");
    document.getElementById("sec-worktrees").classList.toggle("hidden", target !== "worktrees");
    document.getElementById("nav-agents").classList.toggle("active", target === "agents");
    document.getElementById("nav-worktrees").classList.toggle("active", target === "worktrees");
  }

  function formatWorktreeBadge(wt) {
    if (wt.state === "MAIN") {
      return `<span class="c3 c3-grn">${esc(CobaltI18n.t("wtState_MAIN"))}</span>`;
    }
    if (wt.state === "CODING") {
      const extra =
        wt.ahead > 0 ? CobaltI18n.t("wtAheadExtra", { ahead: wt.ahead }) : "";
      const lbl = CobaltI18n.t("wtState_CODING", { dirty: wt.dirty_count, extra });
      return `<span class="c3 c3-blue">${esc(lbl)}</span>`;
    }
    if (wt.state === "UNMERGED") {
      return `<span class="c3 c3-amb">${esc(CobaltI18n.t("wtState_UNMERGED", { ahead: wt.ahead }))}</span>`;
    }
    return `<span class="c3 c3-gry">${esc(CobaltI18n.t("wtState_MERGED"))}</span>`;
  }

  function renderWorktrees() {
    const host = document.getElementById("worktreesTableHost");
    const navBtn = document.getElementById("nav-worktrees");
    const cntEl = document.getElementById("railCntWorktrees");
    if (!host || !st.worktreesPayload) return;

    const enabled = Boolean(st.worktreesPayload.enabled);
    const list = st.worktreesPayload.worktrees || [];
    if (navBtn) {
      navBtn.classList.toggle("hidden", !enabled);
      if (!enabled && st.section === "worktrees") {
        switchSection("agents");
      }
    }
    if (cntEl) cntEl.textContent = String(list.length);

    if (!enabled) {
      host.innerHTML = `<div class="card-body muted">${esc(CobaltI18n.t("wtDisabled"))}</div>`;
      return;
    }
    if (!list.length) {
      host.innerHTML = `<div class="card-body muted">${esc(CobaltI18n.t("wtEmpty"))}</div>`;
      return;
    }

    const rowsHtml = list
      .map((wt) => {
        const wtName = CobaltI18n.maskProject(wt.name);
        const branch = CobaltI18n.maskBranch(wt.branch);
        const subj = CobaltI18n.maskDetail(wt.subject || "");
        const ab = `+${wt.ahead || 0} / -${wt.behind || 0}`;
        return `
          <tr>
            <td class="mono"><strong>${esc(wtName)}</strong></td>
            <td class="mono">⑂ ${esc(branch)}</td>
            <td>${formatWorktreeBadge(wt)}</td>
            <td class="mono muted">${esc(ab)}</td>
            <td class="mono muted">${esc(wt.sha || "")} · ${esc(subj)} ${wt.commit_rel ? `(${esc(wt.commit_rel)})` : ""}</td>
          </tr>
        `;
      })
      .join("");

    host.innerHTML = `
      <table class="ledger-table">
        <thead>
          <tr>
            <th>${esc(CobaltI18n.t("wtThName"))}</th>
            <th>${esc(CobaltI18n.t("wtThBranch"))}</th>
            <th>${esc(CobaltI18n.t("wtThState"))}</th>
            <th>${esc(CobaltI18n.t("wtThAheadBehind"))}</th>
            <th>${esc(CobaltI18n.t("wtThCommit"))}</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  async function loadWorktrees(force = false) {
    try {
      const res = await fetch(`/api/worktrees?force=${force ? "1" : "0"}`);
      if (!res.ok) return;
      st.worktreesPayload = await res.json();
      renderWorktrees();
    } catch (_) {}
  }

  async function manualRefresh() {
    await Promise.all([AgentDesk.refresh(false), loadWorktrees(true)]);
    showToast(CobaltI18n.t("toastRefreshed"));
  }

  function bindAppEvents() {
    document.addEventListener("click", (ev) => {
      const el =
        ev.target instanceof Element ? ev.target.closest("[data-action^='app-']") : null;
      if (!el) return;
      const act = el.getAttribute("data-action");
      if (act === "app-switch-section") {
        switchSection(el.getAttribute("data-sec") || "agents");
      } else if (act === "app-toggle-theme") {
        toggleTheme();
      } else if (act === "app-set-lang") {
        switchLang(el.getAttribute("data-lang") || "en");
      } else if (act === "app-toggle-privacy") {
        togglePrivacyMask();
      } else if (act === "app-refresh") {
        manualRefresh();
      } else if (act === "app-rescan-worktrees") {
        loadWorktrees(true);
      }
    });
  }

  async function init() {
    const savedTheme = localStorage.getItem("agent_desk_theme") || "light";
    document.documentElement.setAttribute("data-theme", savedTheme);
    document.documentElement.setAttribute("lang", CobaltI18n.getLang());

    bindAppEvents();
    applyStaticTranslations();

    const params = new URLSearchParams(window.location.search);
    const rawSec =
      params.get("section") || localStorage.getItem("agent_desk_section") || "agents";
    switchSection(rawSec === "worktrees" ? "worktrees" : "agents");

    AgentDesk.start(true);
    await loadWorktrees(false);

    setInterval(() => {
      if (!document.hidden && st.worktreesPayload && st.worktreesPayload.enabled) {
        loadWorktrees(false);
      }
    }, 12000);
  }

  init();

  return {
    setConnStatus,
    loadWorktrees,
  };
})();
