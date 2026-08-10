document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  const csrfToken = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || "";

  async function postForm(url, data) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": csrfToken,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: new URLSearchParams(data),
    });
    if (!response.ok) {
      let message = "The update could not be saved.";
      try { message = (await response.json()).message || message; } catch (_) { /* HTML error response */ }
      throw new Error(message);
    }
    return response.json();
  }

  document.querySelectorAll(".save-message").forEach((button) => {
    button.addEventListener("click", async () => {
      const item = button.closest("[data-work-item]");
      const textarea = item.querySelector(".message-content");
      const state = item.querySelector(".save-state");
      const original = button.innerHTML;
      button.disabled = true;
      button.textContent = "Saving…";
      state.textContent = "Saving your edit…";
      try {
        await postForm("/Rasel/EditMessage/", { message_id: button.dataset.messageId, new_message: textarea.value });
        state.textContent = "Saved just now.";
        window.showToast?.("Message edit saved.", "success");
      } catch (error) {
        state.textContent = "Edit not saved.";
        window.showToast?.(error.message, "error");
      } finally {
        button.disabled = false;
        button.innerHTML = original;
      }
    });
  });

  document.querySelectorAll(".message-status").forEach((select) => {
    select.addEventListener("change", async () => {
      const previous = select.dataset.previous || "pending";
      select.disabled = true;
      try {
        await postForm("/Rasel/update-message-status/", { message_id: select.dataset.messageId, status: select.value });
        select.dataset.previous = select.value;
        window.showToast?.("Message status updated.", "success");
      } catch (error) {
        select.value = previous;
        window.showToast?.(error.message, "error");
      } finally { select.disabled = false; }
    });
    select.dataset.previous = select.value;
  });

  document.querySelectorAll(".appointment-status").forEach((select) => {
    select.addEventListener("change", async () => {
      const previous = select.dataset.previous;
      select.disabled = true;
      try {
        await postForm(select.dataset.url, { status: select.value });
        select.dataset.previous = select.value;
        window.showToast?.("Appointment status updated.", "success");
      } catch (error) {
        select.value = previous;
        window.showToast?.(error.message, "error");
      } finally { select.disabled = false; }
    });
    select.dataset.previous = select.value;
  });

  document.querySelectorAll(".open-whatsapp").forEach((link) => {
    link.addEventListener("click", () => {
      const item = link.closest("[data-work-item]");
      const status = item?.querySelector(".message-status");
      if (status && status.value === "pending") {
        status.value = "opened";
        status.dataset.previous = "opened";
      }
      window.showToast?.("WhatsApp opened in a new tab. Return here to mark the result.", "success");
    });
  });
});
