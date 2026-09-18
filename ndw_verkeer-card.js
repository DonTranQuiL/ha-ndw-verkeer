/**
 * NDW Verkeer Lovelace card.
 * Custom element: ndw_verkeer-card
 * Point entity at the master NDW Verkeer sensor (attributes.items).
 */
class NdwVerkeerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._expanded = new Set();
    this._filter = "all";
    this._fingerprint = "";
    this._onClick = this._onClick.bind(this);
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Please define an entity (NDW Verkeer master sensor).");
    }
    this.config = config;
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
    return 4;
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

  _items(attrs, stateObj) {
    let items = attrs.items;
    if (!Array.isArray(items) || !items.length) {
      const history = Array.isArray(attrs.history) ? attrs.history : [];
      if (attrs.description || attrs.id) {
        items = [
          {
            id: attrs.id,
            type: attrs.type || stateObj.state,
            start: attrs.start,
            end: attrs.end,
            description: attrs.description,
          },
          ...history,
        ];
      } else {
        items = history;
      }
    }
    const filter = this._filter;
    if (filter === "all") {
      return items;
    }
    return items.filter((item) =>
      String(item.type || "").toLowerCase().includes(filter)
    );
  }

  _typeLabel(type) {
    const raw = String(type || "Verkeershinder");
    return raw.replace(/([a-z])([A-Z])/g, "$1 $2");
  }

  _onClick(event) {
    const target = event.target.closest("[data-action]");
    if (!target) {
      return;
    }
    const action = target.getAttribute("data-action");
    if (action === "filter") {
      this._filter = target.getAttribute("data-filter") || "all";
      this._fingerprint = "";
      if (this._hass) {
        this.hass = this._hass;
      }
      return;
    }
    if (action === "toggle") {
      const id = target.getAttribute("data-id") || "";
      if (this._expanded.has(id)) {
        this._expanded.delete(id);
      } else {
        this._expanded.add(id);
      }
      this._fingerprint = "";
      if (this._hass) {
        this.hass = this._hass;
      }
    }
  }

  _render(stateObj, attrs, dark) {
    const items = this._items(attrs, stateObj);
    const count = attrs.count != null ? attrs.count : items.length;
    const theme = dark ? "dark-theme" : "light-theme";
    const filters = [
      ["all", "All"],
      ["road", "Roadworks"],
      ["maintenance", "Maintenance"],
      ["accident", "Accident"],
      ["closure", "Closure"],
    ];
    const filterHtml = filters
      .map(([value, label]) => {
        const active = this._filter === value ? "active" : "";
        return `<button type="button" class="chip ${active}" data-action="filter" data-filter="${value}">${label}</button>`;
      })
      .join("");

    const rows = items
      .slice(0, 40)
      .map((item, index) => {
        const id = String(item.id || index);
        const open = this._expanded.has(id);
        const desc = item.description || "";
        const shortDesc =
          !open && desc.length > 160 ? `${desc.slice(0, 159)}…` : desc;
        return `<article class="row ${open ? "open" : ""}" data-action="toggle" data-id="${this._esc(id)}">
          <div class="row-top">
            <span class="pill">${this._esc(this._typeLabel(item.type))}</span>
            <span class="when">${this._esc(item.start || "")}${item.end ? " → " + this._esc(item.end) : ""}</span>
          </div>
          <p>${this._esc(shortDesc)}</p>
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
        <div class="chips">${filterHtml}</div>
        <div class="list">
          ${rows || "<p class='empty'>No traffic matches for this filter.</p>"}
        </div>
      </ha-card>
    `;
    this.shadowRoot.querySelector("ha-card").addEventListener("click", this._onClick);
  }
}

customElements.define("ndw_verkeer-card", NdwVerkeerCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ndw_verkeer-card",
  name: "NDW Verkeer Card",
  description: "Traffic matches from the NDW Verkeer master sensor.",
});
