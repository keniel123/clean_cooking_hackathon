/*
  GridCook mobile UI prototype

  Integration points:
  1. Replace MOCK_USER with data returned by the user/database service.
  2. Replace HOURLY_TARIFFS with output from the AI/tariff/mini-grid service.
  3. Call setUserData(...) and setHourlyTariffs(...) after your API requests.
*/

const MOCK_USER = {
  id: "KC-2048",
  name: "Amina Njeri",
  electricityUsageKwh: 42.6,
  creditKes: 1250,
  profilePhotoUrl: "assets/profile-photo.svg",
};

/*
  Placeholder tariff schedule.
  level must be: "low", "medium", or "high".
  rateKesPerKwh is shown for transparency in the prototype.
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
let resultsVisible = false;

const elements = {
  userId: document.querySelector("#userId"),
  userName: document.querySelector("#userName"),
  electricityUsage: document.querySelector("#electricityUsage"),
  creditBalance: document.querySelector("#creditBalance"),
  profilePhoto: document.querySelector("#profilePhoto"),
  profileButton: document.querySelector("#profileButton"),
  timeGrid: document.querySelector("#timeGrid"),
  selectionSummary: document.querySelector("#selectionSummary"),
  clearButton: document.querySelector("#clearButton"),
  goButton: document.querySelector("#goButton"),
  resultsCard: document.querySelector("#resultsCard"),
  selectedResults: document.querySelector("#selectedResults"),
  recommendationTitle: document.querySelector("#recommendationTitle"),
  recommendationText: document.querySelector("#recommendationText"),
  resultBadge: document.querySelector("#resultBadge"),
  toast: document.querySelector("#toast"),
};

function formatHour(hour) {
  const normalizedHour = hour % 24;
  const suffix = normalizedHour < 12 ? "AM" : "PM";
  const displayHour = normalizedHour % 12 || 12;
  return `${displayHour}:00 ${suffix}`;
}

function formatTimeRange(hour) {
  return `${formatHour(hour)}–${formatHour((hour + 1) % 24)}`;
}

function formatKes(value) {
  return new Intl.NumberFormat("en-KE", {
    maximumFractionDigits: 0,
  }).format(value);
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

/*
  Public integration helper.
  Future API code can call:
  window.GridCookUI.setUserData(apiUser);
*/
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

  if (resultsVisible) {
    applyCostColours();
    renderResults();
  }
}

function createTimeSlots() {
  elements.timeGrid.innerHTML = "";

  HOURLY_TARIFFS.forEach(({ hour }) => {
    const button = document.createElement("button");
    button.className = "time-slot";
    button.type = "button";
    button.dataset.hour = String(hour);
    button.setAttribute("aria-pressed", "false");
    button.setAttribute(
      "aria-label",
      `Select ${formatTimeRange(hour)} for cooking`
    );
    button.textContent = formatHour(hour);

    button.addEventListener("click", () => {
      toggleHour(hour);
    });

    elements.timeGrid.appendChild(button);
  });
}

function toggleHour(hour) {
  if (selectedHours.has(hour)) {
    selectedHours.delete(hour);
  } else {
    selectedHours.add(hour);
  }

  updateSelectedState();
  updateSelectionSummary();

  if (resultsVisible) {
    renderResults();
  }
}

function updateSelectedState() {
  document.querySelectorAll(".time-slot").forEach((button) => {
    const hour = Number(button.dataset.hour);
    const isSelected = selectedHours.has(hour);
    button.setAttribute("aria-pressed", String(isSelected));
  });

  elements.goButton.disabled = selectedHours.size === 0;
}

function updateSelectionSummary() {
  const count = selectedHours.size;

  if (count === 0) {
    elements.selectionSummary.textContent = "No time slots selected.";
    return;
  }

  const orderedHours = [...selectedHours].sort((a, b) => a - b);
  const firstThree = orderedHours.slice(0, 3).map(formatHour).join(", ");
  const extraCount = Math.max(0, count - 3);
  const extraText = extraCount ? ` and ${extraCount} more` : "";

  elements.selectionSummary.textContent =
    `${count} slot${count === 1 ? "" : "s"} selected: ${firstThree}${extraText}.`;
}

function getTariff(hour) {
  return HOURLY_TARIFFS.find((item) => item.hour === hour);
}

function applyCostColours() {
  document.querySelectorAll(".time-slot").forEach((button) => {
    const hour = Number(button.dataset.hour);
    const tariff = getTariff(hour);

    button.classList.remove("cost-low", "cost-medium", "cost-high");
    button.classList.add(`cost-${tariff.level}`);

    button.setAttribute(
      "aria-label",
      `${formatTimeRange(hour)}: ${tariff.level} cost, ` +
        `KES ${tariff.rateKesPerKwh} per kWh. ` +
        `${selectedHours.has(hour) ? "Selected" : "Not selected"}.`
    );
  });
}

function renderResults() {
  const orderedHours = [...selectedHours].sort((a, b) => a - b);
  elements.selectedResults.innerHTML = "";

  if (orderedHours.length === 0) {
    hideResults();
    return;
  }

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

function getCostLabel(level) {
  return {
    low: "Lower cost",
    medium: "Average cost",
    high: "Peak cost",
  }[level];
}

function updateRecommendation(orderedHours) {
  const selectedTariffs = orderedHours.map(getTariff);
  const lowSelections = selectedTariffs.filter(
    (tariff) => tariff.level === "low"
  );
  const highSelections = selectedTariffs.filter(
    (tariff) => tariff.level === "high"
  );

  const allLowTariffs = HOURLY_TARIFFS.filter(
    (tariff) => tariff.level === "low"
  ).sort((a, b) => a.rateKesPerKwh - b.rateKesPerKwh);

  if (lowSelections.length > 0) {
    const cheapestSelected = [...lowSelections].sort(
      (a, b) => a.rateKesPerKwh - b.rateKesPerKwh
    )[0];

    elements.recommendationTitle.textContent =
      `${formatTimeRange(cheapestSelected.hour)} is a good choice`;
    elements.recommendationText.textContent =
      `This selected slot is in the lower-cost period at approximately ` +
      `KES ${formatKes(cheapestSelected.rateKesPerKwh)} per kWh.`;
    elements.resultBadge.textContent = "Good choice";
    return;
  }

  const cheapestAvailable = allLowTariffs[0];

  if (highSelections.length === selectedTariffs.length) {
    elements.recommendationTitle.textContent =
      "Your selected hours are peak-cost periods";
    elements.recommendationText.textContent =
      `For a lower estimated cost, consider ${formatTimeRange(
        cheapestAvailable.hour
      )} instead.`;
    elements.resultBadge.textContent = "Try another time";
    return;
  }

  elements.recommendationTitle.textContent =
    "A lower-cost option is available";
  elements.recommendationText.textContent =
    `Your selection includes an average-cost period. ` +
    `${formatTimeRange(cheapestAvailable.hour)} is currently the cheapest option.`;
  elements.resultBadge.textContent = "Alternative found";
}

function showResults() {
  resultsVisible = true;
  applyCostColours();
  renderResults();
  elements.resultsCard.classList.remove("is-hidden");

  window.setTimeout(() => {
    elements.resultsCard.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, 80);
}

function hideResults() {
  resultsVisible = false;
  elements.resultsCard.classList.add("is-hidden");

  document.querySelectorAll(".time-slot").forEach((button) => {
    button.classList.remove("cost-low", "cost-medium", "cost-high");

    const hour = Number(button.dataset.hour);
    button.setAttribute(
      "aria-label",
      `Select ${formatTimeRange(hour)} for cooking`
    );
  });
}

function clearSelection() {
  selectedHours.clear();
  hideResults();
  updateSelectedState();
  updateSelectionSummary();
  showToast("Cooking time selection cleared.");
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

elements.goButton.addEventListener("click", showResults);
elements.clearButton.addEventListener("click", clearSelection);
elements.profileButton.addEventListener("click", () => {
  showToast("Profile editing will be connected to the user service later.");
});

window.GridCookUI = {
  setUserData,
  setHourlyTariffs,
  getSelectedHours: () => [...selectedHours].sort((a, b) => a - b),
};

setUserData(MOCK_USER);
createTimeSlots();
updateSelectedState();
updateSelectionSummary();
