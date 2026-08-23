(() => {
  "use strict";

  const providerGrid = document.getElementById("providerGrid");
  const searchInput = document.getElementById("providerSearch");
  const emptyState = document.getElementById("providerEmptyState");
  const filterButtons = Array.from(
    document.querySelectorAll("[data-provider-filter]"),
  );

  if (!providerGrid || !searchInput || !emptyState || filterButtons.length === 0) {
    return;
  }

  let activeFilter = "all";
  let scheduled = false;

  const countAll = document.getElementById("providerCountAll");
  const countConfigured = document.getElementById("providerCountConfigured");
  const countSetup = document.getElementById("providerCountSetup");

  function cards() {
    return Array.from(providerGrid.querySelectorAll(".provider-card"));
  }

  function cardState(card) {
    const pill = card.querySelector(".status-pill");
    return pill?.classList.contains("ok") ? "configured" : "setup";
  }

  function normalizedSearch() {
    return searchInput.value.trim().toLocaleLowerCase();
  }

  function updateCounts(providerCards) {
    const configured = providerCards.filter(
      (card) => cardState(card) === "configured",
    ).length;
    countAll.textContent = String(providerCards.length);
    countConfigured.textContent = String(configured);
    countSetup.textContent = String(providerCards.length - configured);
  }

  function applyFilter() {
    scheduled = false;
    const query = normalizedSearch();
    const providerCards = cards();
    let visible = 0;

    updateCounts(providerCards);

    for (const card of providerCards) {
      const stateMatches =
        activeFilter === "all" || cardState(card) === activeFilter;
      const searchMatches =
        query.length === 0 || card.textContent.toLocaleLowerCase().includes(query);
      const show = stateMatches && searchMatches;
      card.hidden = !show;
      if (show) visible += 1;
    }

    emptyState.hidden = visible !== 0;
  }

  function scheduleFilter() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(applyFilter);
  }

  searchInput.addEventListener("input", scheduleFilter);

  for (const button of filterButtons) {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.providerFilter || "all";
      for (const candidate of filterButtons) {
        const selected = candidate === button;
        candidate.classList.toggle("active", selected);
        candidate.setAttribute("aria-pressed", String(selected));
      }
      scheduleFilter();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target?.isContentEditable
    ) {
      return;
    }
    event.preventDefault();
    searchInput.focus();
  });

  const observer = new MutationObserver(scheduleFilter);
  observer.observe(providerGrid, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });

  scheduleFilter();
})();
