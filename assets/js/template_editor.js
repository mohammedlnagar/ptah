(function () {
  "use strict";

  const root = document.getElementById("tpl-editor");
  if (!root) return;

  const nameInput = root.querySelector("[data-tpl-name]");
  const contentInput = root.querySelector("[data-tpl-content]");
  const purposeInput = document.getElementById("tpl-purpose");
  const preview = root.querySelector("[data-tpl-preview]");
  const saveBtn = root.querySelector("[data-tpl-save]");

  /* The sample patient from the handoff, so the operator can judge length and
     tone against realistic values rather than raw tokens. */
  const SAMPLE = {
    "#patient_name": "Layla",
    "#mrn": "448291",
    "#doctor": "Dr. Al-Rashid",
    "#department": "Cardiology",
    "#appointment_date": "14 Aug",
    "#appointment_time": "10:30",
    "#appointment_status": "Confirmed",
  };

  function renderPreview() {
    let text = contentInput.value;
    Object.keys(SAMPLE).forEach((token) => {
      text = text.split(token).join(SAMPLE[token]);
    });
    preview.textContent = text || "Your message will appear here.";
  }

  /* Save stays disabled until there is something to approve, which is the
     rule the approver relies on. */
  function syncSave() {
    const ready = nameInput.value.trim() && contentInput.value.trim();
    saveBtn.disabled = !ready;
  }

  function sync() {
    renderPreview();
    syncSave();
  }

  nameInput.addEventListener("input", syncSave);
  contentInput.addEventListener("input", sync);

  root.querySelectorAll("[data-purpose]").forEach((btn) =>
    btn.addEventListener("click", () => {
      root.querySelectorAll("[data-purpose]").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      purposeInput.value = btn.dataset.purpose;
    })
  );

  /* Tokens append at the caret rather than the end, so a placeholder can be
     dropped mid-sentence without retyping the rest. */
  root.querySelectorAll("[data-token]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const token = btn.dataset.token;
      const start = contentInput.selectionStart ?? contentInput.value.length;
      const end = contentInput.selectionEnd ?? contentInput.value.length;
      const value = contentInput.value;
      contentInput.value = value.slice(0, start) + token + value.slice(end);
      const caret = start + token.length;
      contentInput.setSelectionRange(caret, caret);
      contentInput.focus();
      sync();
    })
  );

  sync();
})();
