/**
 * NDW Verkeer Lovelace card (1.0.5-beta.5).
 * List render cap: first 80 filtered items (sensor attributes.items is uncapped).
 * Custom element: ndw_verkeer-card
 * Point entity at the master NDW Verkeer sensor (attributes.items).
 *
 * Config (optional):
 *   sort: start_asc | start_desc | end_asc | end_desc
 *   default_date: YYYY-MM-DD (pre-select date filter; empty = all dates)
 *   date_mode: active | starting  (active = start<=day<=end; starting = start on day)
 */
class NdwVerkeerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._expanded = new Set();
    this._filter = "all";
    this._sort = "start_asc";
    this._date = "";
    this._dateMode = "active";
    this._fingerprint = "";
    this._onClick = this._onClick.bind(this);
    this._onChange = this._onChange.bind(this);
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Please define an entity (NDW Verkeer master sensor).");
    }
    this.config = config;
    if (config.sort) {
      this._sort = String(config.sort);
    }
    if (config.default_date != null && config.default_date !== "") {
      this._date = String(config.default_date);
    }
    if (config.date_mode) {
      this._dateMode = String(config.date_mode);
    }
  }

  set hass(hass) {
    this._hass = hass;
    const entityId = this.config.entity;
    const stateObj = hass.states[entityId];
    if (!stateObj) {
      this.shadowRoot.innerHTML =
        `<ha-card style="padding:16px;color:var(--error-color);">Entity not found: ${this._esc(entityId)}</ha-card>`;
      return;
    }
    const attrs = stateObj.attributes || {};
    const dark = this._isDark(hass);
    const fingerprint = JSON.stringify({
      s: stateObj.state,
      f: this._filter,
      sort: this._sort,
      date: this._date,
      mode: this._dateMode,
      e: [...this._expanded],
      d: dark,
      i: attrs.items || attrs.history || [],
      c: attrs.count,
    });
    if (fingerprint === this._fingerprint) {
      return;
    }
    this._fingerprint = fingerprint;
    this._render(stateObj, attrs, dark);
  }

  getCardSize() {
    return 5;
  }

  _isDark(hass) {
    try {
      return !!(hass && hass.themes && hass.themes.darkMode);
    } catch (_err) {
      return false;
    }
  }

  _esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * Parse NDW display dates (DD-MM-YYYY HH:MM) or ISO into a Date at local midnight
   * for day comparisons, or full Date for sorting.
   */
  _parseDate(value) {
    if (!value || value === "Onbekend") {
      return null;
    }
    const s = String(value).trim();
    // DD-MM-YYYY HH:MM
    let m = s.match(/^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if (m) {
      return new Date(
        Number(m[3]),
        Number(m[2]) - 1,
        Number(m[1]),
        Number(m[4] || 0),
        Number(m[5] || 0)
      );
    }
    // ISO
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  _dayKey(dateObj) {
    if (!dateObj) {
      return "";
    }
    const y = dateObj.getFullYear();
    const mo = String(dateObj.getMonth() + 1).padStart(2, "0");
    const da = String(dateObj.getDate()).padStart(2, "0");
    return `${y}-${mo}-${da}`;
  }

  /**
   * Date filter helper (also documented in README).
   * mode=active: item overlaps selected calendar day (start<=day<=end).
   * mode=starting: item start falls on that calendar day.
   */
  _matchesDate(item, dayIso, mode) {
    if (!dayIso) {
      return true;
    }
    const start = this._parseDate(item.start);
    const end = this._parseDate(item.end);
    if (mode === "starting") {
      return start ? this._dayKey(start) === dayIso : false;
    }
    // active on day
    if (!start && !end) {
      return true;
    }
    const day = new Date(`${dayIso}T12:00:00`);
    const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate());
    const dayEnd = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 23, 59, 59);
    const s = start || dayStart;
    const e = end || dayEnd;
    return s <= dayEnd && e >= dayStart;
  }

  _typeMeta(type) {
    const raw = String(type || "Verkeershinder");
    const key = raw.toLowerCase();
    if (key.includes("maintenance") || key.includes("construction")) {
      return { label: "Maintenance", icon: "🚧", filterKey: "maintenance" };
    }
    if (key.includes("rerout")) {
      return { label: "Reroute", icon: "🔄", filterKey: "reroute" };
    }
    if (key.includes("roadorcarriageway") || key.includes("lane")) {
      return { label: "Lane management", icon: "⛔", filterKey: "road" };
    }
    if (key.includes("publicevent") || key.includes("event")) {
      return { label: "Event", icon: "🚴", filterKey: "event" };
    }
    if (key.includes("accident") || key.includes("ongeval")) {
      return { label: "Accident", icon: "💥", filterKey: "accident" };
    }
    if (key.includes("closure") || key.includes("afsluit")) {
      return { label: "Closure", icon: "🚫", filterKey: "closure" };
    }
    if (key.includes("speed")) {
      return { label: "Speed limit", icon: "🐢", filterKey: "speed" };
    }
    // CamelCase → spaced fallback
    return {
      label: raw.replace(/([a-z])([A-Z])/g, "$1 $2"),
      icon: "⚠️",
      filterKey: "other",
    };
  }

  _items(attrs, stateObj) {
    let items = attrs.items;
    if (!Array.isArray(items) || !items.length) {
      const history = Array.isArray(attrs.history) ? attrs.history : [];
      if (attrs.description || attrs.id || attrs.location) {
        items = [
          {
            id: attrs.id,
            type: attrs.type || stateObj.state,
            start: attrs.start,
            end: attrs.end,
            description: attrs.description,
            location: attrs.location,
            municipality: attrs.municipality,
          },
          ...history,
        ];
      } else {
        items = history;
      }
    }

    const typeFilter = this._filter;
    let out = items;
    if (typeFilter !== "all") {
      out = out.filter((item) => {
        const meta = this._typeMeta(item.type);
        const raw = String(item.type || "").toLowerCase();
        return (
          meta.filterKey === typeFilter ||
          raw.includes(typeFilter)
        );
      });
    }

    out = out.filter((item) => this._matchesDate(item, this._date, this._dateMode));

    const sort = this._sort || "start_asc";
    const dir = sort.endsWith("_desc") ? -1 : 1;
    const field = sort.startsWith("end") ? "end" : "start";
    out = [...out].sort((a, b) => {
      const da = this._parseDate(a[field]);
      const db = this._parseDate(b[field]);
      const ta = da ? da.getTime() : 0;
      const tb = db ? db.getTime() : 0;
      return (ta - tb) * dir;
    });

    return out;
  }

  _rerender() {
    this._fingerprint = "";
    if (this._hass) {
      this.hass = this._hass;
    }
  }

  _onClick(event) {
    const target = event.target.closest("[data-action]");
    if (!target) {
      return;
    }
    const action = target.getAttribute("data-action");
    if (action === "filter") {
      this._filter = target.getAttribute("data-filter") || "all";
      this._rerender();
      return;
    }
    if (action === "clear-date") {
      this._date = "";
      this._rerender();
      return;
    }
    if (action === "toggle") {
      const id = target.getAttribute("data-id") || "";
      if (this._expanded.has(id)) {
        this._expanded.delete(id);
      } else {
        this._expanded.add(id);
      }
      this._rerender();
    }
  }

  _onChange(event) {
    const target = event.target;
    if (!target || !target.name) {
      return;
    }
    if (target.name === "ndw-date") {
      this._date = target.value || "";
      this._rerender();
      return;
    }
    if (target.name === "ndw-sort") {
      this._sort = target.value || "start_asc";
      this._rerender();
      return;
    }
    if (target.name === "ndw-date-mode") {
      this._dateMode = target.value || "active";
      this._rerender();
    }
  }

  _isThinTitle(title) {
    const t = (title || "").trim().toLowerCase();
    if (!t) return true;
    const thin = new Set([
      "rijbaanafsluiting",
      "rijstrookafsluiting",
      "wegafsluiting",
      "snelheidsbeperking",
      "periodieke rijbaanafsluiting",
      "geen details beschikbaar",
      "onbekende locatie",
    ]);
    if (thin.has(t)) return true;
    if (t.startsWith("gemeente ") || t.startsWith("provincie ")) return true;
    return t.length < 12;
  }

  _titleLine(item) {
    const loc = (item.location || "").trim();
    if (loc) {
      return loc;
    }
    // Prefer description over municipality when DATEX has no street
    const desc = (item.description || "").trim();
    if (desc) {
      return desc.length > 80 ? `${desc.slice(0, 79)}…` : desc;
    }
    const muni = (item.municipality || "").trim();
    if (muni) {
      return muni;
    }
    return "Onbekende locatie";
  }

  _render(stateObj, attrs, dark) {
    const items = this._items(attrs, stateObj);
    const count = attrs.count != null ? attrs.count : items.length;
    const theme = dark ? "dark-theme" : "light-theme";
    const filters = [
      ["all", "All"],
      ["road", "Lane / road"],
      ["maintenance", "Maintenance"],
      ["reroute", "Reroute"],
      ["event", "Event"],
      ["accident", "Accident"],
      ["closure", "Closure"],
    ];
    const filterHtml = filters
      .map(([value, label]) => {
        const active = this._filter === value ? "active" : "";
        return `<button type="button" class="chip ${active}" data-action="filter" data-filter="${value}">${label}</button>`;
      })
      .join("");

    // Soft UI cap (80). Full list remains on sensor attributes.items / count.
    const rows = items
      .slice(0, 80)
      .map((item, index) => {
        const id = String(item.id || index);
        const open = this._expanded.has(id);
        const desc = item.description || "";
        const shortDesc =
          !open && desc.length > 180 ? `${desc.slice(0, 179)}…` : desc;
        const meta = this._typeMeta(item.type);
        const title = this._titleLine(item);
        const muni =
          item.municipality && item.municipality !== title
            ? `<span class="muni">${this._esc(item.municipality)}</span>`
            : "";
        // When the title is a thin fallback (mgmt label / truncated desc), still
        // show the description body so users see the full narrative.
        const thinTitle = this._isThinTitle(title);
        const showDesc =
          shortDesc && (shortDesc !== title || (thinTitle && shortDesc.length > title.length))
            ? `<p>${this._esc(shortDesc)}</p>`
            : "";
        return `<article class="row ${open ? "open" : ""}" data-action="toggle" data-id="${this._esc(id)}">
          <div class="row-top">
            <span class="pill">${meta.icon} ${this._esc(meta.label)}</span>
            <span class="when">${this._esc(item.start || "")}${item.end ? " → " + this._esc(item.end) : ""}</span>
          </div>
          <h3 class="loc">${this._esc(title)}</h3>
          ${muni}
          ${showDesc}
        </article>`;
      })
      .join("");

    this.shadowRoot.innerHTML = `
      <ha-card class="${theme}">
        <style>
          :host { display: block; }
          ha-card {
            background: var(--ha-card-background, var(--card-background-color));
            color: var(--primary-text-color);
            padding: 12px 14px 14px;
          }
          .header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            margin-bottom: 10px;
          }
          .header h2 {
            margin: 0;
            font-size: 1.05rem;
            font-weight: 600;
          }
          .muted { color: var(--secondary-text-color); font-size: .85rem; }
          .stats {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
          }
          .stat {
            background: color-mix(in srgb, var(--accent-color, #03a9f4) 12%, transparent);
            border: 1px solid var(--divider-color);
            border-radius: 10px;
            padding: 8px 10px;
            min-width: 72px;
          }
          .stat b { display: block; font-size: 1.15rem; }
          .stat span { color: var(--secondary-text-color); font-size: .75rem; }
          .toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
            margin-bottom: 10px;
          }
          .toolbar label {
            font-size: .78rem;
            color: var(--secondary-text-color);
            display: flex;
            flex-direction: column;
            gap: 2px;
          }
          .toolbar input, .toolbar select {
            font: inherit;
            font-size: .85rem;
            padding: 4px 8px;
            border-radius: 8px;
            border: 1px solid var(--divider-color);
            background: var(--card-background-color);
            color: var(--primary-text-color);
          }
          .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
          .chip {
            border: 1px solid var(--divider-color);
            background: transparent;
            color: var(--primary-text-color);
            border-radius: 999px;
            padding: 4px 10px;
            font: inherit;
            font-size: .8rem;
            cursor: pointer;
          }
          .chip.active {
            background: var(--accent-color, #03a9f4);
            border-color: transparent;
            color: var(--text-primary-color, #fff);
          }
          .list { display: flex; flex-direction: column; gap: 8px; }
          .row {
            border: 1px solid var(--divider-color);
            border-radius: 12px;
            padding: 10px 12px;
            cursor: pointer;
          }
          .row-top {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            align-items: center;
            margin-bottom: 4px;
          }
          .pill {
            font-size: .72rem;
            text-transform: uppercase;
            letter-spacing: .03em;
            padding: 2px 8px;
            border-radius: 999px;
            background: color-mix(in srgb, var(--warning-color, #f5a623) 22%, transparent);
          }
          .when { color: var(--secondary-text-color); font-size: .78rem; }
          .loc {
            margin: 2px 0 2px;
            font-size: 1rem;
            font-weight: 600;
            line-height: 1.25;
          }
          .muni {
            display: block;
            color: var(--secondary-text-color);
            font-size: .78rem;
            margin-bottom: 4px;
          }
          .row p { margin: 0; font-size: .9rem; line-height: 1.35; }
          .empty { color: var(--secondary-text-color); padding: 8px 0; }
          @media (max-width: 1000px) {
            .row-top { flex-direction: column; align-items: flex-start; }
          }
        </style>
        <div class="header">
          <h2>${this._esc(this.config.title || stateObj.attributes.friendly_name || "NDW Verkeer")}</h2>
          <span class="muted">${this._esc(stateObj.state || "")}</span>
        </div>
        <div class="stats">
          <div class="stat"><b>${this._esc(count)}</b><span>matches</span></div>
          <div class="stat"><b>${this._esc(items.length)}</b><span>shown</span></div>
        </div>
        <div class="toolbar">
          <label>Date
            <input type="date" name="ndw-date" value="${this._esc(this._date)}" />
          </label>
          <label>Filter mode
            <select name="ndw-date-mode">
              <option value="active"${this._dateMode === "active" ? " selected" : ""}>Active on day</option>
              <option value="starting"${this._dateMode === "starting" ? " selected" : ""}>Starting that day</option>
            </select>
          </label>
          <label>Sort
            <select name="ndw-sort">
              <option value="start_asc"${this._sort === "start_asc" ? " selected" : ""}>Start ↑</option>
              <option value="start_desc"${this._sort === "start_desc" ? " selected" : ""}>Start ↓ (newest)</option>
              <option value="end_asc"${this._sort === "end_asc" ? " selected" : ""}>End ↑</option>
              <option value="end_desc"${this._sort === "end_desc" ? " selected" : ""}>End ↓</option>
            </select>
          </label>
          <button type="button" class="chip" data-action="clear-date">Clear date</button>
        </div>
        <div class="chips">${filterHtml}</div>
        <div class="list">
          ${rows || "<p class='empty'>No traffic matches for this filter.</p>"}
        </div>
      </ha-card>
    `;
    const card = this.shadowRoot.querySelector("ha-card");
    card.addEventListener("click", this._onClick);
    card.addEventListener("change", this._onChange);
  }
}

customElements.define("ndw_verkeer-card", NdwVerkeerCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ndw_verkeer-card",
  name: "NDW Verkeer Card",
  description: "Traffic matches from the NDW Verkeer master sensor (location, date filter, sort).",
});
