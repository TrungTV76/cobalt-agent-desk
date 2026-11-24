/* Controller for Section 1: Agent Control Desk (Cobalt Agent Desk v0.1)
   5 grouping modes, Lazy DOM rendering, Privacy Mask, `/` quick search,
   100% client-side i18n over language-invariant JSON codes, zero inline JS. */

window.AgentDesk = (function () {
  "use strict";

  const IDLE_PREVIEW_LIMIT = 9;
  const GROUP_IDLE_CAP = 12;
  const STALE_IDLE_SEC = 7200;

  const TIER_ORDER = {
    T1_ORCHESTRATOR: 1,
    T2_IMPLEMENTER: 2,
    T3_REVIEWER_GATE: 3,
    T4_SURVEY_RUNNER: 4,
  };

  const VALID_GROUP_BY = ["tier", "model_effort", "function", "hierarchy", "none"];

  function readSavedGroupBy() {
    const raw = localStorage.getItem("agent_desk_groupby") || "tier";
    return VALID_GROUP_BY.includes(raw) ? raw : "tier";
  }

  const desk = {
    scope: localStorage.getItem("agent_desk_scope") || "all",
    windowHours: Number(localStorage.getItem("agent_desk_hours") || "24"),
    viewMode: localStorage.getItem("agent_desk_view") || "grid",
    groupBy: readSavedGroupBy(),
    stateFilter: "ALL",
    modelEffortFilter: "",
    searchQuery: "",
    hideStaleIdle: (localStorage.getItem("agent_desk_hide_stale") ?? "1") === "1",
    expandAllIdle: false,
    groupOpenOverrides: {},
    groupShowAllIdle: {},
    feedAgentFilter: "",
    selectedAgentId: null,
    lastTriggerEl: null,
    detailReqId: 0,
    lastDetailPayload: null,
    data: null,
    sse: null,
    delegatedBound: false,
  };

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtTokens(n) {
    const val = Number(n || 0);
    if (!val || val <= 0) return "";
    if (val >= 1000000) return `${(val / 1000000).toFixed(2)}M tokens`;
    if (val >= 1000) return `~${Math.round(val / 1000)}K tokens`;
    return `${val} tokens`;
  }

  function c3BadgeHtml(ag) {
    const lbl = esc(CobaltI18n.formatC3Label(ag));
    if (ag.room_state === "ERROR") return `<span class="c3 c3-red">${lbl}</span>`;
    if (ag.room_state === "WORKING") return `<span class="c3 c3-blue">${lbl}</span>`;
    if (ag.room_state === "WAITING") return `<span class="c3 c3-amb">${lbl}</span>`;
    if (ag.is_finished) return `<span class="c3 c3-grn">${lbl}</span>`;
    return `<span class="c3 c3-gry">${lbl}</span>`;
  }

  function mePillHtml(ag) {
    const rawKey = ag.model_effort_key || ag.model || "";
    if (!rawKey) return "";
    const label = CobaltI18n.formatModelEffort(rawKey);
    const eff = String(ag.effort || "").toLowerCase();
    const cls = eff === "xhigh" || eff === "max" ? "me-pill me-xhigh" : "me-pill";
    return `<span class="${cls}" title="${esc(CobaltI18n.t("meTooltip"))}">${esc(label)}</span>`;
  }

  function tabBadgeHtml(ag, compact) {
    if (ag.source !== "claude_main") return "";
    if (ag.tab_open) {
      return `<span class="tab-live-pill">${esc(compact ? CobaltI18n.t("tabOpen") : CobaltI18n.t("tabOpenLong"))}</span>`;
    }
    return `<span class="tab-closed-pill">${esc(compact ? CobaltI18n.t("tabClosed") : CobaltI18n.t("tabClosedLong"))}</span>`;
  }

  function displayStatusLine(ag) {
    const raw = ag.status_text || ag.subtitle || "";
    if (raw) {
      return CobaltI18n.maskDetail(raw);
    }
    return CobaltI18n.formatActionTitle(ag.action_code, ag.current_tool);
  }

  function updateScopeDropdown() {
    const sc = document.getElementById("deskScopeSelect");
    if (!sc) return;
    const projects = (desk.data && desk.data.summary && desk.data.summary.projects) || [];
    const curVal = desk.scope;
    const fixedOpts = [
      { v: "all", lbl: CobaltI18n.t("optAll") },
      { v: "claude", lbl: CobaltI18n.t("optClaude") },
      { v: "antigravity", lbl: CobaltI18n.t("optAntigravity") },
    ];
    const projOpts = projects.map((p) => ({
      v: `project:${p}`,
      lbl: `${CobaltI18n.t("optProjPrefix")}${CobaltI18n.maskProject(p)}`,
    }));
    const allOpts = [...fixedOpts, ...projOpts];
    sc.innerHTML = allOpts
      .map((o) => `<option value="${esc(o.v)}">${esc(o.lbl)}</option>`)
      .join("");
    if (allOpts.some((o) => o.v === curVal)) {
      sc.value = curVal;
    } else {
      desk.scope = "all";
      sc.value = "all";
    }
  }

  function getFilteredAgents() {
    if (!desk.data || !Array.isArray(desk.data.agents)) return [];
    const q = desk.searchQuery.trim().toLowerCase();
    return desk.data.agents.filter((ag) => {
      if (desk.stateFilter !== "ALL" && ag.room_state !== desk.stateFilter) return false;
      if (desk.modelEffortFilter && ag.model_effort_key !== desk.modelEffortFilter) return false;
      if (q) {
        const hay = [
          CobaltI18n.formatAgentName(ag),
          ag.name,
          ag.project,
          ag.branch,
          ag.model_effort_key,
          ag.current_tool,
          ag.status_text,
          ag.subtitle,
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function countStates(items) {
    let working = 0,
      waiting = 0,
      error = 0,
      idle = 0;
    for (const a of items) {
      if (a.room_state === "WORKING") working++;
      else if (a.room_state === "WAITING") waiting++;
      else if (a.room_state === "ERROR") error++;
      else idle++;
    }
    return { total: items.length, working, waiting, error, idle, hot: working + waiting + error };
  }

  function isGroupExpanded(grp, counts, forceFirstOpen) {
    if (Object.prototype.hasOwnProperty.call(desk.groupOpenOverrides, grp.key)) {
      return Boolean(desk.groupOpenOverrides[grp.key]);
    }
    if (forceFirstOpen) return true;
    if (counts.hot > 0) return true;
    if (!desk.hideStaleIdle) return true;
    const newestAge = Math.min(...grp.items.map((a) => Number(a.age_sec ?? 999999)));
    return newestAge <= STALE_IDLE_SEC;
  }

  function functionDisplayLabel(fk, sampleAg) {
    if (fk === "claude_main") return CobaltI18n.t("role_claude_main");
    if (fk === "antigravity") return CobaltI18n.t("role_antigravity");
    if (fk.startsWith("skill:")) return `/${fk.slice(6)}${CobaltI18n.t("skillSuffix")}`;
    return (sampleAg && sampleAg.name) || fk;
  }

  function buildGroups(list) {
    if (desk.groupBy === "tier") {
      const buckets = {};
      for (const a of list) {
        const tId = a.tier || "T4_SURVEY_RUNNER";
        if (!buckets[tId]) {
          buckets[tId] = {
            key: `tier:${tId}`,
            order: TIER_ORDER[tId] || 9,
            title: CobaltI18n.t(`tier_${tId}`),
            sub: CobaltI18n.t(`tierShort_${tId}`),
            items: [],
          };
        }
        buckets[tId].items.push(a);
      }
      return Object.values(buckets).sort((x, y) => x.order - y.order);
    }

    if (desk.groupBy === "model_effort") {
      const buckets = {};
      for (const a of list) {
        const mek = a.model_effort_key || "unknown · default";
        if (!buckets[mek]) {
          buckets[mek] = {
            key: `me:${mek}`,
            title: CobaltI18n.formatModelEffort(mek),
            sub: `${a.model_family === "unknown" ? CobaltI18n.t("unknownModel") : a.model_family}`,
            items: [],
          };
        }
        buckets[mek].items.push(a);
      }
      return Object.values(buckets).sort((x, y) => {
        const cx = countStates(x.items);
        const cy = countStates(y.items);
        return cy.hot - cx.hot || y.items.length - x.items.length || x.title.localeCompare(y.title);
      });
    }

    if (desk.groupBy === "function") {
      const buckets = {};
      for (const a of list) {
        const fk = a.function_key || "general";
        if (!buckets[fk]) {
          buckets[fk] = {
            key: `fn:${fk}`,
            title: functionDisplayLabel(fk, a),
            sub: CobaltI18n.t(`tierShort_${a.tier || "T4_SURVEY_RUNNER"}`),
            items: [],
          };
        }
        buckets[fk].items.push(a);
      }
      return Object.values(buckets).sort((x, y) => {
        const cx = countStates(x.items);
        const cy = countStates(y.items);
        return cy.hot - cx.hot || y.items.length - x.items.length || x.title.localeCompare(y.title);
      });
    }

    // Hierarchy: Parent Session -> Branch -> Subagents
    const buckets = {};
    for (const a of list) {
      const pid = a.parent_session_id || a.id;
      if (!buckets[pid]) {
        const pProj = CobaltI18n.maskProject(a.parent_project || a.project || "");
        const pTitle =
          a.source === "antigravity"
            ? a.name
            : `${CobaltI18n.t("sessionPrefix")}${pProj} (${a.parent_sid_short || pid.slice(0, 8)})`;
        buckets[pid] = {
          key: `tree:${pid}`,
          title: pTitle,
          sub: pProj,
          parentAgent: null,
          modelKey: "",
          items: [],
        };
      }
      if (a.spawn_depth === 0) {
        buckets[pid].parentAgent = a;
        buckets[pid].modelKey = CobaltI18n.formatModelEffort(a.model_effort_key);
      }
      buckets[pid].items.push(a);
    }
    return Object.values(buckets).sort((x, y) => {
      const cx = countStates(x.items);
      const cy = countStates(y.items);
      return cy.hot - cx.hot || y.items.length - x.items.length;
    });
  }

  function renderGroupCountsHtml(c) {
    const bits = [];
    if (c.error > 0) bits.push(`<span style="color:var(--c3-red-fg);">△ ${c.error}</span>`);
    if (c.working > 0) bits.push(`<span style="color:var(--c3-blue-fg);">▷ ${c.working}</span>`);
    if (c.waiting > 0) bits.push(`<span style="color:var(--c3-amb-fg);">◷ ${c.waiting}</span>`);
    bits.push(`<span class="muted">(${c.total})</span>`);
    return bits.join("");
  }

  function renderStationCardHtml(ag) {
    const stCls =
      ag.room_state === "WORKING"
        ? "st-working"
        : ag.room_state === "WAITING"
          ? "st-waiting"
          : ag.room_state === "ERROR"
            ? "st-error"
            : ag.is_finished
              ? "st-done"
              : "st-idle";
    const selCls = desk.selectedAgentId === ag.id ? "is-selected" : "";
    const nameStr = CobaltI18n.formatAgentName(ag);
    const projStr = CobaltI18n.maskProject(ag.project);
    const branchStr = CobaltI18n.maskBranch(ag.branch);
    const detailStr = displayStatusLine(ag);
    const ctxStr = fmtTokens(ag.context_tokens);
    const footLeft = branchStr ? `${projStr} · ⑂ ${branchStr}` : projStr;

    return `
      <article class="station-card ${stCls} ${selCls}" tabindex="0" role="button"
               data-action="desk-open-detail" data-agent-id="${esc(ag.id)}">
        <div class="st-top">
          <span class="st-name" title="${esc(nameStr)}">
            ${CobaltSchematic.renderRoleBadgeSvg(ag.role, 14)}
            <span>${esc(nameStr)}</span>
          </span>
          <span class="st-age">${esc(CobaltI18n.formatAge(ag.age_sec))}</span>
        </div>
        <div class="st-badges">
          ${c3BadgeHtml(ag)}
          ${mePillHtml(ag)}
          ${tabBadgeHtml(ag, true)}
        </div>
        <div class="svg-box">${CobaltSchematic.renderStationSvg(ag)}</div>
        <div class="st-detail" title="${esc(detailStr)}">${esc(detailStr)}</div>
        <div class="st-foot">
          <span class="st-foot-left" title="${esc(footLeft)}">${esc(footLeft)}</span>
          ${ctxStr ? `<span class="muted" title="${esc(CobaltI18n.t("ctxTooltip"))}">${esc(ctxStr)}</span>` : ""}
        </div>
      </article>
    `;
  }

  function renderTableWrapperHtml(rowsHtml) {
    return `
      <table class="ledger-table">
        <thead>
          <tr>
            <th>${esc(CobaltI18n.t("thAgent"))}</th>
            <th>${esc(CobaltI18n.t("thTier"))}</th>
            <th>${esc(CobaltI18n.t("thStatus"))}</th>
            <th>${esc(CobaltI18n.t("thModelEffort"))}</th>
            <th>${esc(CobaltI18n.t("thProjectBranch"))}</th>
            <th title="${esc(CobaltI18n.t("ctxTooltip"))}">${esc(CobaltI18n.t("thContext"))}</th>
            <th>${esc(CobaltI18n.t("thUpdated"))}</th>
            <th>${esc(CobaltI18n.t("thLastAction"))}</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  }

  function renderTableRowHtml(ag) {
    const selCls = desk.selectedAgentId === ag.id ? "row-selected" : "";
    const nameStr = CobaltI18n.formatAgentName(ag);
    const projStr = CobaltI18n.maskProject(ag.project);
    const branchStr = CobaltI18n.maskBranch(ag.branch);
    const pb = branchStr ? `${projStr} · ⑂ ${branchStr}` : projStr;
    const ctxStr = fmtTokens(ag.context_tokens) || "—";
    const detailStr = displayStatusLine(ag);

    return `
      <tr class="${selCls}" tabindex="0" data-action="desk-open-detail" data-agent-id="${esc(ag.id)}">
        <td>
          <div style="display:flex;align-items:center;gap:6px;">
            ${CobaltSchematic.renderRoleBadgeSvg(ag.role, 14)}
            <strong>${esc(nameStr)}</strong>
            ${tabBadgeHtml(ag, true)}
          </div>
        </td>
        <td class="mono muted">${esc(CobaltI18n.t(`tierShort_${ag.tier}`))}</td>
        <td>${c3BadgeHtml(ag)}</td>
        <td>${mePillHtml(ag)}</td>
        <td class="mono">${esc(pb)}</td>
        <td class="mono muted" title="${esc(CobaltI18n.t("ctxTooltip"))}">${esc(ctxStr)}</td>
        <td class="mono muted">${esc(CobaltI18n.formatAge(ag.age_sec))}</td>
        <td class="mono muted" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(detailStr)}">${esc(detailStr)}</td>
      </tr>
    `;
  }

  function renderHierarchyBodyHtml(grp, viewMode) {
    const children = grp.items.filter((a) => !grp.parentAgent || a.id !== grp.parentAgent.id);
    const showAll = Boolean(desk.groupShowAllIdle[grp.key]);
    const hotChildren = children.filter((a) => a.room_state !== "IDLE");
    const idleChildren = children.filter((a) => a.room_state === "IDLE");
    let visibleChildren = children;
    let hiddenCount = 0;
    if (!showAll && idleChildren.length > GROUP_IDLE_CAP) {
      visibleChildren = [...hotChildren, ...idleChildren.slice(0, GROUP_IDLE_CAP)];
      hiddenCount = idleChildren.length - GROUP_IDLE_CAP;
    }

    const branchMap = {};
    for (const ch of visibleChildren) {
      const bKey = CobaltI18n.maskBranch(ch.branch) || CobaltI18n.t("generalBranch");
      if (!branchMap[bKey]) branchMap[bKey] = [];
      branchMap[bKey].push(ch);
    }
    const branchGroups = Object.entries(branchMap).map(([key, items]) => ({ key, items }));

    if (viewMode === "table") {
      const rows = [];
      if (grp.parentAgent) rows.push(renderTableRowHtml(grp.parentAgent));
      for (const bg of branchGroups) {
        rows.push(
          `<tr><td colspan="8" style="background:var(--bg-paper);font-family:var(--font-mono);font-size:11.5px;font-weight:700;color:var(--ink-struct);padding:5px 10px;">${esc(CobaltI18n.t("branchGroupPrefix"))}${esc(bg.key)} (${bg.items.length} ${esc(CobaltI18n.t("agentsCountSuffix"))})</td></tr>`
        );
        for (const ch of bg.items) rows.push(renderTableRowHtml(ch));
      }
      const expBtn =
        hiddenCount > 0
          ? `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("showMoreIdleGroup", { n: hiddenCount }))}</button>`
          : showAll && idleChildren.length > GROUP_IDLE_CAP
            ? `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("collapseIdleGroup"))}</button>`
            : "";
      return `<div class="group-body-table">${renderTableWrapperHtml(rows.join(""))}${expBtn}</div>`;
    }

    let html = `<div class="group-body">`;
    if (grp.parentAgent) {
      html += `<div class="hierarchy-parent-wrap"><div class="stations-grid">${renderStationCardHtml(grp.parentAgent)}</div></div>`;
    }
    for (const bg of branchGroups) {
      html += `
        <div class="hierarchy-branch-block">
          <div class="hierarchy-branch-head">
            <span>${esc(CobaltI18n.t("branchGroupPrefix"))}${esc(bg.key)}</span>
            <span class="muted">(${bg.items.length} ${esc(CobaltI18n.t("agentsCountSuffix"))})</span>
          </div>
          <div class="stations-grid">${bg.items.map(renderStationCardHtml).join("")}</div>
        </div>
      `;
    }
    if (hiddenCount > 0) {
      html += `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("showMoreIdleGroup", { n: hiddenCount }))}</button>`;
    } else if (showAll && idleChildren.length > GROUP_IDLE_CAP) {
      html += `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("collapseIdleGroup"))}</button>`;
    }
    html += `</div>`;
    return html;
  }

  function renderGrouped(host, fullList) {
    const groups = buildGroups(fullList);
    const metaCounts = groups.map((g) => countStates(g.items));
    const anyDefaultOpen = groups.some((g, idx) => isGroupExpanded(g, metaCounts[idx], false));

    const blocksHtml = groups
      .map((grp, idx) => {
        const c = metaCounts[idx];
        const expanded = isGroupExpanded(grp, c, !anyDefaultOpen && idx === 0);
        const headCls = [
          "group-head",
          expanded ? "" : "is-collapsed",
          c.error > 0 ? "has-err" : c.hot > 0 ? "has-hot" : "",
        ]
          .filter(Boolean)
          .join(" ");

        const extraBadges = [];
        if (desk.groupBy === "hierarchy" && grp.parentAgent && grp.parentAgent.source === "claude_main") {
          extraBadges.push(tabBadgeHtml(grp.parentAgent, false));
        }
        if (desk.groupBy === "hierarchy" && grp.modelKey) {
          extraBadges.push(`<span class="me-pill">${esc(grp.modelKey)}</span>`);
        }

        let bodyHtml = "";
        // Lazy DOM: collapsed groups render ZERO station cards or SVG schematics
        if (expanded) {
          if (desk.groupBy === "hierarchy") {
            bodyHtml = renderHierarchyBodyHtml(grp, desk.viewMode);
          } else {
            const showAll = Boolean(desk.groupShowAllIdle[grp.key]);
            const hotItems = grp.items.filter((a) => a.room_state !== "IDLE");
            const idleItems = grp.items.filter((a) => a.room_state === "IDLE");
            let visibleItems = grp.items;
            let hiddenIdle = 0;
            if (!showAll && idleItems.length > GROUP_IDLE_CAP) {
              visibleItems = [...hotItems, ...idleItems.slice(0, GROUP_IDLE_CAP)];
              hiddenIdle = idleItems.length - GROUP_IDLE_CAP;
            }
            const expBtn =
              hiddenIdle > 0
                ? `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("showMoreIdleGroup", { n: hiddenIdle }))}</button>`
                : showAll && idleItems.length > GROUP_IDLE_CAP
                  ? `<button type="button" class="idle-expander-bar" data-action="desk-toggle-group-all" data-group-key="${esc(grp.key)}">${esc(CobaltI18n.t("collapseIdleGroup"))}</button>`
                  : "";

            if (desk.viewMode === "table") {
              bodyHtml = `<div class="group-body-table">${renderTableWrapperHtml(visibleItems.map(renderTableRowHtml).join(""))}${expBtn}</div>`;
            } else {
              bodyHtml = `<div class="group-body"><div class="stations-grid">${visibleItems.map(renderStationCardHtml).join("")}</div>${expBtn}</div>`;
            }
          }
        }

        return `
          <div class="group-block">
            <button type="button" class="${headCls}" aria-expanded="${expanded ? "true" : "false"}"
                    data-action="desk-toggle-group" data-group-key="${esc(grp.key)}">
              <span class="group-head-left">
                <span class="group-chevron">${expanded ? "▼" : "▶"}</span>
                <span>${esc(grp.title)}</span>
                ${grp.sub && grp.sub !== grp.title ? `<span class="group-sub">${esc(grp.sub)}</span>` : ""}
                ${extraBadges.join("")}
              </span>
              <span class="group-counts">${renderGroupCountsHtml(c)}</span>
            </button>
            ${bodyHtml}
          </div>
        `;
      })
      .join("");

    host.innerHTML = `<div class="group-stack">${blocksHtml}</div>`;
  }

  function renderFlat(host, fullList) {
    if (desk.viewMode === "table") {
      host.innerHTML = `<div class="card" style="overflow-x:auto;">${renderTableWrapperHtml(fullList.map(renderTableRowHtml).join(""))}</div>`;
      return;
    }

    let visibleList = fullList;
    let hiddenIdleCount = 0;
    if (desk.stateFilter === "ALL") {
      const hotList = fullList.filter((a) => a.room_state !== "IDLE");
      const idleList = fullList.filter((a) => a.room_state === "IDLE");
      if (idleList.length > IDLE_PREVIEW_LIMIT && !desk.expandAllIdle) {
        visibleList = [...hotList, ...idleList.slice(0, IDLE_PREVIEW_LIMIT)];
        hiddenIdleCount = idleList.length - IDLE_PREVIEW_LIMIT;
      }
    }

    const cardsHtml = visibleList.map(renderStationCardHtml).join("");
    let expanderHtml = "";
    if (hiddenIdleCount > 0) {
      expanderHtml = `<button type="button" class="idle-expander-bar" data-action="desk-toggle-idle">${esc(CobaltI18n.t("showMoreIdleFlat", { n: hiddenIdleCount }))}</button>`;
    } else if (
      desk.stateFilter === "ALL" &&
      desk.expandAllIdle &&
      fullList.filter((a) => a.room_state === "IDLE").length > IDLE_PREVIEW_LIMIT
    ) {
      expanderHtml = `<button type="button" class="idle-expander-bar" data-action="desk-toggle-idle">${esc(CobaltI18n.t("collapseIdleFlat"))}</button>`;
    }

    host.innerHTML = `<div class="stations-grid">${cardsHtml}</div>${expanderHtml}`;
  }

  function renderAgents() {
    const host = document.getElementById("deskStationsHost");
    if (!host) return;

    // Preserve keyboard focus across live SSE updates
    let focusAttr = null;
    let focusVal = null;
    const activeEl = document.activeElement;
    if (activeEl instanceof Element && host.contains(activeEl)) {
      if (activeEl.hasAttribute("data-agent-id")) {
        focusAttr = "data-agent-id";
        focusVal = activeEl.getAttribute("data-agent-id");
      } else if (activeEl.hasAttribute("data-group-key")) {
        focusAttr = "data-group-key";
        focusVal = activeEl.getAttribute("data-group-key");
      }
    }

    const fullList = getFilteredAgents();
    if (!fullList.length) {
      const olderCnt = Number((desk.data && desk.data.summary && desk.data.summary.older_session_count) || 0);
      const olderHtml =
        olderCnt > 0 && desk.windowHours < 168
          ? `<div style="margin-top:8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
               <span>${esc(CobaltI18n.t("emptyOlderHint", { n: olderCnt }))}</span>
               <button type="button" class="btn active" data-action="desk-expand-7d">${esc(CobaltI18n.t("btnExpand7d"))}</button>
             </div>`
          : "";
      host.innerHTML = `
        <div class="card">
          <div class="card-body" style="display:flex;flex-direction:column;gap:6px;">
            <strong>${esc(CobaltI18n.t("emptyWindowTitle"))}</strong>
            ${olderHtml}
            <span class="muted" style="font-size:12px;">${esc(CobaltI18n.t("emptyCliHint"))}</span>
          </div>
        </div>
      `;
      return;
    }

    if (desk.groupBy === "none") {
      renderFlat(host, fullList);
    } else {
      renderGrouped(host, fullList);
    }

    if (focusAttr && focusVal) {
      const match = host.querySelector(`[${focusAttr}="${CSS.escape(focusVal)}"]`);
      if (match instanceof HTMLElement) {
        match.focus({ preventScroll: true });
      }
    }
  }

  function renderStateFilterPills() {
    const el = document.getElementById("deskStatePills");
    if (!el || !desk.data) return;
    const s = desk.data.summary || { total: 0, working: 0, waiting: 0, error: 0, idle: 0 };
    const defs = [
      { key: "ALL", label: `${CobaltI18n.t("stAll")} (${s.total})` },
      { key: "WORKING", label: `${CobaltI18n.t("stWorking")} (${s.working})` },
      { key: "WAITING", label: `${CobaltI18n.t("stWaiting")} (${s.waiting})` },
      { key: "ERROR", label: `${CobaltI18n.t("stError")} (${s.error})` },
      { key: "IDLE", label: `${CobaltI18n.t("stIdle")} (${s.idle})` },
    ];
    el.innerHTML = defs
      .map(
        (d) =>
          `<button type="button" class="btn ${desk.stateFilter === d.key ? "active" : ""}" data-action="desk-filter-state" data-state="${esc(d.key)}">${esc(d.label)}</button>`
      )
      .join("");
  }

  function renderModelEffortPills() {
    const el = document.getElementById("deskModelPills");
    if (!el || !desk.data) return;
    const byMe = (desk.data.group_summaries && desk.data.group_summaries.by_model_effort) || [];
    if (!byMe.length) {
      el.innerHTML = `<span class="muted" style="font-size:11.5px;">${esc(CobaltI18n.t("noModelData"))}</span>`;
      return;
    }
    if (desk.modelEffortFilter && !byMe.some((x) => x.key === desk.modelEffortFilter)) {
      desk.modelEffortFilter = "";
    }
    const allBtn = `<button type="button" class="me-filter-btn ${desk.modelEffortFilter === "" ? "active" : ""}" data-action="desk-filter-me" data-me="">${esc(CobaltI18n.t("allModels"))}</button>`;
    const pills = byMe.slice(0, 12).map((item) => {
      const hot = (item.working || 0) + (item.waiting || 0) + (item.error || 0);
      const hotSuffix = hot > 0 ? ` · ▷${hot}` : "";
      const activeCls = desk.modelEffortFilter === item.key ? "active" : "";
      const disp = CobaltI18n.formatModelEffort(item.key);
      return `<button type="button" class="me-filter-btn ${activeCls}" data-action="desk-filter-me" data-me="${esc(item.key)}">${esc(disp)} (${item.total}${hotSuffix})</button>`;
    });
    el.innerHTML = allBtn + pills.join("");
  }

  function renderFeed() {
    const listEl = document.getElementById("deskFeedList");
    const filterInfo = document.getElementById("deskFeedFilterInfo");
    if (!listEl || !desk.data) return;

    let events = desk.data.events || [];
    if (desk.feedAgentFilter) {
      events = events.filter((e) => e.agent_id === desk.feedAgentFilter);
      if (filterInfo) {
        const matchedAg = (desk.data.agents || []).find((a) => a.id === desk.feedAgentFilter);
        const name = matchedAg ? CobaltI18n.formatAgentName(matchedAg) : desk.feedAgentFilter;
        filterInfo.innerHTML = `${esc(CobaltI18n.t("feedFiltering"))} <strong>${esc(name)}</strong> · <button type="button" class="link-btn" data-action="desk-filter-feed" data-agent-id="">${esc(CobaltI18n.t("feedShowAll"))}</button>`;
        filterInfo.classList.remove("hidden");
      }
    } else if (filterInfo) {
      filterInfo.classList.add("hidden");
    }

    if (!events.length) {
      listEl.innerHTML = `<div class="card-body muted">${esc(CobaltI18n.t("feedEmpty"))}</div>`;
      return;
    }

    listEl.innerHTML = events
      .map((ev) => {
        const cls = ev.is_error ? "feed-item is-error" : "feed-item";
        const evName = CobaltI18n.formatAgentName({
          name: ev.agent_name,
          name_kind: ev.name_kind,
        });
        const evTitle = CobaltI18n.formatActionTitle(ev.action_code, ev.tool);
        const evDetail = CobaltI18n.maskDetail(ev.detail);
        return `
          <div class="${cls}">
            <div class="feed-meta">
              <button type="button" class="link-btn mono" style="font-size:11px;text-decoration:none;font-weight:700;color:var(--ink-struct);"
                      data-action="desk-filter-feed" data-agent-id="${esc(ev.agent_id)}">
                [${esc(ev.role_short)}] ${esc(evName)}
              </button>
              <span class="mono muted">${esc(CobaltI18n.formatClock(ev.ts))}</span>
            </div>
            <div class="feed-title">${esc(evTitle)}</div>
            ${evDetail ? `<div class="feed-detail" title="${esc(evDetail)}">${esc(evDetail)}</div>` : ""}
          </div>
        `;
      })
      .join("");
  }

  function renderDrawerFromPayload(payload) {
    if (!payload || !payload.agent) return;
    const titleEl = document.getElementById("drawerTitle");
    const metaEl = document.getElementById("drawerMeta");
    const bodyEl = document.getElementById("drawerBody");
    const ag = payload.agent;
    const tl = payload.timeline || [];

    titleEl.textContent = CobaltI18n.formatAgentName(ag);
    const ctxStr = fmtTokens(ag.context_tokens);
    const diagBits = [];
    diagBits.push(
      `<span><strong>${esc(CobaltI18n.t("drawerTier"))}</strong> ${esc(CobaltI18n.t(`tier_${ag.tier}`))}</span>`
    );
    if (ag.source === "claude_subagent" && ag.parent_project) {
      const pDisp = `${CobaltI18n.t("sessionPrefix")}${CobaltI18n.maskProject(ag.parent_project)} (${ag.parent_sid_short || ""})`;
      diagBits.push(`<span><strong>${esc(CobaltI18n.t("drawerParent"))}</strong> ${esc(pDisp)}</span>`);
    }
    if (ctxStr) {
      diagBits.push(
        `<span title="${esc(CobaltI18n.t("ctxTooltip"))}"><strong>${esc(CobaltI18n.t("drawerContext"))}</strong> ${esc(ctxStr)}</span>`
      );
    }
    if (ag.parent_effort_model && ag.parent_effort_model !== ag.model) {
      diagBits.push(
        `<span class="muted"><strong>${esc(CobaltI18n.t("drawerParentModel"))}</strong> ${esc(ag.parent_effort_model)}</span>`
      );
    }

    const projStr = CobaltI18n.maskProject(ag.project);
    const branchStr = CobaltI18n.maskBranch(ag.branch);

    metaEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
        ${c3BadgeHtml(ag)}
        ${mePillHtml(ag)}
        ${tabBadgeHtml(ag, false)}
      </div>
      <div class="mono" style="font-size:11.5px;color:var(--ink-struct);margin-bottom:6px;">
        ${esc(CobaltI18n.t("drawerWorkspace"))} <strong>${esc(projStr)}</strong>${branchStr ? ` · ⑂ ${esc(branchStr)}` : ""}
      </div>
      <div style="display:flex;flex-direction:column;gap:3px;font-size:11.5px;margin-bottom:8px;padding:6px 8px;background:var(--bg-paper);border:1px solid var(--border-soft);">
        ${diagBits.join("")}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button type="button" class="btn" data-action="desk-filter-feed" data-agent-id="${esc(ag.id)}" data-from-drawer="1">${esc(CobaltI18n.t("drawerFilterFeed"))}</button>
      </div>
    `;

    if (!tl.length) {
      bodyEl.innerHTML = `<div class="muted">${esc(CobaltI18n.t("drawerNoSteps"))}</div>`;
      return;
    }

    bodyEl.innerHTML = tl
      .map((step) => {
        const sTitle = CobaltI18n.formatActionTitle(step.action_code, step.tool);
        const sDetail = CobaltI18n.maskDetail(step.detail);
        return `
          <div class="card" style="border-left:3px solid ${step.is_error ? "var(--c3-red-fg)" : "var(--border)"};">
            <div class="card-body" style="padding:8px 10px;">
              <div style="display:flex;justify-content:space-between;gap:8px;font-size:11.5px;">
                <strong>${esc(sTitle)}</strong>
                <span class="mono muted">${esc(CobaltI18n.formatClock(step.ts))}</span>
              </div>
              ${sDetail ? `<div class="mono" style="font-size:11px;margin-top:4px;word-break:break-word;color:${step.is_error ? "var(--c3-red-fg)" : "var(--ink-muted)"};">${esc(sDetail)}</div>` : ""}
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function openDetail(agentId) {
    if (!agentId) return;
    const reqId = ++desk.detailReqId;
    if (document.activeElement instanceof HTMLElement) {
      desk.lastTriggerEl = document.activeElement;
    }
    desk.selectedAgentId = agentId;
    desk.lastDetailPayload = null;
    renderAgents();

    const backdrop = document.getElementById("agentDrawerBackdrop");
    const bodyEl = document.getElementById("drawerBody");
    backdrop.classList.remove("hidden");
    const closeBtn = document.getElementById("btnDrawerClose");
    if (closeBtn) closeBtn.focus();
    bodyEl.innerHTML = `<div class="muted">${esc(CobaltI18n.t("drawerLoading"))}</div>`;

    try {
      const res = await fetch(`/api/agent-detail?id=${encodeURIComponent(agentId)}`);
      const payload = await res.json();
      if (reqId !== desk.detailReqId) return;
      if (!res.ok) {
        bodyEl.innerHTML = `<div class="c3 c3-red">${esc(payload.error || "Error")}</div>`;
        return;
      }
      desk.lastDetailPayload = payload;
      renderDrawerFromPayload(payload);
    } catch (_) {
      if (reqId !== desk.detailReqId) return;
      bodyEl.innerHTML = `<div class="c3 c3-red">Connection error</div>`;
    }
  }

  function closeDetail() {
    const el = document.getElementById("agentDrawerBackdrop");
    if (el) el.classList.add("hidden");
    desk.lastDetailPayload = null;
    if (desk.lastTriggerEl && document.contains(desk.lastTriggerEl)) {
      desk.lastTriggerEl.focus();
    }
    desk.lastTriggerEl = null;
  }

  function renderAll() {
    if (!desk.data) return;
    const sum = desk.data.summary || {};
    const railCnt = document.getElementById("railCntAgents");
    if (railCnt) {
      const hot = (sum.working || 0) + (sum.waiting || 0) + (sum.error || 0);
      railCnt.textContent = hot > 0 ? `${hot}/${sum.total || 0}` : String(sum.total || 0);
    }
    const demoBadge = document.getElementById("demoBadge");
    if (demoBadge) {
      demoBadge.classList.toggle("hidden", !desk.data.demo);
    }
    const syncEl = document.getElementById("lastSync");
    if (syncEl && desk.data.server_time) {
      syncEl.textContent = CobaltI18n.formatClock(desk.data.server_time);
    }
    updateScopeDropdown();
    renderStateFilterPills();
    renderModelEffortPills();
    renderAgents();
    renderFeed();
    if (desk.lastDetailPayload) {
      renderDrawerFromPayload(desk.lastDetailPayload);
    }
  }

  function setViewMode(mode) {
    desk.viewMode = mode === "table" ? "table" : "grid";
    localStorage.setItem("agent_desk_view", desk.viewMode);
    const bGrid = document.getElementById("btnDeskGrid");
    const bTable = document.getElementById("btnDeskTable");
    if (bGrid) bGrid.classList.toggle("active", desk.viewMode === "grid");
    if (bTable) bTable.classList.toggle("active", desk.viewMode === "table");
    renderAgents();
  }

  function setGroupBy(mode) {
    if (!VALID_GROUP_BY.includes(mode)) return;
    desk.groupBy = mode;
    localStorage.setItem("agent_desk_groupby", mode);
    desk.groupOpenOverrides = {};
    desk.groupShowAllIdle = {};
    const grp = document.getElementById("deskGroupSelect");
    if (grp && grp.value !== mode) grp.value = mode;
    renderAgents();
  }

  function setStateFilter(st) {
    desk.stateFilter = desk.stateFilter === st && st !== "ALL" ? "ALL" : st;
    renderStateFilterPills();
    renderAgents();
  }

  function handleDelegatedAction(actionEl, ev) {
    const act = actionEl.getAttribute("data-action");
    if (!act) return;

    if (act === "desk-filter-state") {
      setStateFilter(actionEl.getAttribute("data-state") || "ALL");
      return;
    }
    if (act === "desk-filter-me") {
      const me = actionEl.getAttribute("data-me") || "";
      desk.modelEffortFilter = desk.modelEffortFilter === me ? "" : me;
      renderModelEffortPills();
      renderAgents();
      return;
    }
    if (act === "desk-toggle-group") {
      const gKey = actionEl.getAttribute("data-group-key") || "";
      const curOpen = actionEl.getAttribute("aria-expanded") === "true";
      desk.groupOpenOverrides[gKey] = !curOpen;
      renderAgents();
      return;
    }
    if (act === "desk-toggle-group-all") {
      const gKey = actionEl.getAttribute("data-group-key") || "";
      desk.groupShowAllIdle[gKey] = !desk.groupShowAllIdle[gKey];
      renderAgents();
      return;
    }
    if (act === "desk-toggle-idle") {
      desk.expandAllIdle = !desk.expandAllIdle;
      renderAgents();
      return;
    }
    if (act === "desk-expand-7d") {
      desk.windowHours = 168;
      localStorage.setItem("agent_desk_hours", "168");
      const hr = document.getElementById("deskHoursSelect");
      if (hr) hr.value = "168";
      refresh(true);
      return;
    }
    if (act === "desk-open-detail") {
      openDetail(actionEl.getAttribute("data-agent-id") || "");
      return;
    }
    if (act === "desk-view-mode") {
      setViewMode(actionEl.getAttribute("data-view") || "grid");
      return;
    }
    if (act === "desk-close-drawer") {
      closeDetail();
      return;
    }
    if (act === "desk-filter-feed") {
      ev.stopPropagation();
      const aid = actionEl.getAttribute("data-agent-id") || "";
      const fromDrawer = actionEl.getAttribute("data-from-drawer") === "1";
      if (fromDrawer) {
        desk.feedAgentFilter = aid;
        closeDetail();
        renderFeed();
      } else {
        desk.feedAgentFilter = desk.feedAgentFilter === aid ? "" : aid;
        renderFeed();
      }
    }
  }

  function bindDelegation() {
    if (desk.delegatedBound) return;
    desk.delegatedBound = true;

    document.addEventListener("click", (ev) => {
      const backdrop = document.getElementById("agentDrawerBackdrop");
      if (ev.target === backdrop) {
        closeDetail();
        return;
      }
      const target =
        ev.target instanceof Element ? ev.target.closest("[data-action^='desk-']") : null;
      if (target) handleDelegatedAction(target, ev);
    });

    document.addEventListener("keydown", (ev) => {
      const backdrop = document.getElementById("agentDrawerBackdrop");
      const drawerOpen = backdrop && !backdrop.classList.contains("hidden");
      const searchInput = document.getElementById("deskSearchInput");

      if (ev.key === "/" && !drawerOpen && document.activeElement !== searchInput) {
        const tag = (document.activeElement && document.activeElement.tagName) || "";
        if (!["INPUT", "SELECT", "TEXTAREA"].includes(tag)) {
          ev.preventDefault();
          if (searchInput) searchInput.focus();
          return;
        }
      }

      if (ev.key === "Escape") {
        if (drawerOpen) {
          ev.preventDefault();
          closeDetail();
          return;
        }
        if (searchInput && document.activeElement === searchInput && searchInput.value) {
          searchInput.value = "";
          desk.searchQuery = "";
          renderAgents();
          return;
        }
      }

      if ((ev.key === "Enter" || ev.key === " ") && !drawerOpen) {
        const target = ev.target instanceof Element ? ev.target : null;
        if (
          target &&
          target.hasAttribute("data-action") &&
          (target.getAttribute("data-action") || "").startsWith("desk-") &&
          target.tagName !== "BUTTON"
        ) {
          ev.preventDefault();
          handleDelegatedAction(target, ev);
        }
      }
    });
  }

  function initControls() {
    bindDelegation();
    const sc = document.getElementById("deskScopeSelect");
    const hr = document.getElementById("deskHoursSelect");
    const grp = document.getElementById("deskGroupSelect");
    const chkStale = document.getElementById("chkHideStaleGroups");
    const searchEl = document.getElementById("deskSearchInput");

    if (sc) {
      sc.addEventListener("change", (e) => {
        desk.scope = e.target.value;
        localStorage.setItem("agent_desk_scope", desk.scope);
        desk.feedAgentFilter = "";
        desk.modelEffortFilter = "";
        desk.groupOpenOverrides = {};
        refresh(true);
      });
    }
    if (hr) {
      hr.value = String(desk.windowHours);
      hr.addEventListener("change", (e) => {
        desk.windowHours = Number(e.target.value);
        localStorage.setItem("agent_desk_hours", String(desk.windowHours));
        desk.groupOpenOverrides = {};
        refresh(true);
      });
    }
    if (grp) {
      grp.value = desk.groupBy;
      grp.addEventListener("change", (e) => setGroupBy(e.target.value));
    }
    if (chkStale) {
      chkStale.checked = desk.hideStaleIdle;
      chkStale.addEventListener("change", (e) => {
        desk.hideStaleIdle = Boolean(e.target.checked);
        localStorage.setItem("agent_desk_hide_stale", desk.hideStaleIdle ? "1" : "0");
        desk.groupOpenOverrides = {};
        renderAgents();
      });
    }
    if (searchEl) {
      searchEl.addEventListener("input", (e) => {
        desk.searchQuery = e.target.value || "";
        renderAgents();
      });
    }
    setViewMode(desk.viewMode);
  }

  function connectSse() {
    if (desk.sse) {
      desk.sse.close();
      desk.sse = null;
    }
    const url = `/api/stream/agents?scope=${encodeURIComponent(desk.scope)}&window_hours=${desk.windowHours}`;
    const es = new EventSource(url);
    desk.sse = es;
    es.onopen = () => {
      if (window.DeskApp) window.DeskApp.setConnStatus(true);
    };
    es.onerror = () => {
      if (window.DeskApp) window.DeskApp.setConnStatus(false);
    };
    es.addEventListener("agents_update", (ev) => {
      try {
        desk.data = JSON.parse(ev.data);
        if (window.DeskApp) window.DeskApp.setConnStatus(true);
        renderAll();
      } catch (_) {}
    });
  }

  async function refresh(reconnect = false) {
    const url = `/api/agents?scope=${encodeURIComponent(desk.scope)}&window_hours=${desk.windowHours}`;
    try {
      const res = await fetch(url);
      if (!res.ok) return;
      desk.data = await res.json();
      if (window.DeskApp) window.DeskApp.setConnStatus(true);
      renderAll();
      if (reconnect) connectSse();
    } catch (_) {
      if (window.DeskApp) window.DeskApp.setConnStatus(false);
    }
  }

  function start(connectImmediately = true) {
    initControls();
    refresh(Boolean(connectImmediately));
    setInterval(() => {
      if (!document.hidden && (!desk.sse || desk.sse.readyState !== EventSource.OPEN)) {
        refresh(false);
      }
    }, 12000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && (!desk.sse || desk.sse.readyState !== EventSource.OPEN)) {
        refresh(false);
      }
    });
  }

  return {
    start,
    refresh,
    renderAll,
    closeDetail,
  };
})();
