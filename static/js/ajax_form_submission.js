document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  const campaignForm = document.getElementById("appointmentListForm");
  const templateForm = document.getElementById("messageTemplateForm");

  function csrfToken() {
    return document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || "";
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-error-for]").forEach((element) => { element.textContent = ""; });
  }

  function showErrors(form, errors) {
    Object.entries(errors || {}).forEach(([field, messages]) => {
      const target = form.querySelector(`[data-error-for="${field}"]`);
      if (target) target.textContent = messages.map((item) => item.message).join(" ");
    });
  }

  async function submitForm({ form, type, button, loadingLabel }) {
    clearErrors(form);
    const initialLabel = button.innerHTML;
    button.disabled = true;
    button.textContent = loadingLabel;

    const body = new FormData(form);
    body.append("form_type", type);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        showErrors(form, result.errors);
        window.showToast?.(result.message || "Please correct the highlighted fields.", "error");
        return;
      }

      window.showToast?.(result.message, "success");
      form.reset();
      if (result.campaign_id) {
        window.setTimeout(() => { window.location.href = `/Rasel/list/${result.campaign_id}/`; }, 450);
      } else {
        window.setTimeout(() => window.location.reload(), 650);
      }
    } catch (error) {
      console.error("Form submission failed", error);
      window.showToast?.("The request could not be completed. Please try again.", "error");
    } finally {
      button.disabled = false;
      button.innerHTML = initialLabel;
    }
  }

  campaignForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitForm({ form: campaignForm, type: "appointments_list", button: document.getElementById("listSubmitButton"), loadingLabel: "Validating CSV…" });
  });

  templateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitForm({ form: templateForm, type: "message_template", button: document.getElementById("messageSubmitButton"), loadingLabel: "Saving draft…" });
  });
});
