(function () {
  "use strict";

  /* Floating nav: collapse to icons once the page scrolls past 40px, keeping
     the active item's label so the current location stays readable. */
  const nav = document.getElementById("floatingNav");
  if (nav) {
    let collapsed = null;
    const sync = () => {
      const next = window.scrollY > 40;
      if (next === collapsed) return;
      collapsed = next;
      nav.classList.toggle("mini", next);
    };
    sync();
    window.addEventListener("scroll", sync, { passive: true });
  }

  /* Toasts: bottom-right dark pill with a mint check, ~2.6s. */
  window.showToast = function showToast(message) {
    const region = document.getElementById("toastRegion");
    if (!region) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<svg aria-hidden="true"><use href="#r-check"></use></svg><span></span>';
    toast.querySelector("span").textContent = message;
    region.appendChild(toast);
    window.setTimeout(() => toast.remove(), 2600);
  };

  /* Flash messages arrive as server-rendered markup; mirror them as toasts on
     screens that ask for it via data-toast, so actions like "profile saved"
     land in the same place as client-side confirmations. */
  document.querySelectorAll("[data-toast]").forEach((node) => {
    const text = node.getAttribute("data-toast");
    if (text) window.showToast(text);
  });
})();
