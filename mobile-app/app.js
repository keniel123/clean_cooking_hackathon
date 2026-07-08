const MOCK_USER = {
  id: "KC-2048",
  name: "Amina Njeri",
  electricityUsageKwh: 42.6,
  creditKes: 1250,
  profilePhotoUrl: "assets/profile-photo.svg",
};

/*
  Placeholder hourly tariffs.
  These can later be replaced with AI, grid, battery, or tariff-service output.
*/
let HOURLY_TARIFFS = Array.from({ length: 24 }, (_, hour) => {
  if (hour >= 10 && hour <= 15) {
    return { hour, level: "low", rateKesPerKwh: 15 };
  }

  if ((hour >= 6 && hour <= 9) || (hour >= 16 && hour <= 17) || hour === 23) {
    return { hour, level: "medium", rateKesPerKwh: 25 };
  }

  if (hour >= 18 && hour <= 22) {
    return { hour, level: "high", rateKesPerKwh: 38 };
  }

  return { hour, level: "low", rateKesPerKwh: 17 };
});

const selectedHours = new Set();
let currentPage = 0;
let availableTariffs = [];

const elements = {
  userId: document.querySelector("#userId"),
  userName: document.querySelector("#userName"),
  electricityUsage: document.querySelector("#electricityUsage"),
  creditBalance: document.querySelector("#creditBalance"),
  profilePhoto: document.querySelector("#profilePhoto"),
  profileButton: document.querySelector("#profileButton"),

  timeTrack: document.querySelector("#timeTrack"),
  previousButton: document.querySelector("#previousButton"),
  nextButton: document.querySelector("#nextButton"),
  pageIndicator: document.querySelector("#pageIndicator"),
  remainingHoursText: document.querySelector("#remainingHoursText"),

  selectionSummary: document.querySelector("#selectionSummary"),
  clearButton: document.querySelector("#clearButton"),
  goButton: document.querySelector("#goButton"),

  resultsModal: document.querySelector("#resultsModal"),
  closeModalButton: document.querySelector("#closeModalButton"),
  doneButton: document.querySelector("#doneButton"),
  selectedResults: document.querySelector("#selectedResults"),
  recommendationTitle: document.querySelector("#recommendationTitle"),
  recommendationText: document.querySelector("#recommendationText"),
  resultBadge: document.querySelector("#resultBadge"),

  toast: document.querySelector("#toast"),
};

let lastFocusedElement = null;

function formatHourParts(hour) {
  const normalizedHour = hour % 24;
  const period = normalizedHour < 12 ? "AM" : "PM";
  const number = normalizedHour % 12 || 12;

  return {
    number,
    period,
    full: `${number}:00 ${period}`,
  };
}

function formatTimeRange(hour) {
  const start = formatHourParts(hour).full;
  const end = formatHourParts((hour + 1) % 24).full;
  return `${start}–${end}`;
}

function formatKes(value) {
  return new Intl.NumberFormat("en-KE", {
    maximumFractionDigits: 0,
  }).format(value);
}

function getVisibleCount() {
  if (window.innerWidth <= 360) {
    return 2;
  }

  if (window.innerWidth >= 420) {
    return 4;
  }

  return 3;
}

function getCurrentHour() {
  return new Date().getHours();
}

function getTariff(hour) {
  return HOURLY_TARIFFS.find((item) => item.hour === hour);
}

function getCostLabel(level) {
  return {
    low: "Lower cost",
    medium: "Average cost",
    high: "Peak cost",
  }[level];
}

function setUserData(user) {
  elements.userId.textContent = user.id;
  elements.userName.textContent = user.name;
  elements.electricityUsage.textContent = Number(
    user.electricityUsageKwh
  ).toFixed(1);
  elements.creditBalance.textContent = formatKes(user.creditKes);
  elements.profilePhoto.src =
    user.profilePhotoUrl || "assets/profile-photo.svg";
  elements.profilePhoto.alt = `${user.name}'s profile`;
}

function setHourlyTariffs(tariffs) {
  const isValid =
    Array.isArray(tariffs) &&
    tariffs.length === 24 &&
    tariffs.every(
      (item, index) =>
        item.hour === index &&
        ["low", "medium", "high"].includes(item.level) &&
        Number.isFinite(Number(item.rateKesPerKwh))
    );

  if (!isValid) {
    throw new Error(
      "Tariffs must contain 24 ordered hourly items with hour, level, and rateKesPerKwh."
    );
  }

  HOURLY_TARIFFS = tariffs.map((item) => ({
    ...item,
    rateKesPerKwh: Number(item.rateKesPerKwh),
  }));

  buildAvailableTariffs();
  renderTimeSlots();
}

function buildAvailableTariffs() {
  const currentHour = getCurrentHour();

  availableTariffs = HOURLY_TARIFFS.filter(
    (tariff) => tariff.hour >= currentHour
  );

  if (availableTariffs.length === 0) {
    availableTariffs = [getTariff(23)];
  }

  const validHours = new Set(
    availableTariffs.map((item) => item.hour)
  );

  [...selectedHours].forEach((hour) => {
    if (!validHours.has(hour)) {
      selectedHours.delete(hour);
    }
  });

  currentPage = 0;

  elements.remainingHoursText.textContent =
    `${availableTariffs.length} hour${
      availableTariffs.length === 1 ? "" : "s"
    } remaining today`;
}

function renderTimeSlots() {
  const currentHour = getCurrentHour();
  elements.timeTrack.innerHTML = "";

  availableTariffs.forEach((tariff) => {
    const parts = formatHourParts(tariff.hour);
    const button = document.createElement("button");

    button.type = "button";
    button.className = `time-slot ${tariff.level}`;
    button.dataset.hour = String(tariff.hour);
    button.setAttribute(
      "aria-pressed",
      String(selectedHours.has(tariff.hour))
    );
    button.setAttribute(
      "aria-label",
      `${formatTimeRange(tariff.hour)}, ${getCostLabel(
        tariff.level
      )}, KES ${tariff.rateKesPerKwh} per kWh`
    );

    button.innerHTML = `
      ${
        tariff.hour === currentHour
          ? '<span class="now-badge">Now</span>'
          : ""
      }
      <span class="time-number">${parts.number}:00</span>
      <span class="time-period">${parts.period}</span>
      <span class="time-cost">${getCostLabel(tariff.level)}</span>
    `;

    button.addEventListener("click", () => {
      toggleHour(tariff.hour);
    });

    elements.timeTrack.appendChild(button);
  });

  updateCarousel();
  updateSelectionUI();
}

function toggleHour(hour) {
  if (selectedHours.has(hour)) {
    selectedHours.delete(hour);
  } else {
    selectedHours.add(hour);
  }

  updateSelectionUI();
}

function updateSelectionUI() {
  document.querySelectorAll(".time-slot").forEach((button) => {
    const hour = Number(button.dataset.hour);
    button.setAttribute(
      "aria-pressed",
      String(selectedHours.has(hour))
    );
  });

  const ordered = [...selectedHours].sort((a, b) => a - b);

  if (ordered.length === 0) {
    elements.selectionSummary.textContent =
      "No cooking hours selected.";
  } else {
    const firstThree = ordered
      .slice(0, 3)
      .map((hour) => formatHourParts(hour).full)
      .join(", ");

    const remaining = ordered.length - 3;

    elements.selectionSummary.textContent =
      `${ordered.length} hour${
        ordered.length === 1 ? "" : "s"
      } selected: ${firstThree}${
        remaining > 0 ? ` and ${remaining} more` : ""
      }.`;
  }

  elements.goButton.disabled = ordered.length === 0;
}

function getPageCount() {
  return Math.max(
    1,
    Math.ceil(availableTariffs.length / getVisibleCount())
  );
}

function updateCarousel() {
  const visibleCount = getVisibleCount();
  const pageCount = getPageCount();

  currentPage = Math.min(currentPage, pageCount - 1);

  const offsetPercent = currentPage * 100;
  const gapOffset = currentPage * visibleCount * 8;

  elements.timeTrack.style.transform =
    `translateX(calc(-${offsetPercent}% - ${gapOffset}px))`;

  elements.previousButton.disabled = currentPage === 0;
  elements.nextButton.disabled =
    currentPage >= pageCount - 1;

  elements.pageIndicator.textContent =
    `${currentPage + 1} / ${pageCount}`;
}

function goToPreviousPage() {
  if (currentPage > 0) {
    currentPage -= 1;
    updateCarousel();
  }
}

function goToNextPage() {
  if (currentPage < getPageCount() - 1) {
    currentPage += 1;
    updateCarousel();
  }
}

function renderResults() {
  const orderedHours = [...selectedHours].sort(
    (a, b) => a - b
  );

  elements.selectedResults.innerHTML = "";

  orderedHours.forEach((hour) => {
    const tariff = getTariff(hour);
    const row = document.createElement("article");

    row.className = "result-row";
    row.innerHTML = `
      <span class="result-time">${formatTimeRange(hour)}</span>
      <span class="cost-label ${tariff.level}">
        ${getCostLabel(tariff.level)}
      </span>
      <span class="result-price">
        KES ${formatKes(tariff.rateKesPerKwh)}
        <small>per kWh</small>
      </span>
    `;

    elements.selectedResults.appendChild(row);
  });

  updateRecommendation(orderedHours);
}

function updateRecommendation(orderedHours) {
  const selectedTariffs = orderedHours.map(getTariff);

  const lowSelections = selectedTariffs.filter(
    (tariff) => tariff.level === "low"
  );

  const highSelections = selectedTariffs.filter(
    (tariff) => tariff.level === "high"
  );

  const cheapestAvailable = [...availableTariffs].sort(
    (a, b) => a.rateKesPerKwh - b.rateKesPerKwh
  )[0];

  if (lowSelections.length === selectedTariffs.length) {
    elements.recommendationTitle.textContent =
      "Good choice";

    elements.recommendationText.textContent =
      "All your selected hours are in a lower-cost period.";

    elements.resultBadge.textContent =
      "Best cost zone";

    return;
  }

  if (lowSelections.length > 0) {
    const cheapestSelected = [...lowSelections].sort(
      (a, b) => a.rateKesPerKwh - b.rateKesPerKwh
    )[0];

    elements.recommendationTitle.textContent =
      `${formatTimeRange(
        cheapestSelected.hour
      )} is your cheapest selected hour`;

    elements.recommendationText.textContent =
      "Your selection includes a mixture of lower, average, or peak-cost hours.";

    elements.resultBadge.textContent =
      "Mixed costs";

    return;
  }

  if (highSelections.length === selectedTariffs.length) {
    elements.recommendationTitle.textContent =
      "Your selected hours are peak-cost";

    elements.recommendationText.textContent =
      `For a cheaper option, consider ${formatTimeRange(
        cheapestAvailable.hour
      )}.`;

    elements.resultBadge.textContent =
      "Peak cost";

    return;
  }

  elements.recommendationTitle.textContent =
    "A cheaper time is available";

  elements.recommendationText.textContent =
    `The cheapest remaining option today is ${formatTimeRange(
      cheapestAvailable.hour
    )}.`;

  elements.resultBadge.textContent =
    "Alternative found";
}

function openResultsModal() {
  renderResults();

  lastFocusedElement = document.activeElement;

  elements.resultsModal.classList.remove("is-hidden");
  document.body.classList.add("modal-open");

  window.setTimeout(() => {
    elements.closeModalButton.focus();
  }, 20);
}

function closeResultsModal() {
  elements.resultsModal.classList.add("is-hidden");
  document.body.classList.remove("modal-open");

  if (
    lastFocusedElement &&
    typeof lastFocusedElement.focus === "function"
  ) {
    lastFocusedElement.focus();
  }
}

function clearSelection() {
  selectedHours.clear();
  updateSelectionUI();
  closeResultsModal();
  showToast("Cooking-hour selection cleared.");
}

function trapModalFocus(event) {
  if (
    event.key !== "Tab" ||
    elements.resultsModal.classList.contains("is-hidden")
  ) {
    return;
  }

  const focusable = elements.resultsModal.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );

  if (!focusable.length) {
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (
    event.shiftKey &&
    document.activeElement === first
  ) {
    event.preventDefault();
    last.focus();
  } else if (
    !event.shiftKey &&
    document.activeElement === last
  ) {
    event.preventDefault();
    first.focus();
  }
}

let toastTimer;

function showToast(message) {
  window.clearTimeout(toastTimer);

  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");

  toastTimer = window.setTimeout(() => {
    elements.toast.classList.remove("is-visible");
  }, 2200);
}

elements.previousButton.addEventListener(
  "click",
  goToPreviousPage
);

elements.nextButton.addEventListener(
  "click",
  goToNextPage
);

elements.goButton.addEventListener(
  "click",
  openResultsModal
);

elements.closeModalButton.addEventListener(
  "click",
  closeResultsModal
);

elements.doneButton.addEventListener(
  "click",
  closeResultsModal
);

elements.resultsModal.addEventListener(
  "click",
  (event) => {
    if (event.target === elements.resultsModal) {
      closeResultsModal();
    }
  }
);

elements.clearButton.addEventListener(
  "click",
  clearSelection
);

elements.profileButton.addEventListener(
  "click",
  () => {
    showToast(
      "Profile editing will be connected to the user service later."
    );
  }
);

document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    !elements.resultsModal.classList.contains("is-hidden")
  ) {
    closeResultsModal();
  }

  trapModalFocus(event);
});

window.addEventListener("resize", updateCarousel);

window.GridCookUI = {
  setUserData,
  setHourlyTariffs,
  getSelectedHours: () =>
    [...selectedHours].sort((a, b) => a - b),
  refreshRemainingHours: () => {
    buildAvailableTariffs();
    renderTimeSlots();
  },
};

setUserData(MOCK_USER);
buildAvailableTariffs();
renderTimeSlots();
