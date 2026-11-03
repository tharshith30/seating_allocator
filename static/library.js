/**
 * library.js — Frontend controller for the Smart Library Utilization and Analytics module.
 *
 * Handles:
 * - Student Live View & crowd gauge
 * - Stale observation warnings (> 120 minutes)
 * - Admin Occupancy Recorder (headcount entry & capacity config)
 * - Interactive SVG/HTML5 charts (Hourly bars, Daily trend, Peak heatmap)
 * - Machine Learning predictive forecasts & model evaluation display (MAE)
 * - Smart administrative recommendations
 * - Report exports (Excel & PDF)
 */

const Lib = {
  activeSubTab: "student",
  statsData: null,
  predictionsData: null,

  async init() {
    this.setupSubTabs();
    await this.loadLiveStatus();
    this.setupAdminForms();
    this.setupDateFilters();
    await this.loadAnalytics("30d");
    await this.loadPredictions();
    await this.loadRecommendations();

    // Auto-refresh live status every 60s
    setInterval(() => this.loadLiveStatus(), 60000);
  },

  setupSubTabs() {
    document.querySelectorAll(".lib-sub-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const sub = btn.dataset.sub;
        this.switchSubTab(sub);
      });
    });
  },

  switchSubTab(sub) {
    this.activeSubTab = sub;
    document.querySelectorAll(".lib-sub-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.sub === sub);
    });
    document.querySelectorAll(".lib-sub-pane").forEach(p => {
      p.classList.toggle("active", p.id === `lib-pane-${sub}`);
    });
  },

  async loadLiveStatus() {
    try {
      const res = await fetch("/api/library/status").then(r => r.json());
      if (res.status !== "success") return;

      const cur = res.latest;
      const cfg = res.config;

      // Update Header Badge & Counters
      const capEl = document.getElementById("lib-total-capacity");
      if (capEl) capEl.textContent = `${cfg.total_capacity} Seats`;

      const occEl = document.getElementById("lib-live-occupied");
      const availEl = document.getElementById("lib-live-available");
      const pctEl = document.getElementById("lib-live-pct");
      const statusBadge = document.getElementById("lib-live-status-badge");
      const updatedEl = document.getElementById("lib-live-updated");
      const staleAlert = document.getElementById("lib-stale-alert");

      if (occEl) occEl.textContent = cur.occupied_seats;
      if (availEl) availEl.textContent = cur.available_seats;
      if (pctEl) pctEl.textContent = `${cur.occupancy_pct}%`;

      if (statusBadge) {
        statusBadge.textContent = cur.status;
        statusBadge.className = `crowd-badge crowd-${cur.badge_color}`;
      }

      if (updatedEl) updatedEl.textContent = cur.last_updated_human;

      // Staleness alert
      if (staleAlert) {
        if (cur.is_stale) {
          staleAlert.style.display = "flex";
          const staleTxt = document.getElementById("lib-stale-text");
          if (staleTxt) {
            staleTxt.textContent = `Last recorded observation was ${cur.last_updated_human} (${cur.recorded_at || 'No recent reading'}). This displays periodic observations, not automatic real-time tracking.`;
          }
        } else {
          staleAlert.style.display = "none";
        }
      }

      // Fill visual progress meter
      const meterFill = document.getElementById("lib-meter-fill");
      if (meterFill) {
        meterFill.style.width = `${Math.min(100, cur.occupancy_pct)}%`;
        meterFill.className = `meter-fill crowd-bg-${cur.badge_color}`;
      }

      // Best Visiting Hours
      const bestEl = document.getElementById("lib-best-visiting");
      if (bestEl) bestEl.textContent = res.best_visiting_hours;

      // Peak Hours banner
      const peakEl = document.getElementById("lib-typical-peaks");
      if (peakEl && res.peak_hours && res.peak_hours.length) {
        peakEl.textContent = res.peak_hours.map(p => p.hour).join(", ");
      }
    } catch (e) {
      console.warn("Failed to load library live status:", e);
    }
  },

  setupAdminForms() {
    // Record Observation form
    const obsForm = document.getElementById("lib-obs-form");
    if (obsForm) {
      obsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const seats = parseInt(document.getElementById("lib-obs-seats").value, 10);
        const pin = document.getElementById("lib-obs-pin").value.trim() || "1234";
        const notes = document.getElementById("lib-obs-notes").value.trim();
        const msgEl = document.getElementById("lib-obs-msg");

        try {
          const resp = await fetch("/api/library/occupancy", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Pin": pin },
            body: JSON.stringify({ occupied_seats: seats, pin, notes })
          }).then(r => r.json());

          if (resp.success) {
            this.showMsg(msgEl, resp.message, false);
            obsForm.reset();
            const pinEl = document.getElementById("lib-obs-pin");
            if (pinEl) pinEl.value = "1234";
            await this.loadLiveStatus();
            await this.loadAnalytics("30d");
            await this.loadPredictions();
            await this.loadRecommendations();
          } else {
            this.showMsg(msgEl, resp.error || "Failed to record observation", true);
          }
        } catch (err) {
          this.showMsg(msgEl, "Network error recording headcount.", true);
        }
      });
    }

    // Capacity & Threshold Config form
    const cfgForm = document.getElementById("lib-cfg-form");
    if (cfgForm) {
      cfgForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const cap = parseInt(document.getElementById("lib-cfg-capacity").value, 10);
        const low = parseFloat(document.getElementById("lib-cfg-low").value);
        const mod = parseFloat(document.getElementById("lib-cfg-mod").value);
        const high = parseFloat(document.getElementById("lib-cfg-high").value);
        const pin = document.getElementById("lib-cfg-pin").value.trim() || "1234";
        const msgEl = document.getElementById("lib-cfg-msg");

        try {
          const resp = await fetch("/api/library/config", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Pin": pin },
            body: JSON.stringify({ total_capacity: cap, low_threshold_pct: low, mod_threshold_pct: mod, high_threshold_pct: high, pin })
          }).then(r => r.json());

          if (resp.success) {
            this.showMsg(msgEl, resp.message, false);
            await this.loadLiveStatus();
            await this.loadAnalytics("30d");
          } else {
            this.showMsg(msgEl, resp.error || "Failed to update configuration", true);
          }
        } catch (err) {
          this.showMsg(msgEl, "Network error updating config.", true);
        }
      });
    }
  },

  setupDateFilters() {
    document.querySelectorAll(".lib-filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".lib-filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const f = btn.dataset.filter;
        this.loadAnalytics(f);
      });
    });
  },

  async loadAnalytics(filter) {
    try {
      const data = await fetch(`/api/library/analytics?filter=${filter}`).then(r => r.json());
      this.statsData = data;
      this.renderAnalytics(data);
    } catch (e) {
      console.warn("Error loading library analytics:", e);
    }
  },

  renderAnalytics(data) {
    if (!data || !data.has_data) return;

    // KPI Cards
    const avgEl = document.getElementById("lib-kpi-avg");
    const maxEl = document.getElementById("lib-kpi-max");
    const minEl = document.getElementById("lib-kpi-min");
    const totalEl = document.getElementById("lib-kpi-total");

    if (avgEl) avgEl.textContent = `${data.avg_occupancy_pct}%`;
    if (maxEl) maxEl.textContent = `${data.max_occupancy_seats} seats (${data.max_occupancy_pct}%)`;
    if (minEl) minEl.textContent = `${data.min_occupancy_seats} seats (${data.min_occupancy_pct}%)`;
    if (totalEl) totalEl.textContent = `${data.total_observations} readings (${data.actual_count} real / ${data.simulated_count} sim)`;

    // Hourly Bar Chart
    this.renderHourlyBarChart(data.hourly_chart);

    // Daily Trend Line Chart
    this.renderDailyTrendChart(data.daily_trend);

    // Peak-Hour Heatmap
    this.renderHeatmap(data.heatmap);

    // Recent Observation Table
    this.loadRecentTable();
  },

  renderHourlyBarChart(chartData) {
    const container = document.getElementById("lib-hourly-chart");
    if (!container || !chartData || !chartData.labels) return;

    const labels = chartData.labels;
    const values = chartData.data;
    const maxVal = 100;

    let html = `<div class="chart-bars-wrap">`;
    for (let i = 0; i < labels.length; i++) {
      const val = values[i] || 0;
      const heightPct = Math.min(100, Math.round((val / maxVal) * 100));
      const colorClass = val >= 90 ? "crowd-bg-danger" : val >= 70 ? "crowd-bg-warning" : val >= 35 ? "crowd-bg-info" : "crowd-bg-success";

      html += `
        <div class="chart-bar-col" title="${labels[i]}: ${val}% average occupancy">
          <div class="chart-bar-val">${val > 0 ? val + '%' : ''}</div>
          <div class="chart-bar-track">
            <div class="chart-bar-fill ${colorClass}" style="height:${heightPct}%"></div>
          </div>
          <div class="chart-bar-lbl">${labels[i]}</div>
        </div>
      `;
    }
    html += `</div>`;
    container.innerHTML = html;
  },

  renderDailyTrendChart(dailyData) {
    const container = document.getElementById("lib-daily-chart");
    if (!container || !dailyData || !dailyData.labels || !dailyData.labels.length) {
      if (container) container.innerHTML = `<div class="no-data-msg">No historical daily observations recorded yet.</div>`;
      return;
    }

    const labels = dailyData.labels;
    const values = dailyData.data;

    const width = 640;
    const height = 180;
    const padL = 40;
    const padB = 30;
    const padT = 15;
    const padR = 20;

    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    let points = [];
    for (let i = 0; i < labels.length; i++) {
      const x = padL + (i / Math.max(1, labels.length - 1)) * plotW;
      const y = padT + plotH - ((values[i] || 0) / 100) * plotH;
      points.push(`${x},${y}`);
    }

    const polyline = points.join(" ");

    let svg = `
      <svg viewBox="0 0 ${width} ${height}" class="trend-svg" style="width:100%;height:auto;max-height:220px">
        <!-- Grid lines -->
        <line x1="${padL}" y1="${padT}" x2="${width - padR}" y2="${padT}" stroke="var(--border)" stroke-dasharray="4"/>
        <line x1="${padL}" y1="${padT + plotH / 2}" x2="${width - padR}" y2="${padT + plotH / 2}" stroke="var(--border)" stroke-dasharray="4"/>
        <line x1="${padL}" y1="${padT + plotH}" x2="${width - padR}" y2="${padT + plotH}" stroke="var(--border)"/>

        <!-- Y-axis labels -->
        <text x="${padL - 6}" y="${padT + 4}" fill="var(--text-muted)" font-size="9" text-anchor="end">100%</text>
        <text x="${padL - 6}" y="${padT + plotH / 2 + 3}" fill="var(--text-muted)" font-size="9" text-anchor="end">50%</text>
        <text x="${padL - 6}" y="${padT + plotH + 3}" fill="var(--text-muted)" font-size="9" text-anchor="end">0%</text>

        <!-- Trend Line -->
        <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${polyline}"/>

        <!-- Data circles -->
        ${points.map((pt, idx) => {
          const [cx, cy] = pt.split(",");
          return `<circle cx="${cx}" cy="${cy}" r="3.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"><title>${labels[idx]}: ${values[idx]}%</title></circle>`;
        }).join("")}

        <!-- X labels (first, middle, last) -->
        <text x="${padL}" y="${height - 8}" fill="var(--text-muted)" font-size="9" text-anchor="start">${labels[0] || ''}</text>
        ${labels.length > 2 ? `<text x="${padL + plotW / 2}" y="${height - 8}" fill="var(--text-muted)" font-size="9" text-anchor="middle">${labels[Math.floor(labels.length / 2)]}</text>` : ''}
        <text x="${width - padR}" y="${height - 8}" fill="var(--text-muted)" font-size="9" text-anchor="end">${labels[labels.length - 1] || ''}</text>
      </svg>
    `;
    container.innerHTML = svg;
  },

  renderHeatmap(heatmapData) {
    const container = document.getElementById("lib-heatmap-table");
    if (!container || !heatmapData || !heatmapData.length) return;

    let hours = heatmapData[0].slots.map(s => s.hour);
    let html = `<table class="lib-heatmap-grid"><thead><tr><th style="width:60px">Day</th>`;
    hours.forEach(h => html += `<th>${h.split(":")[0]}h</th>`);
    html += `</tr></thead><tbody>`;

    heatmapData.forEach(row => {
      html += `<tr><td class="hm-day-lbl"><strong>${row.day}</strong></td>`;
      row.slots.forEach(s => {
        const val = s.avg_pct;
        let colorClass = "hm-c0";
        if (val >= 90) colorClass = "hm-c4";
        else if (val >= 70) colorClass = "hm-c3";
        else if (val >= 35) colorClass = "hm-c2";
        else if (val > 0) colorClass = "hm-c1";

        html += `
          <td class="hm-cell ${colorClass}" title="${row.day_name} at ${s.hour}: ${val}% avg occupancy (${s.count} readings)">
            ${val > 0 ? val + '%' : '–'}
          </td>
        `;
      });
      html += `</tr>`;
    });

    html += `</tbody></table>`;
    container.innerHTML = html;
  },

  async loadRecentTable() {
    const tbody = document.getElementById("lib-recent-table-body");
    if (!tbody) return;

    try {
      const res = await fetch("/api/library/records?limit=15").then(r => r.json());
      const records = res.records || [];

      if (!records.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="td-center" style="color:var(--text-muted)">No observations recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = records.map(r => `
        <tr>
          <td class="td-cell" style="font-weight:700">#${r.id}</td>
          <td class="td-cell">${r.recorded_date} ${r.recorded_time.substring(0, 5)}</td>
          <td class="td-center" style="font-weight:600">${r.occupied_seats}</td>
          <td class="td-center">${r.available_seats}</td>
          <td class="td-center" style="font-weight:700">${r.occupancy_pct}%</td>
          <td class="td-center"><span class="crowd-badge crowd-${r.badge_color}">${r.status}</span></td>
          <td class="td-cell" style="font-size:0.8rem;color:var(--text-muted)">${r.notes || '–'}</td>
        </tr>
      `).join("");
    } catch (e) {
      console.warn("Failed to load recent table:", e);
    }
  },

  async loadPredictions() {
    try {
      const data = await fetch("/api/library/predictions?horizon=12").then(r => r.json());
      this.predictionsData = data;
      this.renderPredictions(data);
    } catch (e) {
      console.warn("Failed to load predictions:", e);
    }
  },

  renderPredictions(data) {
    if (!data) return;

    // Metrics banner
    const modelBadge = document.getElementById("lib-pred-model-type");
    const maeBadge = document.getElementById("lib-pred-mae");
    const sampleBadge = document.getElementById("lib-pred-samples");
    const provAlert = document.getElementById("lib-pred-provisional-alert");

    const m = data.metrics || {};
    if (modelBadge) modelBadge.textContent = m.model_type || "Regression Engine";
    if (maeBadge) maeBadge.textContent = m.mae != null ? `MAE: ±${m.mae}%` : "Evaluating...";
    if (sampleBadge) sampleBadge.textContent = `${m.total_samples || 0} training points`;

    if (provAlert) {
      provAlert.style.display = m.is_provisional ? "block" : "none";
      const txt = document.getElementById("lib-pred-status-text");
      if (txt) txt.textContent = m.status_message;
    }

    // Forecast cards container
    const fcContainer = document.getElementById("lib-forecast-grid");
    if (!fcContainer || !data.forecasts || !data.forecasts.length) return;

    fcContainer.innerHTML = data.forecasts.map(f => `
      <div class="forecast-card crowd-border-${f.badge_color}">
        <div class="fc-time">${f.day_label} ${f.hour_label}</div>
        <div class="fc-pct">${f.predicted_occupancy_pct}%</div>
        <div class="crowd-badge crowd-${f.badge_color}" style="font-size:0.75rem">${f.crowd_level}</div>
        <div class="fc-seats">Est. ${f.predicted_seats} occupied &bull; <strong>${f.expected_available_seats} free</strong></div>
      </div>
    `).join("");
  },

  async loadRecommendations() {
    const container = document.getElementById("lib-recommendations-list");
    if (!container) return;

    try {
      const data = await fetch("/api/library/recommendations").then(r => r.json());
      const recs = data.recommendations || [];

      if (!recs.length) {
        container.innerHTML = `<div class="no-data-msg">No recommendations generated yet. Log additional observations.</div>`;
        return;
      }

      container.innerHTML = recs.map(r => `
        <div class="rec-alert-card rec-type-${r.type}">
          <div class="rec-card-header">
            <span class="rec-category-badge">${r.category}</span>
            <span class="rec-tag-badge">${r.tag}</span>
          </div>
          <div class="rec-card-title">${r.title}</div>
          <div class="rec-card-desc">${r.description}</div>
          <div class="rec-card-action">💡 <strong>Action:</strong> ${r.action}</div>
        </div>
      `).join("");
    } catch (e) {
      console.warn("Failed to load recommendations:", e);
    }
  },

  showMsg(el, text, isError) {
    if (!el) return;
    el.textContent = text;
    el.className = "msg " + (isError ? "msg-error" : "msg-success");
    el.style.display = "block";
    setTimeout(() => { el.style.display = "none"; }, 5000);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  Lib.init();
});
