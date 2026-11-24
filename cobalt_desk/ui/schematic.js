/* Minimalist Architectural Blueprint SVG Schematics for Cobalt Agent Desk
   Pure vector line-art (1.5px strokes), zero raster assets, WCAG & deuteranopia safe. */

window.CobaltSchematic = (function () {
  "use strict";

  function roleIconPath(role) {
    switch (role) {
      case "implementer":
        return '<rect x="3.5" y="3.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="13.5" y="3.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="3.5" y="13.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M13.5 17h7M17 13.5v7" fill="none" stroke="currentColor" stroke-width="1.6"/>';
      case "security":
        return '<path d="M12 3l7 3v5c0 4.5-3 7.8-7 9.5C8 18.8 5 15.5 5 11V6l7-3z" fill="none" stroke="currentColor" stroke-width="1.6"/>';
      case "database":
        return '<ellipse cx="12" cy="6.5" rx="6.5" ry="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M5.5 6.5v11c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-11" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M5.5 12c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5" fill="none" stroke="currentColor" stroke-width="1.3"/>';
      case "python":
        return '<path d="M9 7l-4.5 5L9 17M15 7l4.5 5L15 17M13.2 5.5l-2.4 13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square"/>';
      case "typescript":
        return '<rect x="3.5" y="4.5" width="17" height="15" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7.5 9.5h6M10.5 9.5v6M15.5 10c-.6-.4-1.6-.4-1.8.4-.2.8 2 1.1 1.9 2.3-.1 1-1.3 1.2-2.2.8" fill="none" stroke="currentColor" stroke-width="1.5"/>';
      case "verifier":
        return '<rect x="4" y="4" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8.2 12.2l2.6 2.6 5-5.4" fill="none" stroke="currentColor" stroke-width="1.7"/>';
      case "skill_verify":
        return '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8.5 12.2l2.3 2.3 4.7-4.8" fill="none" stroke="currentColor" stroke-width="1.7"/>';
      case "planner":
        return '<path d="M12 3.5l8 4.2-8 4.2-8-4.2zM4 12l8 4.2 8-4.2M4 16.3L12 20.5l8-4.2" fill="none" stroke="currentColor" stroke-width="1.5"/>';
      case "surveyor":
        return '<circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="3 2"/><path d="M12 12l4.8-4.2" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/>';
      case "explore":
        return '<circle cx="11" cy="11" r="6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M15.6 15.6L20 20" stroke="currentColor" stroke-width="1.7"/>';
      case "antigravity":
        return '<path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z" fill="none" stroke="currentColor" stroke-width="1.6"/>';
      default:
        return '<rect x="3.5" y="4.5" width="17" height="15" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7.5 10l3 2.5-3 2.5M12.5 15h4" fill="none" stroke="currentColor" stroke-width="1.5"/>';
    }
  }

  function renderRoleBadgeSvg(role, size) {
    const s = size || 15;
    return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0;vertical-align:-2px;">${roleIconPath(role)}</svg>`;
  }

  function escapeXml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderStationSvg(agent) {
    const state = agent.room_state || "IDLE";
    const rawTool = String(agent.current_tool || (agent.is_finished ? "DONE" : "ACTIVE"));
    const tool = rawTool.length > 11 ? rawTool.slice(0, 10) + "…" : rawTool;
    const waitTool = rawTool.length > 8 ? rawTool.slice(0, 7) + "…" : rawTool;

    if (state === "WORKING") {
      return `
        <svg viewBox="0 0 220 66" width="100%" height="64" aria-hidden="true">
          <line x1="14" y1="52" x2="206" y2="52" stroke="var(--c3-blue-fg)" stroke-width="1.6"/>
          <line x1="24" y1="52" x2="24" y2="62" stroke="var(--c3-blue-fg)" stroke-width="1.4"/>
          <line x1="196" y1="52" x2="196" y2="62" stroke="var(--c3-blue-fg)" stroke-width="1.4"/>
          <rect x="56" y="12" width="68" height="32" fill="var(--c3-blue-bg)" stroke="var(--c3-blue-fg)" stroke-width="1.6"/>
          <line x1="90" y1="44" x2="90" y2="52" stroke="var(--c3-blue-fg)" stroke-width="1.6"/>
          <line x1="76" y1="52" x2="104" y2="52" stroke="var(--c3-blue-fg)" stroke-width="2"/>
          <line x1="64" y1="21" x2="98" y2="21" stroke="var(--c3-blue-fg)" stroke-width="1.6"/>
          <line x1="64" y1="28" x2="112" y2="28" stroke="var(--c3-blue-fg)" stroke-width="1.3" opacity="0.78"/>
          <line x1="64" y1="35" x2="90" y2="35" stroke="var(--c3-blue-fg)" stroke-width="1.3"/>
          <rect x="94" y="32" width="5" height="6" fill="var(--accent)" class="svg-pulse"/>
          <rect x="131" y="15" width="82" height="17" fill="var(--bg-card)" stroke="var(--c3-blue-fg)" stroke-width="1.2"/>
          <text x="172" y="26.5" text-anchor="middle" font-family="var(--font-mono)" font-size="8" font-weight="700" fill="var(--c3-blue-fg)">${escapeXml(tool)}</text>
          <circle cx="34" cy="26" r="5.6" fill="var(--c3-blue-bg)" stroke="var(--c3-blue-fg)" stroke-width="1.5"/>
          <path d="M23.5 48c0-5.6 4.8-9.5 10.5-9.5s10.5 3.9 10.5 9.5" fill="none" stroke="var(--c3-blue-fg)" stroke-width="1.5"/>
        </svg>
      `;
    }

    if (state === "WAITING") {
      return `
        <svg viewBox="0 0 220 66" width="100%" height="64" aria-hidden="true">
          <line x1="18" y1="54" x2="202" y2="54" stroke="var(--c3-amb-fg)" stroke-width="1.5"/>
          <rect x="30" y="13" width="46" height="41" fill="var(--c3-amb-bg)" stroke="var(--c3-amb-fg)" stroke-width="1.5"/>
          <line x1="36" y1="23" x2="62" y2="23" stroke="var(--c3-amb-fg)" stroke-width="1.4"/>
          <circle cx="69" cy="23" r="2.2" fill="var(--c3-amb-fg)" class="svg-pulse"/>
          <line x1="36" y1="34" x2="62" y2="34" stroke="var(--c3-amb-fg)" stroke-width="1.4"/>
          <circle cx="69" cy="34" r="2.2" fill="var(--c3-amb-fg)" opacity="0.5"/>
          <line x1="36" y1="45" x2="62" y2="45" stroke="var(--c3-amb-fg)" stroke-width="1.4"/>
          <line x1="76" y1="34" x2="108" y2="34" stroke="var(--c3-amb-fg)" stroke-width="1.4" stroke-dasharray="4 3"/>
          <circle cx="126" cy="34" r="14.5" fill="var(--bg-card)" stroke="var(--c3-amb-fg)" stroke-width="1.6"/>
          <path d="M126 25v9l6.2 3.6" fill="none" stroke="var(--c3-amb-fg)" stroke-width="1.6" stroke-linecap="square"/>
          <rect x="148" y="25.5" width="62" height="17" fill="var(--bg-card)" stroke="var(--c3-amb-fg)" stroke-width="1.2"/>
          <text x="179" y="37" text-anchor="middle" font-family="var(--font-mono)" font-size="8" font-weight="700" fill="var(--c3-amb-fg)">${escapeXml(waitTool)}</text>
        </svg>
      `;
    }

    if (state === "ERROR") {
      return `
        <svg viewBox="0 0 220 66" width="100%" height="64" aria-hidden="true">
          <line x1="22" y1="54" x2="198" y2="54" stroke="var(--c3-red-fg)" stroke-width="1.6"/>
          <rect x="64" y="13" width="92" height="33" fill="var(--c3-red-bg)" stroke="var(--c3-red-fg)" stroke-width="1.6"/>
          <path d="M110 19l11.5 20h-23z" fill="var(--bg-card)" stroke="var(--c3-red-fg)" stroke-width="1.6"/>
          <line x1="110" y1="26" x2="110" y2="32.5" stroke="var(--c3-red-fg)" stroke-width="1.8"/>
          <circle cx="110" cy="36.5" r="1.2" fill="var(--c3-red-fg)"/>
          <line x1="110" y1="46" x2="110" y2="54" stroke="var(--c3-red-fg)" stroke-width="1.6"/>
        </svg>
      `;
    }

    const isDone = Boolean(agent.is_finished);
    const stroke = isDone ? "var(--c3-grn-fg)" : "var(--ink-muted)";
    return `
      <svg viewBox="0 0 220 66" width="100%" height="64" aria-hidden="true" opacity="0.78">
        <line x1="28" y1="52" x2="192" y2="52" stroke="${stroke}" stroke-width="1.3"/>
        <rect x="78" y="16" width="64" height="28" fill="none" stroke="${stroke}" stroke-width="1.3"/>
        <line x1="110" y1="44" x2="110" y2="52" stroke="${stroke}" stroke-width="1.3"/>
        ${
          isDone
            ? `<path d="M101 30l6 6 12-12" fill="none" stroke="${stroke}" stroke-width="1.8"/>`
            : `<circle cx="110" cy="30" r="5" fill="none" stroke="${stroke}" stroke-width="1.3"/>`
        }
        <rect x="156" y="41" width="11" height="11" fill="none" stroke="${stroke}" stroke-width="1.2"/>
        <path d="M167 43h3v5h-3" fill="none" stroke="${stroke}" stroke-width="1.2"/>
      </svg>
    `;
  }

  return {
    renderRoleBadgeSvg,
    renderStationSvg,
  };
})();
