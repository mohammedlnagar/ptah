(function () {
  "use strict";

  const sidebar = document.getElementById("primary-sidebar");
  const scrim = document.querySelector(".sidebar-scrim");
  const openButton = document.querySelector("[data-sidebar-open]");
  const closeButtons = document.querySelectorAll("[data-sidebar-close]");

  function setSidebar(open) {
    if (!sidebar || !scrim) return;
    sidebar.classList.toggle("is-open", open);
    scrim.classList.toggle("is-open", open);
    openButton?.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
  }

  openButton?.addEventListener("click", () => setSidebar(true));
  closeButtons.forEach((button) => button.addEventListener("click", () => setSidebar(false)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setSidebar(false);
  });

  window.showToast = function showToast(message, type = "info") {
    const region = document.getElementById("toastRegion");
    if (!region) return;

    const toast = document.createElement("div");
    toast.className = `app-toast app-toast--${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", type === "success" ? "#icon-check" : "#icon-info");
    icon.appendChild(use);

    const copy = document.createElement("span");
    copy.textContent = message;
    toast.append(icon, copy);
    region.appendChild(toast);
    window.setTimeout(() => toast.remove(), 4500);
  };
})();
