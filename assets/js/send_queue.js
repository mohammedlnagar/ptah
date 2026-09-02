(function () {
  "use strict";

  const root = document.getElementById("queue");
  if (!root) return;

  const SENT = root.dataset.sentValue;
  const statusUrl = root.dataset.statusUrl;
  const editUrl = root.dataset.editUrl;
  const csrf = root.querySelector('[name="csrfmiddlewaretoken"]').value;

  const split = root.querySelector("[data-queue-split]");
  const rows = Array.from(root.querySelectorAll("[data-row]"));
  const card = root.querySelector("[data-current]");
  const editor = root.querySelector("[data-editor]");
  const editorInput = root.querySelector("[data-editor-input]");
  const bubble = root.querySelector("[data-cur-bubble]");
  const waModal = document.getElementById("wa-handoff");
  const summaryModal = document.getElementById("session-summary");

  const searchInput = root.querySelector("[data-filter-search]");
  const doctorChips = Array.from(root.querySelectorAll("[data-filter-doctor]"));
  const statusChips = Array.from(root.querySelectorAll("[data-filter-status]"));

  let visible = rows.slice();
  let index = 0;
  let filters = { search: "", doctor: "", status: "" };
  /* Counters for the summary modal: this session's work, not campaign totals. */
  let session = { sent: 0, skipped: 0 };
  let summaryShown = false;

  const focusKey = "waslni.focus." + window.location.pathname;
  let focusMode = false;
  try { focusMode = localStorage.getItem(focusKey) === "1"; } catch (e) { focusMode = false; }

  /* ---------------------------------------------------------------- filters */

  function matches(row) {
    if (filters.doctor && row.dataset.doctor !== filters.doctor) return false;
    if (filters.status && row.dataset.status !== filters.status) return false;
    if (filters.search && !row.dataset.search.includes(filters.search)) return false;
    return true;
  }

  function applyFilters(keepSelection) {
    const previous = visible[index];
    visible = rows.filter(matches);
    rows.forEach((row) => { row.hidden = !matches(row); });
    root.querySelector("[data-shown-count]").textContent = String(visible.length);
    const next = keepSelection ? visible.indexOf(previous) : -1;
    select(next >= 0 ? next : 0, { silent: true });
  }

  searchInput.addEventListener("input", () => {
    filters.search = searchInput.value.trim().toLowerCase();
    applyFilters(false);
  });

  doctorChips.forEach((chip) =>
    chip.addEventListener("click", () => {
      const value = chip.dataset.filterDoctor;
      filters.doctor = filters.doctor === value ? "" : value;
      doctorChips.forEach((c) => c.classList.toggle("on", c.dataset.filterDoctor === filters.doctor));
      applyFilters(false);
    })
  );

  statusChips.forEach((chip) =>
    chip.addEventListener("click", () => {
      filters.status = chip.dataset.filterStatus;
      statusChips.forEach((c) => c.classList.toggle("on", c === chip));
      applyFilters(false);
    })
  );

  /* -------------------------------------------------------------- selection */

  function statusLabel(row) {
    const s = row.dataset.status;
    if (s === SENT) return "✓ sent";
    if (s === "skipped") return "skipped";
    if (s === "opened") return "opened";
    return row.dataset.time || "—";
  }

  function paintRow(row) {
    const s = row.dataset.status;
    const cell = row.querySelector(".qrow__status");
    cell.textContent = statusLabel(row);
    cell.classList.toggle("is-sent", s === SENT);
    cell.classList.toggle("is-skipped", s === "skipped");
    row.classList.toggle("done", s === SENT || s === "skipped");
  }

  function select(i, options) {
    const opts = options || {};
    if (!visible.length) {
      card.hidden = true;
      root.querySelector("[data-queue-position]").textContent = "Nothing to send";
      return;
    }
    index = Math.max(0, Math.min(visible.length - 1, i));
    const row = visible[index];
    card.hidden = false;
    rows.forEach((r) => r.classList.toggle("on", r === row));

    const position = (index + 1) + " of " + visible.length;
    root.querySelector("[data-queue-position]").textContent = "Message " + position;
    root.querySelector("[data-cur-position]").textContent = position;
    root.querySelector("[data-cur-patient]").textContent = row.dataset.patient;

    const meta = ["MRN " + row.dataset.mrn, row.dataset.phone, row.dataset.doctorName];
    if (row.dataset.date) meta.push(row.dataset.date);
    if (row.dataset.time) meta.push(row.dataset.time);
    root.querySelector("[data-cur-meta]").textContent = meta.filter(Boolean).join(" · ");

    const appt = root.querySelector("[data-cur-appt]");
    if (row.dataset.apptLabel) {
      appt.hidden = false;
      appt.textContent = row.dataset.apptLabel;
      appt.className = "appt-pill " + apptClass(row.dataset.apptStatus);
    } else {
      appt.hidden = true;
    }

    root.querySelector("[data-cur-message]").textContent = row.dataset.message;
    root.querySelector("[data-open-wa]").href = row.dataset.waUrl;
    root.querySelector("[data-cur-stamp]").textContent =
      (row.dataset.status === SENT ? "sent ✓" : row.dataset.time || "") + "";

    cancelEdit();
    if (!opts.silent) row.scrollIntoView({ block: "nearest" });
  }

  function apptClass(status) {
    if (status === "confirmed") return "badge--success";
    if (status === "cancelled") return "badge--danger";
    if (status === "booked") return "badge--info";
    return "badge--muted";
  }

  rows.forEach((row, i) =>
    row.addEventListener("click", () => select(visible.indexOf(row) >= 0 ? visible.indexOf(row) : i))
  );

  /* --------------------------------------------------------------- counters */

  function refreshCounts() {
    const count = (s) => rows.filter((r) => r.dataset.status === s).length;
    const sent = count(SENT);
    const skipped = count("skipped");
    const pending = rows.filter((r) => r.dataset.status === "pending" || r.dataset.status === "opened").length;
    root.querySelector("[data-count-sent]").textContent = String(sent);
    root.querySelector("[data-count-skipped]").textContent = String(skipped);
    root.querySelector("[data-count-pending]").textContent = String(pending);
    const total = rows.length || 1;
    root.querySelector("[data-progress]").style.width = Math.round((sent / total) * 100) + "%";
  }

  /* Advance to the next item still needing work, which is what makes the
     queue feel like a queue rather than a list. */
  function advance() {
    const next = visible.findIndex(
      (r, i) => i > index && r.dataset.status !== SENT && r.dataset.status !== "skipped"
    );
    if (next >= 0) return select(next);
    const anyPending = visible.findIndex(
      (r) => r.dataset.status !== SENT && r.dataset.status !== "skipped"
    );
    if (anyPending >= 0) return select(anyPending);
    showSummary();
  }

  function showSummary() {
    if (summaryShown || !visible.length) return;
    summaryShown = true;
    summaryModal.querySelector("[data-summary-sent]").textContent = String(session.sent);
    summaryModal.querySelector("[data-summary-skipped]").textContent = String(session.skipped);
    summaryModal.hidden = false;
  }

  async function setStatus(row, status) {
    const body = new URLSearchParams({ message_id: row.dataset.row, status: status });
    try {
      const response = await fetch(statusUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrf,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: body,
      });
      if (!response.ok) throw new Error("status " + response.status);
      row.dataset.status = status;
      paintRow(row);
      refreshCounts();
      return true;
    } catch (err) {
      window.showToast && window.showToast("Could not update that message.");
      return false;
    }
  }

  /* ------------------------------------------------------------------ edit */

  function startEdit() {
    if (!visible.length) return;
    editor.hidden = false;
    bubble.hidden = true;
    editorInput.value = visible[index].dataset.message;
    editorInput.focus();
  }

  function cancelEdit() {
    editor.hidden = true;
    bubble.hidden = false;
  }

  root.querySelector("[data-edit-start]").addEventListener("click", startEdit);
  root.querySelector("[data-editor-cancel]").addEventListener("click", cancelEdit);

  root.querySelector("[data-editor-save]").addEventListener("click", async () => {
    const row = visible[index];
    const text = editorInput.value.trim();
    if (!text) return;
    const body = new URLSearchParams({ message_id: row.dataset.row, new_message: text });
    try {
      const response = await fetch(editUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrf,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: body,
      });
      if (!response.ok) throw new Error("save failed");
      row.dataset.message = text;
      root.querySelector("[data-cur-message]").textContent = text;
      cancelEdit();
      window.showToast && window.showToast("Message updated");
    } catch (err) {
      window.showToast && window.showToast("Could not save that edit.");
    }
  });

  /* ------------------------------------------------------- WhatsApp handoff */

  const openLink = root.querySelector("[data-open-wa]");
  openLink.addEventListener("click", () => {
    const row = visible[index];
    if (!row) return;
    /* The link itself opens wa.me in a new tab and the server records the
       "opened" transition; this panel only collects the confirmation. */
    if (row.dataset.status === "pending") {
      row.dataset.status = "opened";
      paintRow(row);
      refreshCounts();
    }
    waModal.querySelector("[data-wa-initial]").textContent = (row.dataset.patient || "?").slice(0, 1).toUpperCase();
    waModal.querySelector("[data-wa-patient]").textContent = row.dataset.patient;
    waModal.querySelector("[data-wa-phone]").textContent = row.dataset.phone;
    waModal.querySelector("[data-wa-message]").textContent = row.dataset.message;
    waModal.hidden = false;
  });

  waModal.querySelectorAll("[data-wa-close]").forEach((b) =>
    b.addEventListener("click", () => { waModal.hidden = true; })
  );
  waModal.addEventListener("click", (e) => { if (e.target === waModal) waModal.hidden = true; });

  waModal.querySelector("[data-wa-confirm]").addEventListener("click", async () => {
    const row = visible[index];
    waModal.hidden = true;
    if (await setStatus(row, SENT)) {
      session.sent += 1;
      window.showToast && window.showToast("Marked as sent");
      advance();
    }
  });

  root.querySelector("[data-skip]").addEventListener("click", async () => {
    const row = visible[index];
    if (!row) return;
    if (await setStatus(row, "skipped")) {
      session.skipped += 1;
      advance();
    }
  });

  root.querySelector("[data-prev]").addEventListener("click", () => select(index - 1));
  root.querySelector("[data-next]").addEventListener("click", () => select(index + 1));

  summaryModal.addEventListener("click", (e) => { if (e.target === summaryModal) summaryModal.hidden = true; });

  /* ------------------------------------------------------------ focus mode */

  function applyFocus() {
    split.classList.toggle("focus", focusMode);
    const btn = root.querySelector("[data-focus-toggle]");
    btn.innerHTML = (focusMode ? "Exit focus" : "Focus mode") + ' <span class="kbd">F</span>';
    try { localStorage.setItem(focusKey, focusMode ? "1" : "0"); } catch (e) { /* private mode */ }
  }

  root.querySelector("[data-focus-toggle]").addEventListener("click", () => {
    focusMode = !focusMode;
    applyFocus();
  });

  /* -------------------------------------------------------------- shortcuts */

  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || event.target.isContentEditable;
    const modalOpen = !waModal.hidden || !summaryModal.hidden;

    if (event.key === "Escape") {
      if (!waModal.hidden) waModal.hidden = true;
      else if (!summaryModal.hidden) summaryModal.hidden = true;
      else if (!editor.hidden) cancelEdit();
      return;
    }
    if (typing || modalOpen) return;

    switch (event.key) {
      case "Enter":
        event.preventDefault();
        openLink.click();
        break;
      case "s": case "S":
        event.preventDefault();
        root.querySelector("[data-skip]").click();
        break;
      case "e": case "E":
        event.preventDefault();
        startEdit();
        break;
      case "f": case "F":
        event.preventDefault();
        focusMode = !focusMode;
        applyFocus();
        break;
      case "ArrowRight": case "ArrowDown":
        event.preventDefault();
        select(index + 1);
        break;
      case "ArrowLeft": case "ArrowUp":
        event.preventDefault();
        select(index - 1);
        break;
      default:
        break;
    }
  });

  /* ------------------------------------------------------------------ init */

  rows.forEach(paintRow);
  refreshCounts();
  applyFocus();
  applyFilters(false);
})();
