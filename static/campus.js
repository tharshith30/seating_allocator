/**
 * static/campus.js — Client-side controller for Campus Space & Facility Management.
 * Manages Classrooms, Auditoriums, and Facility Maintenance workflows.
 */

const Campus = {
  currentRole: sessionStorage.getItem("campus_role") || "staff",
  currentPin: sessionStorage.getItem("campus_pin") || "2345",

  init() {
    this.initRoleSelector();
    this.initSubTabs();
    this.initClassroomHandlers();
    this.initAuditoriumHandlers();
    this.initFacilityHandlers();
    this.updateRoleUI();
  },

  // ─── Role & Authorization Management ─────────────────────────────────────
  initRoleSelector() {
    const roleSelect = document.getElementById("campus-role-select");
    const pinInput = document.getElementById("campus-pin-input");
    const saveBtn = document.getElementById("campus-role-save-btn");

    if (roleSelect) roleSelect.value = this.currentRole;
    if (pinInput) pinInput.value = this.currentPin;

    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        this.currentRole = roleSelect.value;
        this.currentPin = pinInput.value.trim();
        sessionStorage.setItem("campus_role", this.currentRole);
        sessionStorage.setItem("campus_pin", this.currentPin);
        this.updateRoleUI();
        alert(`Switched active role to: ${this.currentRole.toUpperCase()}`);
      });
    }
  },

  updateRoleUI() {
    const roleBadge = document.getElementById("campus-active-role-badge");
    if (roleBadge) {
      roleBadge.textContent = "Role: " + this.currentRole.toUpperCase();
      roleBadge.className = "role-pill role-" + this.currentRole;
    }
    // Show/hide admin-specific action panels
    document.querySelectorAll(".admin-only").forEach(el => {
      if (this.currentRole === "admin") el.classList.remove("d-none");
      else el.classList.add("d-none");
    });
  },

  // ─── Sub-Tab Navigation ───────────────────────────────────────────────────
  initSubTabs() {
    document.querySelectorAll(".campus-sub-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".campus-sub-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".campus-view").forEach(v => v.classList.remove("active"));

        btn.classList.add("active");
        const target = btn.getAttribute("data-sub");
        const viewEl = document.getElementById(`campus-view-${target}`);
        if (viewEl) viewEl.classList.add("active");
      });
    });
  },

  // ─── Module 1: Classroom Management ───────────────────────────────────────
  initClassroomHandlers() {
    // Schedule Inspector dropdown
    const roomSelect = document.getElementById("cr-schedule-room-select");
    if (roomSelect) {
      roomSelect.addEventListener("change", () => {
        this.loadClassroomSchedule(roomSelect.value);
      });
      if (roomSelect.value) this.loadClassroomSchedule(roomSelect.value);
    }

    // Find Free Classrooms Form
    const freeForm = document.getElementById("cr-find-free-form");
    if (freeForm) {
      freeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const date = document.getElementById("ff-cr-date").value;
        const start = parseInt(document.getElementById("ff-cr-start").value, 10);
        const end = parseInt(document.getElementById("ff-cr-end").value, 10);
        const minCap = parseInt(document.getElementById("ff-cr-cap").value, 10) || 0;
        await this.findFreeClassrooms(date, start, end, minCap);
      });
    }

    // Classroom Booking Form
    const bookForm = document.getElementById("cr-booking-form");
    if (bookForm) {
      bookForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.submitClassroomBooking();
      });
    }

    // Timetable Import Form
    const importForm = document.getElementById("cr-import-form");
    if (importForm) {
      importForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.importTimetable(importForm);
      });
    }

    // Add Classroom Form & Auto-Capacity Calculator
    const benchesInput = document.getElementById("ac-benches");
    const capacityInput = document.getElementById("ac-capacity");
    if (benchesInput && capacityInput) {
      benchesInput.addEventListener("input", () => {
        const b = parseInt(benchesInput.value, 10);
        if (!isNaN(b) && b > 0) {
          capacityInput.value = b * 2;
        }
      });
    }

    const addCrForm = document.getElementById("add-classroom-form");
    if (addCrForm) {
      addCrForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.submitAddClassroom();
      });
    }
  },

  toggleAddClassroomForm() {
    const form = document.getElementById("add-classroom-form");
    if (!form) return;
    form.style.display = (form.style.display === "none") ? "block" : "none";
  },

  async submitAddClassroom() {
    const fb = document.getElementById("add-cr-feedback");
    fb.style.display = "block";
    fb.innerHTML = "Registering new classroom...";

    const payload = {
      id: document.getElementById("ac-room-id").value.trim().toUpperCase(),
      name: document.getElementById("ac-name").value.trim(),
      block: document.getElementById("ac-block").value,
      floor: parseInt(document.getElementById("ac-floor").value, 10) || 0,
      bench_count: parseInt(document.getElementById("ac-benches").value, 10) || 30,
      seating_capacity: parseInt(document.getElementById("ac-capacity").value, 10) || 60,
      room_type: document.getElementById("ac-type").value,
      has_projector: document.getElementById("ac-proj").checked,
      has_audio: document.getElementById("ac-audio").checked,
      has_ac: document.getElementById("ac-ac").checked,
      status: "available",
      pin: document.getElementById("ac-pin").value || this.currentPin
    };

    try {
      const res = await fetch("/api/campus/classrooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to register classroom");

      fb.innerHTML = `<span style="color:#2e7d32;font-weight:700">✅ ${escapeHtml(data.message)}</span>`;
      setTimeout(() => location.reload(), 1400);
    } catch (err) {
      fb.innerHTML = `<span style="color:#c62828;font-weight:700">❌ ${escapeHtml(err.message)}</span>`;
    }
  },

  async loadClassroomSchedule(roomId) {
    const container = document.getElementById("cr-schedule-grid-container");
    if (!container || !roomId) return;
    container.innerHTML = "<div class='loading-spinner'>Loading timetable matrix...</div>";

    try {
      const res = await fetch(`/api/campus/classrooms/${roomId}/schedule`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load schedule");

      const grid = data.schedule.grid;
      const days = data.schedule.days;
      let html = `<div style="overflow-x:auto"><table class="tt-grid-table"><thead><tr><th>Day</th>`;
      
      for (let s = 1; s <= 9; s++) {
        html += `<th>Slot ${s}${s === 5 ? ' (Lunch)' : ''}</th>`;
      }
      html += `</tr></thead><tbody>`;

      days.forEach(day => {
        html += `<tr><td class="tt-day-cell"><strong>${day}</strong></td>`;
        for (let s = 1; s <= 9; s++) {
          if (s === 5) {
            html += `<td class="tt-cell tt-lunch">Lunch Break</td>`;
          } else {
            const entry = grid[day] ? grid[day][s] : null;
            if (entry) {
              html += `<td class="tt-cell tt-occupied">
                <div class="tt-subj">${escapeHtml(entry.subject_code || entry.subject_name || "Lecture")}</div>
                <div class="tt-meta">${escapeHtml(entry.section || "")}</div>
              </td>`;
            } else {
              html += `<td class="tt-cell tt-free">Free</td>`;
            }
          }
        }
        html += `</tr>`;
      });
      html += `</tbody></table></div>`;
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<div class="error">❌ ${escapeHtml(err.message)}</div>`;
    }
  },

  async findFreeClassrooms(date, start, end, minCap) {
    const resultDiv = document.getElementById("ff-cr-results");
    if (!resultDiv) return;
    resultDiv.innerHTML = "Searching for free classrooms...";

    try {
      const res = await fetch("/api/campus/classrooms/find-available", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: date, slot_start: start, slot_end: end, min_capacity: minCap })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Search failed");

      if (data.count === 0) {
        resultDiv.innerHTML = `<div style="color:var(--text-muted);padding:10px 0">No classrooms free for Slot ${start}-${end} on ${date}.</div>`;
        return;
      }

      let html = `<div style="margin-top:12px;font-weight:600;color:var(--accent);margin-bottom:8px">Found ${data.count} Free Classrooms on ${date} (Slots ${start} to ${end}):</div>`;
      html += `<div class="free-cr-grid">`;
      data.available_classrooms.forEach(c => {
        html += `<div class="free-cr-chip" onclick="Campus.selectClassroomForBooking('${escapeHtml(c.id)}')">
          <div style="font-weight:700">${escapeHtml(c.id)}</div>
          <div style="font-size:0.78rem;color:var(--text-muted)">${c.seating_capacity} seats &bull; ${escapeHtml(c.room_type)}</div>
        </div>`;
      });
      html += `</div>`;
      resultDiv.innerHTML = html;
    } catch (err) {
      resultDiv.innerHTML = `<div class="error">❌ ${escapeHtml(err.message)}</div>`;
    }
  },

  selectClassroomForBooking(roomId) {
    const input = document.getElementById("cr-book-room-id");
    if (input) {
      input.value = roomId;
      input.scrollIntoView({ behavior: "smooth" });
      input.focus();
    }
  },

  async submitClassroomBooking() {
    const fb = document.getElementById("cr-book-feedback");
    fb.style.display = "block";
    fb.innerHTML = "Validating and reserving...";

    const payload = {
      classroom_id: document.getElementById("cr-book-room-id").value,
      booking_date: document.getElementById("cr-book-date").value,
      slot_start: parseInt(document.getElementById("cr-book-slot-start").value, 10),
      slot_end: parseInt(document.getElementById("cr-book-slot-end").value, 10),
      department: document.getElementById("cr-book-dept").value,
      booked_by: document.getElementById("cr-book-by").value,
      purpose: document.getElementById("cr-book-purpose").value,
      attendees: parseInt(document.getElementById("cr-book-attendees").value, 10) || 0,
      role: this.currentRole,
      pin: this.currentPin
    };

    try {
      const res = await fetch("/api/campus/classrooms/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Booking failed");

      fb.innerHTML = `<span style="color:#2e7d32;font-weight:700">✅ ${escapeHtml(data.message)}</span>`;
      setTimeout(() => location.reload(), 1400);
    } catch (err) {
      fb.innerHTML = `<span style="color:#c62828;font-weight:700">❌ ${escapeHtml(err.message)}</span>`;
    }
  },

  async importTimetable(formEl) {
    const fb = document.getElementById("cr-import-feedback");
    fb.style.display = "block";
    fb.innerHTML = "Parsing timetable workbook...";

    const formData = new FormData(formEl);
    formData.append("pin", this.currentPin);

    try {
      const res = await fetch("/api/campus/classrooms/import-timetable", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Import failed");

      fb.innerHTML = `<span style="color:#2e7d32;font-weight:700">✅ ${escapeHtml(data.message)}</span>`;
      setTimeout(() => location.reload(), 1500);
    } catch (err) {
      fb.innerHTML = `<span style="color:#c62828;font-weight:700">❌ ${escapeHtml(err.message)}</span>`;
    }
  },

  // ─── Module 2: Auditorium Management ─────────────────────────────────────
  initAuditoriumHandlers() {
    const reqForm = document.getElementById("aud-request-form");
    if (reqForm) {
      reqForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.submitEventRequest();
      });
    }

    // Event filter buttons
    document.querySelectorAll(".aud-filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".aud-filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const st = btn.getAttribute("data-status");
        this.filterEventsList(st);
      });
    });
  },

  async submitEventRequest() {
    const fb = document.getElementById("aud-req-feedback");
    fb.style.display = "block";
    fb.innerHTML = "Submitting event request...";

    const payload = {
      auditorium_id: document.getElementById("aud-req-id").value,
      event_title: document.getElementById("aud-req-title").value,
      event_type: document.getElementById("aud-req-type").value,
      department: document.getElementById("aud-req-dept").value,
      organizer_name: document.getElementById("aud-req-organizer").value,
      contact_email: document.getElementById("aud-req-email").value,
      event_date: document.getElementById("aud-req-date").value,
      start_time: document.getElementById("aud-req-start").value,
      end_time: document.getElementById("aud-req-end").value,
      expected_attendees: parseInt(document.getElementById("aud-req-attendees").value, 10) || 0,
      special_requirements: document.getElementById("aud-req-notes").value,
      pin: this.currentPin
    };

    try {
      const res = await fetch("/api/campus/auditoriums/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Submission failed");

      fb.innerHTML = `<span style="color:#2e7d32;font-weight:700">✅ ${escapeHtml(data.message)}</span>`;
      setTimeout(() => location.reload(), 1400);
    } catch (err) {
      fb.innerHTML = `<span style="color:#c62828;font-weight:700">❌ ${escapeHtml(err.message)}</span>`;
    }
  },

  async reviewEvent(eventId, action) {
    const remarks = prompt(`Enter administrative remarks for ${action.toUpperCase()}:`, "");
    if (remarks === null) return;

    try {
      const res = await fetch(`/api/campus/auditoriums/events/${eventId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, remarks: remarks, pin: this.currentPin, reviewed_by: "Campus Admin" })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Review failed");
      alert(data.message);
      location.reload();
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  },

  async openEventChecklistModal(eventId) {
    const modal = document.getElementById("aud-checklist-modal");
    const container = document.getElementById("aud-checklist-items-container");
    const titleEl = document.getElementById("aud-checklist-modal-title");
    if (!modal || !container) return;

    container.innerHTML = "Loading event readiness checklist...";
    modal.style.display = "flex";

    try {
      const res = await fetch(`/api/campus/auditoriums/events/${eventId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load event details");

      const ev = data.event;
      if (titleEl) titleEl.textContent = `Event Readiness Checklist: ${ev.event_title} (#EV-${ev.id})`;

      let html = `<div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:14px">
        Date: <strong>${ev.event_date}</strong> &bull; Time: <strong>${ev.start_time} - ${ev.end_time}</strong> &bull; Hall: <strong>${escapeHtml(ev.auditorium_name)}</strong>
      </div>`;

      html += `<div class="checklist-items-list">`;
      ev.checklist.forEach(item => {
        const isChecked = item.is_completed ? "checked" : "";
        html += `<label class="checklist-item-row">
          <input type="checkbox" ${isChecked} onchange="Campus.toggleChecklistItem(${ev.id}, '${item.item_key}', this.checked)">
          <div>
            <div style="font-weight:600">${escapeHtml(item.item_label)}</div>
            <div style="font-size:0.75rem;color:var(--text-muted)">Verified by: ${escapeHtml(item.verified_by || 'Pending verification')}</div>
          </div>
        </label>`;
      });
      html += `</div>`;
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<div class="error">❌ ${escapeHtml(err.message)}</div>`;
    }
  },

  async toggleChecklistItem(eventId, itemKey, isCompleted) {
    try {
      const res = await fetch(`/api/campus/auditoriums/events/${eventId}/checklist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_key: itemKey, is_completed: isCompleted, verified_by: this.currentRole.toUpperCase() + " Staff", pin: this.currentPin })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Checklist update failed");
    } catch (err) {
      alert(`Checklist error: ${err.message}`);
    }
  },

  closeChecklistModal() {
    const modal = document.getElementById("aud-checklist-modal");
    if (modal) modal.style.display = "none";
  },

  filterEventsList(status) {
    document.querySelectorAll(".aud-event-card").forEach(card => {
      if (!status || status === "all") {
        card.style.display = "block";
      } else {
        card.style.display = (card.getAttribute("data-status") === status) ? "block" : "none";
      }
    });
  },

  // ─── Module 3: Facility Management ───────────────────────────────────────
  initFacilityHandlers() {
    const tktForm = document.getElementById("fac-ticket-form");
    if (tktForm) {
      tktForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.submitMaintenanceTicket();
      });
    }

    // Priority filter for tickets
    document.querySelectorAll(".tkt-prio-filter").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tkt-prio-filter").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const prio = btn.getAttribute("data-prio");
        this.filterTickets(prio);
      });
    });
  },

  async submitMaintenanceTicket() {
    const fb = document.getElementById("fac-tkt-feedback");
    fb.style.display = "block";
    fb.innerHTML = "Logging maintenance request...";

    const payload = {
      location_type: document.getElementById("fac-loc-type").value,
      location_id: document.getElementById("fac-loc-id").value,
      category: document.getElementById("fac-cat").value,
      issue_title: document.getElementById("fac-title").value,
      description: document.getElementById("fac-desc").value,
      priority: document.getElementById("fac-prio").value,
      blocks_space: document.getElementById("fac-blocks").checked,
      reported_by: document.getElementById("fac-reporter").value,
      reported_by_role: this.currentRole === "admin" ? "Admin" : "Department Staff",
      pin: this.currentPin
    };

    try {
      const res = await fetch("/api/campus/facilities/tickets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Ticket creation failed");

      fb.innerHTML = `<span style="color:#2e7d32;font-weight:700">✅ ${escapeHtml(data.message)}</span>`;
      setTimeout(() => location.reload(), 1400);
    } catch (err) {
      fb.innerHTML = `<span style="color:#c62828;font-weight:700">❌ ${escapeHtml(err.message)}</span>`;
    }
  },

  async assignTicket(ticketNo) {
    const staff = prompt(`Assign technician for ticket ${ticketNo} (e.g. 'Ramesh - Electrician'):`);
    if (!staff) return;
    const estDate = prompt("Target completion date (YYYY-MM-DD):", new Date().toISOString().split("T")[0]);

    try {
      const res = await fetch(`/api/campus/facilities/tickets/${ticketNo}/assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assigned_to: staff, estimated_completion: estDate, pin: this.currentPin })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Assignment failed");
      alert(data.message);
      location.reload();
    } catch (err) {
      alert(`Assignment error: ${err.message}`);
    }
  },

  async updateTicketStatus(ticketNo, newStatus) {
    const notes = prompt(`Enter resolution / status notes for ticket ${ticketNo}:`, "");
    if (notes === null) return;

    try {
      const res = await fetch(`/api/campus/facilities/tickets/${ticketNo}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: newStatus,
          notes: notes,
          updated_by: this.currentRole.toUpperCase() + " User",
          role: this.currentRole === "maintenance" ? "Maintenance Staff" : "Admin",
          pin: this.currentPin
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Update failed");
      alert(data.message);
      location.reload();
    } catch (err) {
      alert(`Update error: ${err.message}`);
    }
  },

  async completePreventiveTask(pmId, title) {
    const notes = prompt(`Enter inspection remarks for '${title}':`, "Inspection complete. System functioning normally.");
    if (notes === null) return;

    try {
      const res = await fetch(`/api/campus/facilities/preventive/${pmId}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conducted_by: "Maintenance Staff", notes: notes, pin: this.currentPin })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "PM completion failed");
      alert(data.message);
      location.reload();
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  },

  filterTickets(priority) {
    document.querySelectorAll(".tkt-row").forEach(row => {
      if (!priority || priority === "all") {
        row.style.display = "";
      } else {
        row.style.display = (row.getAttribute("data-prio") === priority) ? "" : "none";
      }
    });
  }
};

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  Campus.init();
});

