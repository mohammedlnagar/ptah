(function () {
  "use strict";

  const modal = document.getElementById("wizard");
  if (!modal) return;

  const form = document.getElementById("wizard-form");
  const fileInput = form.querySelector('input[type="file"]');
  const dropzone = document.getElementById("wizard-drop");
  const fileOk = document.getElementById("wizard-file");
  const errorBox = document.getElementById("wizard-error");
  const nameInput = document.getElementById("wiz-name");
  const purposeInput = document.getElementById("wiz-purpose");
  const templateInput = document.getElementById("wiz-template");
  const preview = document.getElementById("wiz-preview");
  const statRows = document.getElementById("wiz-stat-rows");
  const statFile = document.getElementById("wiz-stat-file");

  const steps = Array.from(form.querySelectorAll("[data-wiz-step]"));
  const bars = Array.from(modal.querySelectorAll("[data-wiz-bar]"));
  const backBtn = form.querySelector("[data-wiz-back]");
  const nextBtn = form.querySelector("[data-wiz-next]");
  const launchBtn = form.querySelector("[data-wiz-launch]");

  let step = 1;

  function render() {
    steps.forEach((s) => { s.hidden = Number(s.dataset.wizStep) !== step; });
    bars.forEach((b) => { b.classList.toggle("done", Number(b.dataset.wizBar) <= step); });
    backBtn.hidden = step === 1;
    nextBtn.hidden = step === 3;
    launchBtn.hidden = step !== 3;
  }

  function setError(message) {
    errorBox.textContent = message || "";
    errorBox.hidden = !message;
  }

  function open() {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    step = 1;
    render();
    setError("");
  }

  function close() {
    modal.hidden = true;
    document.body.style.overflow = "";
  }

  document.querySelectorAll("[data-wizard-open]").forEach((b) =>
    b.addEventListener("click", open)
  );
  modal.querySelectorAll("[data-wizard-close]").forEach((b) =>
    b.addEventListener("click", close)
  );
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) close();
  });

  /* Step 1: file selection, including drag and drop onto the zone. */
  function showFile(file) {
    if (!file) { fileOk.hidden = true; return; }
    fileOk.querySelector("span").textContent = file.name +
      " · " + Math.max(1, Math.round(file.size / 1024)) + " KB · ready";
    fileOk.hidden = false;
    statFile.textContent = "CSV";
    if (!nameInput.value) {
      nameInput.value = file.name.replace(/\.csv$/i, "").replace(/[_-]+/g, " ");
    }
  }

  /* First data row of the chosen file, used only to make the step 3 preview
     concrete. The server does the authoritative render at import; this is a
     display approximation, so anything it cannot map is left as-is. */
  let firstRow = null;

  function splitCsvLine(line) {
    const out = [];
    let value = "";
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (quoted && ch === '"' && line[i + 1] === '"') { value += '"'; i += 1; }
      else if (ch === '"') quoted = !quoted;
      else if (ch === "," && !quoted) { out.push(value); value = ""; }
      else value += ch;
    }
    out.push(value);
    return out.map((v) => v.trim());
  }

  function readFirstRow(file) {
    const reader = new FileReader();
    reader.onload = () => {
      const lines = String(reader.result)
        .split(/\r?\n/)
        .filter((l) => l.trim().length);
      if (lines.length < 2) return;
      const header = splitCsvLine(lines[0]).map((h) => h.toLowerCase());
      const cells = splitCsvLine(lines[1]);
      const at = (name) => {
        const i = header.indexOf(name.toLowerCase());
        return i === -1 ? "" : cells[i] || "";
      };
      const stamp = at("Appointment Date/Time");
      const [datePart, timePart] = stamp.split(/\s+/);
      firstRow = {
        "#patient_name": (at("Patient Name").split(/\s+/)[0] || ""),
        "#mrn": at("MR No."),
        "#doctor": at("Consultant"),
        "#department": at("Doctor Department"),
        "#appointment_status": at("Appointment Status"),
        "#appointment_date": datePart || "",
        "#appointment_time": timePart || "",
      };
      statRows.textContent = String(lines.length - 1);
      renderPreview();
    };
    reader.readAsText(file);
  }

  function renderPreview() {
    const chosen = form.querySelector("[data-template].on");
    if (!chosen) return;
    let text = chosen.dataset.preview || "";
    if (firstRow) {
      Object.keys(firstRow).forEach((token) => {
        if (firstRow[token]) text = text.split(token).join(firstRow[token]);
      });
    }
    preview.textContent = text;
  }

  fileInput.addEventListener("change", () => {
    showFile(fileInput.files[0]);
    if (fileInput.files[0]) readFirstRow(fileInput.files[0]);
  });
  ["dragenter", "dragover"].forEach((type) =>
    dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-over");
    })
  );
  ["dragleave", "drop"].forEach((type) =>
    dropzone.addEventListener(type, () => dropzone.classList.remove("is-over"))
  );
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    fileInput.files = e.dataTransfer.files;
    showFile(file);
    readFirstRow(file);
  });

  /* Step 2: purpose and template. Templates whose purpose conflicts with the
     chosen one are disabled rather than hidden, so the operator can see the
     whole library and why a row is unavailable. */
  function syncTemplates() {
    const chosen = purposeInput.value;
    form.querySelectorAll("[data-template]").forEach((row) => {
      const p = row.dataset.templatePurpose;
      const usable = p === chosen || p === "general";
      row.disabled = !usable;
      row.style.opacity = usable ? "" : ".45";
      if (!usable && row.classList.contains("on")) {
        row.classList.remove("on");
        templateInput.value = "";
      }
    });
  }

  form.querySelectorAll("[data-purpose]").forEach((btn) =>
    btn.addEventListener("click", () => {
      form.querySelectorAll("[data-purpose]").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      purposeInput.value = btn.dataset.purpose;
      syncTemplates();
    })
  );

  form.querySelectorAll("[data-template]").forEach((btn) =>
    btn.addEventListener("click", () => {
      form.querySelectorAll("[data-template]").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      templateInput.value = btn.dataset.template;
      renderPreview();
    })
  );
  syncTemplates();

  /* Navigation, with the validation each step actually needs. */
  nextBtn.addEventListener("click", () => {
    if (step === 1) {
      if (!fileInput.files.length) return setError("Choose a CSV file to continue.");
      if (!nameInput.value.trim()) return setError("Give the campaign a name.");
    }
    if (step === 2 && !templateInput.value) {
      return setError("Choose an approved template.");
    }
    setError("");
    step = Math.min(3, step + 1);
    render();
  });

  backBtn.addEventListener("click", () => {
    setError("");
    step = Math.max(1, step - 1);
    render();
  });

  /* The endpoint answers JSON, so submit in the background and jump straight
     into the new campaign's send queue on success. */
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");
    launchBtn.disabled = true;
    launchBtn.textContent = "Preparing…";
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.success && data.campaign_id) {
        window.location.href = form.dataset.queueUrl
          ? form.dataset.queueUrl.replace("0", data.campaign_id)
          : "/Rasel/list/" + data.campaign_id + "/";
        return;
      }
      const errors = data.errors
        ? Object.values(data.errors).flat().map((e) => e.message || e).join(" ")
        : "";
      setError(data.message || errors || "That upload could not be processed.");
    } catch (err) {
      setError("Upload failed. Check your connection and try again.");
    }
    launchBtn.disabled = false;
    launchBtn.textContent = "Launch campaign →";
  });

  render();
})();
