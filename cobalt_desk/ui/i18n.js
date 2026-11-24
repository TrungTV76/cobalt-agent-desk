/* Bilingual dictionary (EN / VI) + Privacy Mask helpers for Cobalt Agent Desk */

window.CobaltI18n = (function () {
  "use strict";

  const DICT = {
    en: {
      locale: "en-US",
      brandTitle: "Cobalt Agent Desk",
      liveBadge: "▷ LIVE",
      offlineBadge: "△ RECONNECTING",
      demoBadge: "DEMO MODE",
      privacyMaskBtn: "Privacy Mask",
      privacyMaskOn: "Mask: ON",
      refreshBtn: "↻ Refresh",
      themeDark: "Dark Mode",
      themeLight: "Cobalt Cream",
      readonlyPrefix: "Read-only",

      navAgents: "Agent Desk",
      navWorktrees: "Git Worktrees",
      railZeroDeps: "Zero dependencies · Python stdlib",
      railSafe: "No git locks · Secret redaction ON",

      heroTitle: "Agent Control Desk · Real-Time Multi-Session Monitor",
      heroSub:
        "Ground-truth Model & Effort from api-request (Claude Code, Subagents, Skills, Antigravity), 4 operational tiers, live PID tracking, and automatic secret redaction.",

      lblScope: "Scope:",
      optAll: "All Projects",
      optClaude: "Claude Code & Subagents",
      optAntigravity: "Antigravity",
      optProjPrefix: "Project: ",

      lblWindow: "Window:",
      win2h: "Last 2 hours",
      win24h: "Last 24 hours",
      win72h: "Last 3 days",
      win168h: "Last 7 days",

      lblGroup: "Group by:",
      grpTier: "Role Tier (4 Tiers)",
      grpME: "Model & Effort",
      grpFunc: "Agent Function",
      grpTree: "Session Tree → Subagents",
      grpFlat: "Flat (Ungrouped)",

      searchPlaceholder: "Filter agents, branch, tool... (/)",
      btnGrid: "⊞ Grid",
      btnTable: "☰ Table",
      chkHideStale: "Collapse idle groups > 2h",

      stAll: "All",
      stWorking: "▷ Running",
      stWaiting: "◷ Waiting",
      stError: "△ Error",
      stIdle: "○ Idle / Done",
      allModels: "All Models",
      noModelData: "No Model · Effort data in window",
      unknownModel: "Unknown",

      tier_T1_ORCHESTRATOR: "Tier 1 · Orchestrator & Main Sessions",
      tierShort_T1_ORCHESTRATOR: "T1 · Orchestrator",
      tier_T2_IMPLEMENTER: "Tier 2 · Implementation & Sub-Plans",
      tierShort_T2_IMPLEMENTER: "T2 · Implementer",
      tier_T3_REVIEWER_GATE: "Tier 3 · Independent Review & Gates",
      tierShort_T3_REVIEWER_GATE: "T3 · Review & Gate",
      tier_T4_SURVEY_RUNNER: "Tier 4 · Survey & Background",
      tierShort_T4_SURVEY_RUNNER: "T4 · Survey & Bg",

      role_claude_main: "Main Session",
      role_implementer: "Implementer",
      role_security: "Security Review",
      role_database: "Database Review",
      role_python: "Python Review",
      role_typescript: "TypeScript / Web",
      role_verifier: "Independent Verifier",
      role_skill_verify: "Skill Gate",
      role_planner: "Architect / Planner",
      role_explore: "Explorer",
      role_surveyor: "Fast Surveyor",
      role_general: "Subagent",
      role_antigravity: "Antigravity",

      sessionPrefix: "Session · ",
      skillSuffix: " (Skill)",
      tabOpen: "● Open",
      tabOpenLong: "● Tab open",
      tabClosed: "○ Closed",
      tabClosedLong: "○ Tab closed",

      c3_tool_error: "△ Tool error",
      c3_step_error: "△ Step error",
      c3_waiting_long_cmd: "◷ Waiting",
      c3_running_tool: "▷ Running",
      c3_running_thinking: "▷ Thinking",
      c3_done: "✓ Done",
      c3_idle: "○ Idle",

      act_run_command: "Run command",
      act_write_file: "Write file",
      act_edit_file: "Edit file",
      act_read_file: "Read file",
      act_search: "Search",
      act_spawn_agent: "Spawn subagent",
      act_todo_write: "Update checklist",
      act_call_tool: "Call tool",
      act_reply: "Summary / Reply",
      act_user_prompt: "New user prompt",
      act_thinking: "Analyzing request",
      act_tool_error: "Tool returned error",
      act_ready: "Ready",

      justNow: "just now",
      secAgo: "{n}s ago",
      minAgo: "{n}m ago",
      hrAgo: "{h}h ago",
      hrMinAgo: "{h}h {m}m ago",

      ctxTooltip: "Last-turn context window fill (input + cache_creation + cache_read), not cumulative session spend.",
      meTooltip: "Ground-truth Model & Effort extracted from api-request",
      maskedDetail: "[Hidden by Privacy Mask]",

      branchGroupPrefix: "↳ Branch: ",
      generalBranch: "main / general",
      agentsCountSuffix: "agents",
      showMoreIdleGroup: "+ Show {n} more idle / finished agents in this group",
      collapseIdleGroup: "▲ Collapse extra idle agents",
      showMoreIdleFlat: "+ Show {n} older idle / finished stations",
      collapseIdleFlat: "▲ Collapse older idle stations",

      thAgent: "Agent",
      thTier: "Tier",
      thStatus: "Status",
      thModelEffort: "Model · Effort",
      thProjectBranch: "Project · Branch",
      thContext: "Context",
      thUpdated: "Updated",
      thLastAction: "Last Action",

      emptyWindowTitle: "No active or recent agent sessions matched the current filter.",
      emptyOlderHint: "Found {n} older session(s) outside the current time window.",
      btnExpand7d: "Expand window to 7 days",
      emptyCliHint:
        "Tip: Run Claude Code or Antigravity locally, pass --claude-dir for WSL2, or launch with --demo to explore sample data.",

      feedTitle: "Live Event Stream",
      feedFiltering: "Filtering:",
      feedShowAll: "Show all",
      feedEmpty: "No events recorded in this time window.",

      drawerClose: "× Close (Esc)",
      drawerLoading: "Loading recent 30 steps...",
      drawerTier: "Operational tier:",
      drawerParent: "Parent session:",
      drawerContext: "Last-turn context:",
      drawerParentModel: "Parent session model (pickedEffortModel):",
      drawerFilterFeed: "Filter event stream",
      drawerNoSteps: "No recent tool invocations recorded.",
      drawerWorkspace: "Workspace:",

      wtTitle: "Git Worktrees Radar",
      wtSub:
        "Inspects parallel agent worktrees read-only via git --no-optional-locks (never creates index.lock).",
      wtRescan: "↻ Rescan Git",
      wtDisabled:
        "Git Worktrees Radar is optional. Start the server with --repo /path/to/git/repo (or --demo) to inspect parallel worktrees.",
      wtEmpty: "No git worktrees returned for the configured repository.",
      wtThName: "Worktree",
      wtThBranch: "Branch",
      wtThState: "Status",
      wtThAheadBehind: "Ahead / Behind",
      wtThCommit: "Latest Commit",
      wtState_MAIN: "DEFAULT BRANCH",
      wtState_CODING: "CODING ({dirty} files{extra})",
      wtState_UNMERGED: "UNMERGED (+{ahead})",
      wtState_MERGED: "MERGED",
      wtAheadExtra: " · +{ahead} ahead",

      toastRefreshed: "Refreshed all live telemetry",
    },

    vi: {
      locale: "vi-VN",
      brandTitle: "Cobalt Agent Desk",
      liveBadge: "▷ LIVE",
      offlineBadge: "△ ĐANG NỐI LẠI",
      demoBadge: "CHẾ ĐỘ DEMO",
      privacyMaskBtn: "Che Riêng Tư",
      privacyMaskOn: "Đang che tên",
      refreshBtn: "↻ Làm mới",
      themeDark: "Chế độ Tối",
      themeLight: "Nền Kem Cobalt",
      readonlyPrefix: "Chỉ đọc",

      navAgents: "Bàn Agent",
      navWorktrees: "Đa Làn Git",
      railZeroDeps: "0 thư viện ngoài · Python stdlib",
      railSafe: "Không khóa Git · Tự che bí mật",

      heroTitle: "Bàn Điều Hành Agent · Đa Phiên Thời Gian Thực",
      heroSub:
        "Hiển thị đúng Model & Effort thực từ api-request (Claude Code, Subagents, Skills, Antigravity), phân 4 tầng vai trò, kiểm tra PID sống và tự che mật khẩu/token.",

      lblScope: "Phạm vi:",
      optAll: "Tất cả dự án",
      optClaude: "Chỉ Claude Code & Subagents",
      optAntigravity: "Chỉ Antigravity",
      optProjPrefix: "Dự án: ",

      lblWindow: "Khung giờ:",
      win2h: "2 giờ gần đây",
      win24h: "24 giờ gần đây",
      win72h: "3 ngày gần đây",
      win168h: "7 ngày gần đây",

      lblGroup: "Gom nhóm:",
      grpTier: "Tầng vai trò (4 tầng)",
      grpME: "Model & Effort",
      grpFunc: "Chức năng xử lý",
      grpTree: "Cây Phiên chính → Subagents",
      grpFlat: "Phẳng (không gom)",

      searchPlaceholder: "Lọc nhanh agent, nhánh, công cụ... (/)",
      btnGrid: "⊞ Lưới trạm",
      btnTable: "☰ Bảng",
      chkHideStale: "Thu gọn nhóm rảnh > 2g",

      stAll: "Tất cả",
      stWorking: "▷ Đang chạy",
      stWaiting: "◷ Đang chờ",
      stError: "△ Lỗi",
      stIdle: "○ Rảnh / Xong",
      allModels: "Tất cả Model",
      noModelData: "Chưa có dữ liệu Model · Effort",
      unknownModel: "Chưa rõ",

      tier_T1_ORCHESTRATOR: "Tầng 1 · Điều phối & Phiên chính",
      tierShort_T1_ORCHESTRATOR: "T1 · Điều phối",
      tier_T2_IMPLEMENTER: "Tầng 2 · Thực thi & Plan phụ",
      tierShort_T2_IMPLEMENTER: "T2 · Thực thi",
      tier_T3_REVIEWER_GATE: "Tầng 3 · Soát độc lập & Cổng kiểm",
      tierShort_T3_REVIEWER_GATE: "T3 · Soát & Cổng",
      tier_T4_SURVEY_RUNNER: "Tầng 4 · Khảo sát & Tác vụ nền",
      tierShort_T4_SURVEY_RUNNER: "T4 · Khảo sát",

      role_claude_main: "Phiên chính",
      role_implementer: "Thực thi mã",
      role_security: "Soát bảo mật",
      role_database: "Soát CSDL",
      role_python: "Soát Python",
      role_typescript: "Soát TS / Web",
      role_verifier: "Kiểm chứng độc lập",
      role_skill_verify: "Cổng kỹ năng",
      role_planner: "Kiến trúc / Plan",
      role_explore: "Khảo sát",
      role_surveyor: "Khảo sát nhanh",
      role_general: "Tác tử phụ",
      role_antigravity: "Antigravity",

      sessionPrefix: "Phiên · ",
      skillSuffix: " (Skill)",
      tabOpen: "● Mở",
      tabOpenLong: "● Tab đang mở",
      tabClosed: "○ Đóng",
      tabClosedLong: "○ Đã đóng",

      c3_tool_error: "△ Công cụ lỗi",
      c3_step_error: "△ Bước lỗi",
      c3_waiting_long_cmd: "◷ Chờ lệnh dài",
      c3_running_tool: "▷ Đang chạy",
      c3_running_thinking: "▷ Đang suy luận",
      c3_done: "✓ Xong",
      c3_idle: "○ Rảnh",

      act_run_command: "Chạy lệnh",
      act_write_file: "Ghi tệp",
      act_edit_file: "Sửa tệp",
      act_read_file: "Đọc tệp",
      act_search: "Tìm kiếm",
      act_spawn_agent: "Giao tác tử",
      act_todo_write: "Cập nhật việc",
      act_call_tool: "Gọi công cụ",
      act_reply: "Phản hồi / Tổng kết",
      act_user_prompt: "Nhận yêu cầu mới",
      act_thinking: "Đang phân tích yêu cầu",
      act_tool_error: "Công cụ trả lỗi",
      act_ready: "Sẵn sàng",

      justNow: "vừa xong",
      secAgo: "{n}s trước",
      minAgo: "{n}p trước",
      hrAgo: "{h}g trước",
      hrMinAgo: "{h}g {m}p trước",

      ctxTooltip: "Độ đầy ngữ cảnh ở lượt gần nhất (input + cache_creation + cache_read), không phải tổng cộng dồn cả phiên.",
      meTooltip: "Model & Effort thực tế trích từ api-request",
      maskedDetail: "[Đã ẩn bởi chế độ Che Riêng Tư]",

      branchGroupPrefix: "↳ Nhánh: ",
      generalBranch: "main / chung",
      agentsCountSuffix: "tác tử",
      showMoreIdleGroup: "+ Hiện thêm {n} tác tử rảnh / đã xong trong nhóm này",
      collapseIdleGroup: "▲ Thu gọn bớt tác tử rảnh",
      showMoreIdleFlat: "+ Hiện thêm {n} trạm rảnh / đã xong cũ hơn",
      collapseIdleFlat: "▲ Thu gọn danh sách trạm rảnh cũ",

      thAgent: "Tác tử",
      thTier: "Phân tầng",
      thStatus: "Trạng thái",
      thModelEffort: "Model · Effort",
      thProjectBranch: "Dự án · Nhánh",
      thContext: "Ngữ cảnh",
      thUpdated: "Cập nhật",
      thLastAction: "Hoạt động cuối",

      emptyWindowTitle: "Không có phiên Agent nào khớp bộ lọc trong khung giờ này.",
      emptyOlderHint: "Tìm thấy {n} phiên cũ hơn nằm ngoài khung giờ hiện tại.",
      btnExpand7d: "Mở rộng sang 7 ngày",
      emptyCliHint:
        "Gợi ý: Mở Claude Code / Antigravity trên máy, truyền --claude-dir nếu chạy WSL2, hoặc thêm cờ --demo để xem dữ liệu mẫu.",

      feedTitle: "Luồng sự kiện trực tiếp",
      feedFiltering: "Đang lọc:",
      feedShowAll: "Xem tất cả",
      feedEmpty: "Chưa có sự kiện nào trong khung giờ này.",

      drawerClose: "× Đóng (Esc)",
      drawerLoading: "Đang tải 30 bước gần nhất...",
      drawerTier: "Phân tầng:",
      drawerParent: "Phiên cha:",
      drawerContext: "Ngữ cảnh lượt cuối:",
      drawerParentModel: "Model phiên cha (pickedEffortModel):",
      drawerFilterFeed: "Lọc luồng sự kiện",
      drawerNoSteps: "Chưa có bản ghi gọi công cụ gần đây.",
      drawerWorkspace: "Không gian làm việc:",

      wtTitle: "Đa Làn & Git Worktrees",
      wtSub:
        "Đọc trạng thái các nhánh song song bằng git --no-optional-locks (không bao giờ tạo index.lock).",
      wtRescan: "↻ Quét lại Git",
      wtDisabled:
        "Tab Đa Làn Git đang tắt. Khởi động kèm --repo /duong/dan/repo (hoặc --demo) để theo dõi các worktree song song.",
      wtEmpty: "Không tìm thấy git worktree nào cho kho mã đã chọn.",
      wtThName: "Worktree",
      wtThBranch: "Nhánh",
      wtThState: "Trạng thái",
      wtThAheadBehind: "Vượt / Trễ",
      wtThCommit: "Commit gần nhất",
      wtState_MAIN: "NHÁNH CHÍNH",
      wtState_CODING: "ĐANG CODE ({dirty} tệp{extra})",
      wtState_UNMERGED: "CHỜ GỘP (+{ahead})",
      wtState_MERGED: "ĐÃ GỘP",
      wtAheadExtra: " · +{ahead} chờ gộp",

      toastRefreshed: "Đã làm mới toàn bộ dữ liệu trực tiếp!",
    },
  };

  let curLang = localStorage.getItem("agent_desk_lang") || "en";
  if (!DICT[curLang]) curLang = "en";

  let privacyMask = localStorage.getItem("agent_desk_privacy") === "1";
  const maskAliases = { proj: {}, branch: {} };
  let projSeq = 0;
  let branchSeq = 0;

  function t(key, vars) {
    let raw = (DICT[curLang] && DICT[curLang][key]) || DICT.en[key] || key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        raw = raw.replace(`{${k}}`, String(vars[k]));
      });
    }
    return raw;
  }

  function getLang() {
    return curLang;
  }

  function setLang(lang) {
    if (!DICT[lang]) return;
    curLang = lang;
    localStorage.setItem("agent_desk_lang", lang);
    document.documentElement.setAttribute("lang", lang);
  }

  function isPrivacyMask() {
    return privacyMask;
  }

  function togglePrivacyMask() {
    privacyMask = !privacyMask;
    localStorage.setItem("agent_desk_privacy", privacyMask ? "1" : "0");
    return privacyMask;
  }

  function maskProject(name) {
    if (!privacyMask || !name) return name || "";
    if (name === "Antigravity") return name;
    if (!maskAliases.proj[name]) {
      projSeq += 1;
      maskAliases.proj[name] = `workspace-${projSeq}`;
    }
    return maskAliases.proj[name];
  }

  function maskBranch(branch) {
    if (!privacyMask || !branch) return branch || "";
    if (branch === "main" || branch === "master") return branch;
    if (!maskAliases.branch[branch]) {
      branchSeq += 1;
      maskAliases.branch[branch] = `branch-${branchSeq}`;
    }
    return maskAliases.branch[branch];
  }

  function maskDetail(detail) {
    if (!privacyMask || !detail) return detail || "";
    return t("maskedDetail");
  }

  function formatAgentName(ag) {
    if (!ag) return "";
    if (ag.name_kind === "main_session") {
      return `${t("sessionPrefix")}${maskProject(ag.name)}`;
    }
    if (ag.name_kind === "skill") {
      return `${ag.name}${t("skillSuffix")}`;
    }
    return ag.name || "";
  }

  function formatModelEffort(meKey) {
    if (!meKey) return "";
    if (meKey.startsWith("unknown · ")) {
      return `${t("unknownModel")} · ${meKey.slice("unknown · ".length)}`;
    }
    return meKey;
  }

  function formatActionTitle(actionCode, tool) {
    const base = t(`act_${actionCode || "call_tool"}`);
    if (tool && actionCode !== "reply" && actionCode !== "user_prompt" && actionCode !== "thinking") {
      return `${base} (${tool})`;
    }
    return base;
  }

  function formatC3Label(ag) {
    const base = t(`c3_${ag.state_code || "idle"}`);
    if (ag.badge_tool && (ag.state_code === "running_tool" || ag.state_code === "waiting_long_cmd")) {
      return `${base} · ${ag.badge_tool}`;
    }
    return base;
  }

  function formatAge(ageSec) {
    if (ageSec === null || ageSec === undefined) return "";
    const s = Math.max(0, Math.floor(ageSec));
    if (s < 10) return t("justNow");
    if (s < 60) return t("secAgo", { n: s });
    const m = Math.floor(s / 60);
    if (m < 60) return t("minAgo", { n: m });
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem ? t("hrMinAgo", { h, m: rem }) : t("hrAgo", { h });
  }

  function formatClock(ts) {
    if (!ts) return "--:--:--";
    return new Date(ts * 1000).toLocaleTimeString(t("locale"), { hour12: false });
  }

  return {
    t,
    getLang,
    setLang,
    isPrivacyMask,
    togglePrivacyMask,
    maskProject,
    maskBranch,
    maskDetail,
    formatAgentName,
    formatModelEffort,
    formatActionTitle,
    formatC3Label,
    formatAge,
    formatClock,
  };
})();
