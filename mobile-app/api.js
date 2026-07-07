/*
  GridCook mobile — live API wiring.

  Connects the prototype UI to the shared GridCook API without touching app.js.
  It calls the documented integration hooks (window.GridCookUI.setUserData /
  setHourlyTariffs) with real data:
    - user card  <- GET /api/v1/leaderboard  (name, kWh, reward-credit balance)
    - 24 slots   <- GET /api/v1/grid/daily-plan  (slot_color -> low/medium/high)

  Config (optional):
    - window.GRIDCOOK_API_BASE  overrides the API host
    - ?account=HH-0007          pick which account to show (try a BIZ-00x too)
*/
(function () {
  const API_BASE = (window.GRIDCOOK_API_BASE || "https://delft-api.flonat.com").replace(/\/+$/, "");
  const ACCOUNT = new URLSearchParams(location.search).get("account") || "HH-0007";

  // green window = cheapest/best time to cook; red = peak/avoid.
  const LEVEL_BY_COLOR = { green: "low", orange: "medium", high: "high", red: "high" };

  // Map the recommender's favorability score (~ -1..82) to a transparent
  // KES/kWh figure: the better the window, the lower the shown rate.
  function rateFor(score) {
    const s = Math.max(0, Math.min(82, Number(score) || 0));
    return Math.round(40 - (s / 82) * 25); // ~15 (best) .. 40 (worst)
  }

  async function getJson(path) {
    const res = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(path + " -> HTTP " + res.status);
    return res.json();
  }

  async function loadUser() {
    const lb = await getJson("/api/v1/leaderboard?limit=100");
    const me = (lb.results || []).find((x) => x.account_id === ACCOUNT);
    if (!me) return;
    window.GridCookUI.setUserData({
      id: me.account_id,
      name: me.display_name,
      electricityUsageKwh: me.kwh,
      creditKes: me.ending_balance_credits, // reward-credit wallet balance
      profilePhotoUrl: "assets/profile-photo.svg",
    });
  }

  async function loadTariffs() {
    const plan = await getJson("/api/v1/grid/daily-plan");
    const byHour = new Map((plan.results || []).map((p) => [p.hour_eat, p]));
    const tariffs = Array.from({ length: 24 }, (_, hour) => {
      const p = byHour.get(hour);
      const color = (p && p.slot_color) || "red";
      return {
        hour,
        level: LEVEL_BY_COLOR[color] || "high",
        rateKesPerKwh: rateFor(p && p.favorability_score),
      };
    });
    window.GridCookUI.setHourlyTariffs(tariffs); // 24 ordered items, validated by app.js
  }

  async function wire() {
    if (!window.GridCookUI) {
      console.warn("[gridcook] GridCookUI not ready; is app.js loaded first?");
      return;
    }
    try {
      await Promise.all([loadUser(), loadTariffs()]);
      console.log("[gridcook] wired to", API_BASE, "as", ACCOUNT);
    } catch (err) {
      // Leave the prototype's placeholder data in place on any failure.
      console.warn("[gridcook] live API unavailable, using placeholder data:", err.message);
    }
  }

  // app.js is loaded first (also `defer`), so GridCookUI already exists here.
  wire();
})();
