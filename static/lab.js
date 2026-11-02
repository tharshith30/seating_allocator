/**
 * lab.js — Frontend logic for the Lab Utilization and Booking pages.
 *
 * Architecture: vanilla JS with fetch(). No framework dependencies.
 * All state is kept in module-level variables and refreshed on user action.
 *
 * Dark mode: toggled by setting data-theme="dark" on <html>.
 * The CSS does the rest via custom properties.
 */

// ─── Utilities ───────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);
const qsa = sel => document.querySelectorAll(sel);

function apiGet(url) {
  return fetch(url).then(r => r.json());
}

function apiPost(url, body, pin) {
  const headers = { "Content-Type": "application/json" };
  if (pin) headers["X-Pin"] = pin;
  return fetch(url, { method: "POST", headers, body: JSON.stringify(body) }).then(r => r.json());
}

function apiDelete(url, body, pin) {
  const headers = { "Content-Type": "application/json" };
  if (pin) headers["X-Pin"] = pin;
  return fetch(url, { method: "DELETE", headers, body: JSON.stringify(body) }).then(r => r.json());
}

function showMsg(el, text, isError) {
  if (!el) return;
  el.textContent = text;
  el.className = "msg " + (isError ? "msg-error" : "msg-success");
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 6000);
}

function isoDateToMonday(iso) {
  const d = new Date(iso);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
}

function addWeeks(iso, n) {
  const d = new Date(iso);
  d.setDate(d.getDate() + 7 * n);
  return d.toISOString().slice(0, 10);
}

function formatWeek(monday) {
  const d = new Date(monday);
  const fri = new Date(monday);
  fri.setDate(fri.getDate() + 4);
  return `${d.toLocaleDateString()} – ${fri.toLocaleDateString()}`;
}

// ─── Dark mode ───────────────────────────────────────────────────────────────

function initDarkMode() {
  const btn = $("dark-toggle");
  if (!btn) return;
  const stored = localStorage.getItem("lab-theme") || "light";
  document.documentElement.setAttribute("data-theme", stored);
  btn.textContent = stored === "dark" ? "☀ Light" : "🌙 Dark";
  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("lab-theme", next);
    btn.textContent = next === "dark" ? "☀ Light" : "🌙 Dark";
  });
}

// ─── DASHBOARD PAGE ──────────────────────────────────────────────────────────

async function initDashboard() {
  initDarkMode();
  await loadAnalytics();
  initFreeFinder();
  initForecastEditor();
}

async function loadAnalytics() {
  const data = await apiGet("/api/analytics");
  renderLabCards(data);
  renderHeatmap(data, Object.keys(data)[0]);
  initHeatmapSelector(data);
}

function statusClass(status) {
  return { "Healthy": "status-healthy", "Underused": "status-underused",
           "Overloaded": "status-overloaded", "No data": "status-nodata" }[status] || "";
}

function renderLabCards(data) {
  const grid = $("lab-cards");
  if (!grid) return;
  grid.innerHTML = "";

  for (const [id, info] of Object.entries(data)) {
    const card = document.createElement("div");
    card.className = "lab-card";
    if (!info.has_data) {
      card.innerHTML = `
        <div class="card-header"><span class="lab-id">${id}</span>
          <span class="status-badge status-nodata">No data</span></div>
        <div class="card-name">${info.lab_name}</div>
        <div class="card-body">
          <div class="no-data-msg">No timetable data available for this lab.</div>
        </div>`;
    } else {
      card.innerHTML = `
        <div class="card-header">
          <span class="lab-id">${id}</span>
          <span class="status-badge ${statusClass(info.status)}">${info.status}</span>
        </div>
        <div class="card-name">${info.lab_name}</div>
        <div class="card-body">
          <div class="metric"><span class="metric-label">Utilization</span>
            <span class="metric-value">${info.utilization_pct}%</span></div>
          <div class="util-bar"><div class="util-fill" style="width:${info.utilization_pct}%"></div></div>
          <div class="metric"><span class="metric-label">Booked / Free</span>
            <span class="metric-value">${info.booked_count} / ${info.free_count}</span></div>
          <div class="metric"><span class="metric-label">Avg Seat Fill</span>
            <span class="metric-value">${info.avg_fill_pct}%</span></div>
          <div class="metric"><span class="metric-label">Over-Capacity Sessions</span>
            <span class="metric-value ${info.over_cap_count > 0 ? 'over-cap' : ''}">${info.over_cap_count}</span></div>
        </div>`;
    }
    card.addEventListener("click", () => {
      qsa(".lab-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      renderHeatmap(data, id);
    });
    grid.appendChild(card);
  }
  // Activate first card
  const first = grid.querySelector(".lab-card");
  if (first) first.click();
}

function initHeatmapSelector(data) {
  const sel = $("heatmap-lab-select");
  if (!sel) return;
  sel.innerHTML = "";
  for (const [id, info] of Object.entries(data)) {
    if (!info.has_data) continue;
    const opt = document.createElement("option");
    opt.value = id; opt.textContent = `${id} — ${info.lab_name}`;
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => renderHeatmap(data, sel.value));
}

const SLOT_LABELS = ["S1","S2","S3","S4","S5(L)","S6","S7","S8","S9"];
const DAY_LABELS  = ["Mon","Tue","Wed","Thu","Fri"];

function renderHeatmap(data, labId) {
  const info = data[labId];
  const container = $("heatmap-container");
  if (!container || !info || !info.has_data || !info.heatmap) {
    if (container) container.innerHTML = `<div class="no-data-msg">No heatmap data.</div>`;
    return;
  }
  const sel = $("heatmap-lab-select");
  if (sel) sel.value = labId;

  let html = `<table class="heatmap-table"><thead><tr><th>Day</th>`;
  SLOT_LABELS.forEach(s => html += `<th>${s}</th>`);
  html += `</tr></thead><tbody>`;

  info.heatmap.forEach((row, di) => {
    html += `<tr><td class="day-label">${DAY_LABELS[di]}</td>`;
    row.forEach((cell, si) => {
      const cls = `hm-cell hm-${cell.state}`;
      const tip = cell.sessions.length
        ? cell.sessions.map(s => `${s.section}: ${s.course} (${s.strength} students, ${s.occupancy_pct}% fill)`).join("\n")
        : (cell.state === "lunch" ? "Lunch break" : "Free");
      html += `<td class="${cls}" title="${tip}">${cell.sessions.length || ""}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;

  // Forecast
  if (info.forecast) {
    html += `<div class="forecast-section">
      <h4>📊 Rule-Based Forecast <small style="font-weight:normal;font-size:0.8em">(not ML — multiplicative model)</small></h4>
      <table class="forecast-table"><thead>
        <tr><th>Week Type</th><th>Baseline Slots</th><th>Attendance</th><th>Week Factor</th><th>Predicted Slots</th><th>Predicted %</th></tr>
      </thead><tbody>`;
    const weekTypes = $("forecast-week-types");
    info.forecast.forEach(row => {
      html += `<tr class="fc-${row.week_type}">
        <td><strong>${row.week_type}</strong></td>
        <td>${row.baseline_slots}</td>
        <td>${row.attendance_factor}</td>
        <td>${row.week_factor}</td>
        <td>${row.predicted_slots}</td>
        <td>${row.predicted_pct}%</td>
      </tr>`;
    });
    html += `</tbody></table></div>`;
  }

  // Free slots
  if (info.free_slots) {
    html += `<div class="free-slots-list"><strong>Free Slots:</strong> `;
    html += info.free_slots.map(f => `<span class="free-slot-tag">${f.day} S${f.slot}</span>`).join(" ");
    html += `</div>`;
  }

  container.innerHTML = html;
}

function initFreeFinder() {
  const form = $("free-finder-form");
  if (!form) return;
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const day = $("ff-day").value;
    const slot = $("ff-slot").value;
    const res = await apiGet(`/api/free_labs?day=${day}&slot=${slot}`);
    const out = $("free-finder-result");
    if (res.free_labs && res.free_labs.length) {
      out.innerHTML = `<strong>Free labs:</strong> ${res.free_labs.join(", ")}`;
    } else {
      out.innerHTML = `<em>No labs free at ${day} S${slot} (from timetable).</em>`;
    }
  });
}

function initForecastEditor() {
  // Allow changing forecast week-type overrides (client-side display only)
  // A full implementation would POST to the server; here we just re-render
}

// ─── BOOKING PAGE ─────────────────────────────────────────────────────────────

let selectedLab = null;
let currentWeek = null;
let selectedSlots = [];  // [{day, slot}]
let allLabs = [];

async function initBooking() {
  initDarkMode();

  // Load lab list
  allLabs = await apiGet("/api/labs");
  populateLabSelect();

  // Week navigation
  currentWeek = isoDateToMonday(new Date().toISOString().slice(0,10));
  updateWeekDisplay();

  $("prev-week").addEventListener("click", () => {
    currentWeek = addWeeks(currentWeek, -1);
    updateWeekDisplay();
    loadGrid();
  });
  $("next-week").addEventListener("click", () => {
    currentWeek = addWeeks(currentWeek, 1);
    updateWeekDisplay();
    loadGrid();
  });

  // Lab select
  $("lab-select").addEventListener("change", () => {
    selectedLab = $("lab-select").value;
    selectedSlots = [];
    if (selectedLab) loadGrid();
  });

  // Booking form
  const bookForm = $("booking-form");
  if (bookForm) bookForm.addEventListener("submit", handleBookSubmit);

  // In-charge panel
  const applyBtn = $("apply-state-btn");
  if (applyBtn) applyBtn.addEventListener("click", handleApplyState);

  // Cancel button (for selected booking)
  const cancelBookBtn = $("cancel-booking-btn");
  if (cancelBookBtn) cancelBookBtn.addEventListener("click", handleCancelBooking);

  // Smart suggest
  const suggestForm = $("suggest-form");
  if (suggestForm) suggestForm.addEventListener("submit", handleSuggest);

  // Batch
  const batchPreviewBtn = $("batch-preview-btn");
  if (batchPreviewBtn) batchPreviewBtn.addEventListener("click", () => handleBatch(true));
  const batchCommitBtn = $("batch-commit-btn");
  if (batchCommitBtn) batchCommitBtn.addEventListener("click", () => handleBatch(false));

  // Book from suggestion
  document.addEventListener("click", e => {
    if (e.target.classList.contains("book-suggestion-btn")) {
      const s = JSON.parse(e.target.dataset.suggestion);
      autoFillBookingForm(s);
    }
  });

  // Add lab form
  initAddLab();
}

function initAddLab() {
  const form = $("add-lab-form");
  if (!form) return;
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const id = $("new-lab-id").value.trim().toUpperCase();
    const name = $("new-lab-name").value.trim();
    const location = $("new-lab-location").value.trim();
    const capacity = parseInt($("new-lab-capacity").value, 10);
    const pin = $("new-lab-pin").value.trim() || "1234";
    const msgEl = $("add-lab-msg");

    try {
      const res = await apiPost("/api/labs/add", { id, name, location, capacity, pin }, pin);
      if (res.success) {
        showMsg(msgEl, res.message, false);
        form.reset();
        const pinInput = $("new-lab-pin");
        if (pinInput) pinInput.value = "1234";

        // Refresh allLabs and dropdown in booking
        allLabs = await apiGet("/api/labs");
        populateLabSelect();

        // Switch to the newly created lab in booking view
        const labSel = $("lab-select");
        if (labSel) {
          labSel.value = id;
          selectedLab = id;
          selectedSlots = [];
          loadGrid();
        }

        // Also reload analytics dashboard cards if present
        if (typeof loadAnalytics === "function") {
          loadAnalytics();
        }
      } else {
        showMsg(msgEl, res.error || "Failed to add lab", true);
      }
    } catch (err) {
      showMsg(msgEl, "Network error adding lab: " + err, true);
    }
  });
}

function populateLabSelect() {
  const sel = $("lab-select");
  sel.innerHTML = `<option value="">-- Select Lab --</option>`;
  allLabs.forEach(lab => {
    const opt = document.createElement("option");
    opt.value = lab.id;
    opt.textContent = `${lab.id} — ${lab.name}`;
    sel.appendChild(opt);
  });
}

function updateWeekDisplay() {
  const el = $("week-display");
  if (el) el.textContent = `Week of ${formatWeek(currentWeek)}`;
}

function slotLabel(slot) {
  return slot === 5 ? "S5 (Lunch)" : `S${slot}`;
}

const STATE_ICONS = {
  empty: "✓", in_use: "⬛", maintenance: "🔧", booked: "📌", lunch: "🍽", exam: "📝"
};

async function loadGrid() {
  if (!selectedLab) return;
  const data = await apiGet(`/api/week?lab=${selectedLab}&week=${currentWeek}`);
  renderGrid(data.grid);
  await loadBookingsList();
}

function renderGrid(grid) {
  const container = $("week-grid");
  if (!container) return;

  let html = `<table class="week-table"><thead><tr><th>Day</th>`;
  for (let s = 1; s <= 9; s++) html += `<th>${slotLabel(s)}</th>`;
  html += `</tr></thead><tbody>`;

  grid.forEach((row, di) => {
    html += `<tr><td class="day-label">${DAY_LABELS[di]}</td>`;
    row.forEach(cell => {
      const cls = `wk-cell wk-${cell.state}`;
      const selected = selectedSlots.some(s => s.day === cell.day && s.slot === cell.slot);
      const selClass = selected ? " wk-selected" : "";
      const tip = cell.booking
        ? `${cell.booking.name} (${cell.booking.role}) — ${cell.booking.purpose} [${cell.booking.group_size} people]`
        : cell.state;
      const clickable = cell.state === "empty" || cell.state === "booked" ? "wk-clickable" : "";
      html += `<td class="${cls}${selClass} ${clickable}" 
                   data-day="${cell.day}" data-slot="${cell.slot}"
                   data-state="${cell.state}" title="${tip}">
                 ${STATE_ICONS[cell.state] || ""}
               </td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;
  container.innerHTML = html;

  // Attach click handlers
  container.querySelectorAll(".wk-clickable").forEach(cell => {
    cell.addEventListener("click", () => toggleSlotSelection(cell));
  });
}

function toggleSlotSelection(cell) {
  const day = cell.dataset.day;
  const slot = parseInt(cell.dataset.slot);
  const idx = selectedSlots.findIndex(s => s.day === day && s.slot === slot);
  if (idx >= 0) {
    selectedSlots.splice(idx, 1);
    cell.classList.remove("wk-selected");
  } else {
    selectedSlots.push({ day, slot });
    cell.classList.add("wk-selected");
  }
  updateSelectionDisplay();
}

function updateSelectionDisplay() {
  const el = $("selected-slots-display");
  if (!el) return;
  if (!selectedSlots.length) {
    el.textContent = "No slots selected";
  } else {
    el.textContent = selectedSlots.map(s => `${s.day} S${s.slot}`).join(", ");
  }
}

async function handleBookSubmit(e) {
  e.preventDefault();
  const msg = $("book-msg");
  if (!selectedLab) return showMsg(msg, "Select a lab first.", true);
  if (!selectedSlots.length) return showMsg(msg, "Select at least one slot.", true);

  // Group by day (all selected slots must be same day for one booking)
  const days = [...new Set(selectedSlots.map(s => s.day))];
  if (days.length > 1) return showMsg(msg, "All selected slots must be on the same day.", true);

  const day = days[0];
  const slots = selectedSlots.filter(s => s.day === day).map(s => s.slot);

  const body = {
    lab: selectedLab,
    week: currentWeek,
    day,
    slots,
    name: $("book-name").value,
    role: $("book-role").value,
    purpose: $("book-purpose").value,
    group_size: parseInt($("book-size").value),
  };

  const res = await apiPost("/api/book", body);
  if (res.ok) {
    showMsg(msg, `Booked! IDs: ${res.booking_ids.join(", ")}`, false);
    selectedSlots = [];
    loadGrid();
  } else {
    showMsg(msg, res.error || "Booking failed.", true);
  }
}

async function handleApplyState() {
  if (!selectedSlots.length) return alert("Select slots to apply state.");
  const pin = $("incharge-pin").value;
  const state = $("incharge-state").value;
  const note = $("incharge-note").value;

  const days = [...new Set(selectedSlots.map(s => s.day))];
  for (const day of days) {
    for (const { slot } of selectedSlots.filter(s => s.day === day)) {
      const res = await apiPost("/api/status", {
        lab: selectedLab, week: currentWeek, day, slot, state, note,
      }, pin);
      if (res.error) {
        alert(`Error on ${day} S${slot}: ${res.error}`);
        return;
      }
    }
  }
  selectedSlots = [];
  loadGrid();
}

async function handleCancelBooking() {
  const bookingId = $("cancel-booking-id").value;
  if (!bookingId) return alert("Enter a booking ID to cancel.");
  const pin = $("incharge-pin").value || null;
  const name = $("cancel-name").value || "";
  const res = await apiDelete(`/api/book/${bookingId}`, { name }, pin);
  const msg = $("book-msg");
  if (res.ok) {
    showMsg(msg, "Booking cancelled.", false);
    loadGrid();
    loadBookingsList();
  } else {
    showMsg(msg, res.error || "Cancel failed.", true);
  }
}

async function loadBookingsList() {
  if (!selectedLab) return;
  const rows = await apiGet(`/api/bookings?lab=${selectedLab}&week=${currentWeek}`);
  const el = $("bookings-list");
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = `<em>No bookings this week.</em>`; return;
  }
  let html = `<table class="bookings-table"><thead>
    <tr><th>ID</th><th>Day</th><th>Slot</th><th>Name</th><th>Role</th><th>Purpose</th><th>Size</th></tr>
  </thead><tbody>`;
  rows.forEach(b => {
    html += `<tr>
      <td>${b.id}</td><td>${b.day}</td><td>S${b.slot}</td>
      <td>${b.name}</td><td>${b.role}</td><td>${b.purpose}</td><td>${b.group_size}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  el.innerHTML = html;
}

async function handleSuggest(e) {
  e.preventDefault();
  const group_size = parseInt($("sg-size").value);
  const n_consecutive = parseInt($("sg-consecutive").value);
  const pref_day = $("sg-day").value || undefined;
  const pref_slot = $("sg-slot").value ? parseInt($("sg-slot").value) : undefined;
  const include_unverified = $("sg-unverified").checked;

  const body = { group_size, n_consecutive, week: currentWeek,
                 preferred_day: pref_day, preferred_slot: pref_slot, include_unverified };
  const results = await apiPost("/api/smart/suggest", body);
  renderSuggestions(results);
}

function renderSuggestions(results) {
  const el = $("suggest-results");
  if (!el) return;
  if (!results.length) {
    el.innerHTML = `<div class="no-data-msg">No options found. Ask the in-charge to mark slots Empty.</div>`;
    return;
  }
  let html = `<div class="suggestions">`;
  results.forEach((r, i) => {
    html += `<div class="suggestion-card">
      <div class="sug-rank">#${i+1} — Score: ${r.score}</div>
      <div class="sug-detail">${r.lab_name} | ${r.day} | Slots: ${r.slots.map(s=>`S${s}`).join(", ")}</div>
      <ul class="sug-reasons">${r.reasons.map(x=>`<li>${x}</li>`).join("")}</ul>
      <button class="book-suggestion-btn btn-sm" data-suggestion='${JSON.stringify(r)}'>Book This →</button>
    </div>`;
  });
  html += `</div>`;
  el.innerHTML = html;
}

function autoFillBookingForm(s) {
  // Auto-select the lab and slots
  const labSel = $("lab-select");
  if (labSel) { labSel.value = s.lab; labSel.dispatchEvent(new Event("change")); }
  setTimeout(() => {
    selectedSlots = s.slots.map(slot => ({ day: s.day, slot }));
    loadGrid().then(updateSelectionDisplay);
  }, 500);
}

async function handleBatch(dry_run) {
  const textarea = $("batch-textarea");
  if (!textarea || !textarea.value.trim()) return alert("Enter batch requests first.");

  const pin = dry_run ? null : ($("batch-pin").value || null);
  const include_unverified = $("batch-unverified") ? $("batch-unverified").checked : false;

  // Parse each line: "name,role,group_size,n_consecutive,purpose[,preferred_day][,preferred_slot]"
  let requests;
  try {
    requests = parseBatchText(textarea.value);
  } catch (err) {
    return alert("Parse error: " + err.message);
  }

  const body = { requests, week: currentWeek, dry_run, include_unverified };
  const res = await apiPost("/api/smart/batch", body, pin);
  renderBatchResult(res);
}

function parseBatchText(text) {
  const lines = text.split("\n").map(l => l.trim()).filter(l => l && !l.startsWith("#"));
  return lines.map((line, i) => {
    const parts = line.split(",").map(p => p.trim());
    if (parts.length < 5) throw new Error(`Line ${i+1}: need at least 5 fields (name,role,size,consecutive,purpose)`);
    const [name, role, group_size, n_consecutive, purpose, preferred_day, preferred_slot] = parts;
    if (!["student","faculty"].includes(role)) throw new Error(`Line ${i+1}: role must be student or faculty`);
    return {
      name, role,
      group_size: parseInt(group_size),
      n_consecutive: parseInt(n_consecutive),
      purpose,
      preferred_day: preferred_day || undefined,
      preferred_slot: preferred_slot ? parseInt(preferred_slot) : undefined,
    };
  });
}

function renderBatchResult(res) {
  const el = $("batch-results");
  if (!el) return;
  let html = `<div class="batch-summary">
    <strong>Seat Efficiency: ${res.seat_efficiency_pct}%</strong>
    ${res.committed ? " ✅ Committed" : (res.dry_run ? " 🔍 Dry Run" : "")}
  </div>`;
  if (res.allocated.length) {
    html += `<h4>Allocated (${res.allocated.length})</h4><ul class="batch-list">`;
    res.allocated.forEach(a => {
      html += `<li>✅ ${a.name} → ${a.lab} ${a.day} Slots ${a.slots.map(s=>`S${s}`).join(",")}</li>`;
    });
    html += `</ul>`;
  }
  if (res.unallocated.length) {
    html += `<h4>Unallocated (${res.unallocated.length})</h4><ul class="batch-list batch-unalloc">`;
    res.unallocated.forEach(u => {
      html += `<li>❌ ${u.name} — ${u.reason}</li>`;
    });
    html += `</ul>`;
  }
  el.innerHTML = html;
}

// ─── Auto-init ────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  if ($("lab-cards")) initDashboard();
  if ($("week-grid")) initBooking();
});
