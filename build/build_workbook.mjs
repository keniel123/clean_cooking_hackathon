import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "/Users/kenielpeart/Downloads/innovation camp data";
const buildDir = `${root}/outputs/clean_cooking_hackathon/build`;
const outputDir = `${root}/outputs/clean_cooking_hackathon`;
const data = JSON.parse(await fs.readFile(`${buildDir}/aggregate_data.json`, "utf8"));

const workbook = Workbook.create();

const colors = {
  ink: "#172026",
  slate: "#334155",
  teal: "#0F766E",
  tealLight: "#D9F0EC",
  green: "#17803D",
  amber: "#F59E0B",
  amberLight: "#FFF2CC",
  red: "#C2410C",
  blue: "#2563EB",
  blueLight: "#DBEAFE",
  gray: "#E5E7EB",
  grayLight: "#F8FAFC",
  white: "#FFFFFF",
};

function colName(index) {
  let name = "";
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function a1(row, col) {
  return `${colName(col)}${row + 1}`;
}

function rangeA1(startRow, startCol, rowCount, colCount) {
  return `${a1(startRow, startCol)}:${a1(startRow + rowCount - 1, startCol + colCount - 1)}`;
}

function titleCase(text) {
  return String(text)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (m) => m.toUpperCase())
    .replace("Pct", "%")
    .replace("Kwh", "kWh")
    .replace("Usd", "USD")
    .replace("Soc", "SOC")
    .replace("Ac", "AC")
    .replace("Pv", "PV")
    .replace("P95", "P95")
    .replace("P05", "P05");
}

function writeTitle(sheet, title, subtitle = "") {
  sheet.showGridLines = false;
  const titleRange = sheet.getRange("A1:H1");
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: colors.ink,
    font: { bold: true, color: colors.white, size: 16 },
  };
  titleRange.format.rowHeightPx = 34;
  if (subtitle) {
    const sub = sheet.getRange("A2:H2");
    sub.merge();
    sub.values = [[subtitle]];
    sub.format = {
      fill: colors.grayLight,
      font: { color: colors.slate, italic: true },
      wrapText: true,
    };
    sub.format.rowHeightPx = 40;
  }
}

function writeMatrix(sheet, startRow, startCol, matrix) {
  if (!matrix.length || !matrix[0].length) return null;
  const range = sheet.getRangeByIndexes(startRow, startCol, matrix.length, matrix[0].length);
  range.values = matrix;
  return range;
}

function writeTable(sheet, startRow, startCol, headers, rows, options = {}) {
  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header] ?? null))];
  const range = writeMatrix(sheet, startRow, startCol, matrix);
  if (!range) return null;
  const headerRange = sheet.getRangeByIndexes(startRow, startCol, 1, headers.length);
  headerRange.format = {
    fill: options.headerFill || colors.teal,
    font: { bold: true, color: colors.white },
    wrapText: true,
  };
  headerRange.format.rowHeightPx = 34;
  const body = sheet.getRangeByIndexes(startRow + 1, startCol, Math.max(rows.length, 1), headers.length);
  body.format = {
    borders: {
      insideHorizontal: { style: "thin", color: colors.gray },
      insideVertical: { style: "thin", color: colors.gray },
    },
    wrapText: true,
  };
  try {
    sheet.tables.add(rangeA1(startRow, startCol, matrix.length, headers.length), true, options.tableName || undefined);
  } catch {
    // Tables are a usability layer; values and formatting are still the source of truth if table creation fails.
  }
  return range;
}

function setFormats(sheet, startRow, startCol, headers, rowCount, formatMap) {
  for (const [header, format] of Object.entries(formatMap)) {
    const idx = headers.indexOf(header);
    if (idx >= 0) {
      const range = sheet.getRangeByIndexes(startRow + 1, startCol + idx, Math.max(rowCount, 1), 1);
      range.format.numberFormat = format;
    }
  }
}

function finishSheet(sheet, usedCols = 8, freezeRows = 3) {
  if (freezeRows) sheet.freezePanes.freezeRows(freezeRows);
  const used = sheet.getUsedRange(true);
  if (used) {
    used.format.autofitColumns();
    used.format.autofitRows();
  }
  for (let i = 0; i < usedCols; i++) {
    const col = sheet.getRange(`${colName(i)}:${colName(i)}`);
    if (i === 0) col.format.columnWidthPx = 170;
    if (i > 0) col.format.columnWidthPx = 130;
  }
}

function setColumnWidths(sheet, widths) {
  for (const [column, widthPx] of Object.entries(widths)) {
    sheet.getRange(`${column}:${column}`).format.columnWidthPx = widthPx;
  }
  const used = sheet.getUsedRange(true);
  if (used) used.format.autofitRows();
}

function numberOrBlank(value) {
  return typeof value === "number" ? value : null;
}

function rounded(value, digits = 1) {
  return typeof value === "number" ? Number(value.toFixed(digits)) : value;
}

function remapRows(rows, mapping) {
  return rows.map((row) => {
    const out = {};
    for (const [label, key] of Object.entries(mapping)) out[label] = row[key] ?? null;
    return out;
  });
}

function metricRows() {
  const interpretations = {
    "World population without clean cooking, 2023": "Global TAM for clean-cooking interventions.",
    "Sub-Saharan Africa without clean cooking, 2023": "Largest regional concentration in the data.",
    "Kenya without clean cooking, 2023": "Primary pilot market size.",
    "Kenya clean-cooking access, 2023": "Shows the remaining adoption gap.",
    "Kenya rural clean-cooking access, 2022": "Rural problem framing for mini-grid communities.",
    "Oloika e-cooker energy in June trial": "Observed clean-cooking electricity use.",
    "Oloika e-cooker energy per participating household": "Early usage baseline for pilot sizing.",
    "Oloika June mini-grid AC consumption": "Site load denominator for feasibility.",
    "E-cooker trial share of mini-grid AC consumption": "Shows the pilot can start with scheduling rather than major grid reinforcement.",
  };
  return data.concept.key_metrics.map((row) => ({
    Metric: row.metric,
    Value: row.value,
    Unit: row.unit,
    Interpretation: interpretations[row.metric] || "",
  }));
}

function addDashboard() {
  const sheet = workbook.worksheets.add("Dashboard");
  writeTitle(
    sheet,
    "Clean Cooking Hackathon Aggregate",
    "Evidence base for a Kenya-first GridCook AI pitch using SDG clean-cooking data, Oloika e-cooker smart-plug readings, mini-grid telemetry, and implementation lessons."
  );

  const kpis = metricRows();
  writeTable(sheet, 4, 0, ["Metric", "Value", "Unit", "Interpretation"], kpis, {
    tableName: "DashboardMetrics",
    headerFill: colors.teal,
  });
  setFormats(sheet, 4, 0, ["Metric", "Value", "Unit", "Interpretation"], kpis.length, {
    Value: "#,##0.0",
  });

  const top = data.country.top_unserved.slice(0, 10).map((r) => ({
    Country: r["Country Name"],
    "People without clean cooking": r.people_without_clean_cooking_2023,
  }));
  const chartStart = 17;
  writeTable(sheet, chartStart, 0, ["Country", "People without clean cooking"], top, {
    tableName: "TopUnservedForChart",
    headerFill: colors.red,
  });
  setFormats(sheet, chartStart, 0, ["Country", "People without clean cooking"], top.length, {
    "People without clean cooking": "#,##0",
  });
  const chart = sheet.charts.add("bar", sheet.getRange(rangeA1(chartStart, 0, top.length + 1, 2)));
  chart.title = "Top Countries by People Without Clean Cooking";
  chart.hasLegend = false;
  chart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 9 } };
  chart.yAxis = { numberFormatCode: "#,##0" };
  chart.setPosition("D18", "L36");

  finishSheet(sheet, 12, 4);
  setColumnWidths(sheet, { A: 320, B: 160, C: 95, D: 520, E: 120, F: 120, G: 120, H: 120 });
}

function addPitchBrief() {
  const sheet = workbook.worksheets.add("Pitch Brief");
  writeTitle(sheet, "GridCook AI Pitch Brief", "Concept, implementation path, assumptions, and judge-criteria mapping.");

  writeTable(sheet, 4, 0, ["section", "content"], data.concept.pitch_brief, {
    tableName: "PitchBriefTable",
    headerFill: colors.teal,
  });
  sheet.getRange("A:C").format.wrapText = true;

  const deckRows = [
    { Slide: 1, Title: "The Clean-Cooking Gap", Message: "2.06B people globally and 37.9M in Kenya lack clean cooking access." },
    { Slide: 2, Title: "Why Kenya and Oloika", Message: "Kenya combines a large cooking gap, rising electricity access, and local e-cooker/mini-grid telemetry." },
    { Slide: 3, Title: "Observed Load Evidence", Message: "June Oloika data shows 46.0 kWh of e-cooker use across 5 participating households." },
    { Slide: 4, Title: "The AI System", Message: "Detect cooking sessions, forecast PV/load, and schedule cooking windows without exceeding voltage, SOC, or phase constraints." },
    { Slide: 5, Title: "Pilot and Evaluation", Message: "Run a 6-month field pilot measuring adoption, fuel stacking, voltage events, time saved, and household satisfaction." },
    { Slide: 6, Title: "Funding Ask", Message: "Request USD 350k-600k for a field pilot, with an 8-10 week MVP before deployment." },
  ];
  writeTable(sheet, 17, 0, ["Slide", "Title", "Message"], deckRows, {
    tableName: "DeckOutline",
    headerFill: colors.blue,
  });

  writeTable(sheet, 26, 0, ["criterion", "evidence"], data.concept.judge_mapping, {
    tableName: "JudgeMapping",
    headerFill: colors.amber,
  });
  finishSheet(sheet, 6, 4);
  setColumnWidths(sheet, { A: 220, B: 720, C: 680, D: 120, E: 120, F: 120 });
}

function addTargetCountries() {
  const sheet = workbook.worksheets.add("Target Countries");
  writeTitle(sheet, "Target Country Prioritization", "Kenya is the primary pilot because local implementation data exists; the other countries show replication paths and benchmarks.");
  const headers = [
    "Country",
    "Role",
    "Region",
    "Income",
    "Population 2023",
    "Clean cooking access 2023 %",
    "Clean cooking gap %",
    "People without clean cooking 2023",
    "Rural clean cooking 2022 %",
    "Electricity access 2022 %",
    "Renewable energy share 2021 %",
    "Pilot score",
  ];
  const rows = remapRows(data.country.target_countries, {
    Country: "Country Name",
    Role: "recommended_role",
    Region: "Region",
    Income: "IncomeGroup",
    "Population 2023": "population_2023",
    "Clean cooking access 2023 %": "clean_access_2023_pct",
    "Clean cooking gap %": "clean_cooking_gap_pct",
    "People without clean cooking 2023": "people_without_clean_cooking_2023",
    "Rural clean cooking 2022 %": "clean_cooking_rural_2022_pct",
    "Electricity access 2022 %": "electricity_total_2022_pct",
    "Renewable energy share 2021 %": "renewable_energy_share_2021_pct",
    "Pilot score": "ecooking_pilot_score",
  });
  writeTable(sheet, 4, 0, headers, rows, {
    tableName: "TargetCountries",
    headerFill: colors.teal,
  });
  setFormats(sheet, 4, 0, headers, rows.length, {
    "Population 2023": "#,##0",
    "Clean cooking access 2023 %": "0.0",
    "Clean cooking gap %": "0.0",
    "People without clean cooking 2023": "#,##0",
    "Rural clean cooking 2022 %": "0.0",
    "Electricity access 2022 %": "0.0",
    "Renewable energy share 2021 %": "0.0",
    "Pilot score": "0.00",
  });
  finishSheet(sheet, headers.length, 4);
  setColumnWidths(sheet, { A: 180, B: 430, C: 170, D: 150, E: 150, F: 120, G: 120, H: 170 });
}

function addCountryData() {
  const sheet = workbook.worksheets.add("Country Data");
  writeTitle(sheet, "Country Opportunity Data", "Country-level aggregate data. Readiness score is a heuristic: 45% clean-cooking gap, 35% electricity access, 20% unserved-population scale.");
  const headers = [
    "Country",
    "ISO3",
    "Region",
    "Income",
    "Population 2023",
    "Clean cooking access 2023 %",
    "Clean cooking gap %",
    "People without clean cooking 2023",
    "Rural clean cooking 2022 %",
    "Urban clean cooking 2022 %",
    "Electricity access 2022 %",
    "Rural electricity 2022 %",
    "Urban electricity 2022 %",
    "Renewable energy share 2021 %",
    "Renewable capacity 2019 W/capita",
    "Clean energy finance 2018 USDm",
    "Pilot score",
  ];
  const rows = remapRows(data.country.countries, {
    Country: "Country Name",
    ISO3: "Country Code",
    Region: "Region",
    Income: "IncomeGroup",
    "Population 2023": "population_2023",
    "Clean cooking access 2023 %": "clean_access_2023_pct",
    "Clean cooking gap %": "clean_cooking_gap_pct",
    "People without clean cooking 2023": "people_without_clean_cooking_2023",
    "Rural clean cooking 2022 %": "clean_cooking_rural_2022_pct",
    "Urban clean cooking 2022 %": "clean_cooking_urban_2022_pct",
    "Electricity access 2022 %": "electricity_total_2022_pct",
    "Rural electricity 2022 %": "electricity_rural_2022_pct",
    "Urban electricity 2022 %": "electricity_urban_2022_pct",
    "Renewable energy share 2021 %": "renewable_energy_share_2021_pct",
    "Renewable capacity 2019 W/capita": "renewable_capacity_2019_w_per_capita",
    "Clean energy finance 2018 USDm": "clean_energy_finance_2018_usd_m",
    "Pilot score": "ecooking_pilot_score",
  });
  writeTable(sheet, 4, 0, headers, rows, {
    tableName: "CountryOpportunity",
    headerFill: colors.slate,
  });
  setFormats(sheet, 4, 0, headers, rows.length, {
    "Population 2023": "#,##0",
    "Clean cooking access 2023 %": "0.0",
    "Clean cooking gap %": "0.0",
    "People without clean cooking 2023": "#,##0",
    "Rural clean cooking 2022 %": "0.0",
    "Urban clean cooking 2022 %": "0.0",
    "Electricity access 2022 %": "0.0",
    "Rural electricity 2022 %": "0.0",
    "Urban electricity 2022 %": "0.0",
    "Renewable energy share 2021 %": "0.0",
    "Renewable capacity 2019 W/capita": "0.0",
    "Clean energy finance 2018 USDm": "#,##0.0",
    "Pilot score": "0.00",
  });
  finishSheet(sheet, headers.length, 4);
  setColumnWidths(sheet, { A: 220, B: 80, C: 180, D: 150, E: 150, H: 170, Q: 120 });
}

function addEcooker() {
  const sheet = workbook.worksheets.add("Oloika ECooker");
  writeTitle(sheet, "Oloika E-Cooker Trial Summary", "Smart-plug readings from June 2025. Cumulative kWh is used for energy totals; irregular power samples are used for sessions and peak-load evidence.");

  const overallHeaders = ["Metric", "Value", "Unit"];
  const overallRows = Object.entries(data.ecooker.overall).map(([key, value]) => ({
    Metric: titleCase(key),
    Value: value,
    Unit: key.includes("pct") ? "%" : key.includes("kwh") ? "kWh" : key.includes("power") ? "W" : key.includes("voltage") ? "V" : "",
  }));
  writeTable(sheet, 4, 0, overallHeaders, overallRows, {
    tableName: "ECookerOverall",
    headerFill: colors.teal,
  });
  setFormats(sheet, 4, 0, overallHeaders, overallRows.length, { Value: "#,##0.0" });

  const plugHeaders = [
    "Plug",
    "Household",
    "Observed days",
    "Cumulative kWh",
    "kWh/day",
    "Sessions",
    "Median duration min",
    "Avg power W",
    "Peak power W",
    "Green-light samples %",
    "Voltage P05 V",
    "Mean voltage V",
  ];
  const plugRows = remapRows(data.ecooker.plug_summary, {
    Plug: "plug",
    Household: "household",
    "Observed days": "observed_days",
    "Cumulative kWh": "cumulative_kwh_delta",
    "kWh/day": "kwh_per_observed_day",
    Sessions: "sessions",
    "Median duration min": "median_duration_min",
    "Avg power W": "avg_power_w",
    "Peak power W": "peak_power_w",
    "Green-light samples %": "green_light_sample_pct",
    "Voltage P05 V": "voltage_p05_v",
    "Mean voltage V": "voltage_mean_v",
  });
  writeTable(sheet, 21, 0, plugHeaders, plugRows, {
    tableName: "ECookerPlugSummary",
    headerFill: colors.blue,
  });
  setFormats(sheet, 21, 0, plugHeaders, plugRows.length, {
    "Observed days": "0.0",
    "Cumulative kWh": "0.00",
    "kWh/day": "0.000",
    Sessions: "#,##0",
    "Median duration min": "0.0",
    "Avg power W": "#,##0",
    "Peak power W": "#,##0",
    "Green-light samples %": "0.0",
    "Voltage P05 V": "0.0",
    "Mean voltage V": "0.0",
  });

  const hourStart = 21;
  const hourCol = 14;
  const hourRows = remapRows(data.ecooker.session_start_hour, {
    "Start hour UTC": "start_hour_utc",
    Sessions: "sessions",
  });
  writeTable(sheet, hourStart, hourCol, ["Start hour UTC", "Sessions"], hourRows, {
    tableName: "SessionStartHours",
    headerFill: colors.amber,
  });
  const chart = sheet.charts.add(
    "bar",
    sheet.getRange(rangeA1(hourStart, hourCol, hourRows.length + 1, 2))
  );
  chart.title = "Cooking Sessions by Start Hour";
  chart.hasLegend = false;
  chart.xAxis = { axisType: "textAxis" };
  chart.setPosition("O4", "V18");

  finishSheet(sheet, 22, 4);
  setColumnWidths(sheet, { A: 230, B: 105, C: 120, D: 130, E: 130, F: 90, G: 130, H: 120, I: 115, J: 125, K: 115, L: 115 });
}

function addMiniGrid() {
  const sheet = workbook.worksheets.add("MiniGrid");
  writeTitle(sheet, "Oloika Mini-Grid Energy Context", "Victron telemetry for June 2025. Power telemetry is integrated with long gaps excluded; PV inverter counter and DC solar daily counters are shown separately.");

  const summaryRows = Object.entries(data.minigrid.summary).map(([key, value]) => ({
    Metric: titleCase(key),
    Value: value,
    Unit: key.includes("pct") ? "%" : key.includes("kwh") ? "kWh" : key.includes("load") || key.includes("power") ? "W" : "",
  }));
  writeTable(sheet, 4, 0, ["Metric", "Value", "Unit"], summaryRows, {
    tableName: "MiniGridSummary",
    headerFill: colors.teal,
  });
  setFormats(sheet, 4, 0, ["Metric", "Value", "Unit"], summaryRows.length, { Value: "#,##0.0" });

  const headers = [
    "Date",
    "AC consumption kWh",
    "PV inverter kWh",
    "DC solar yield kWh",
    "Peak AC load W",
    "P95 AC load W",
    "Min battery SOC %",
    "Mean battery SOC %",
  ];
  const rows = remapRows(data.minigrid.daily, {
    Date: "date",
    "AC consumption kWh": "ac_consumption_kwh_integrated",
    "PV inverter kWh": "pv_inverter_kwh_integrated",
    "DC solar yield kWh": "dc_solar_yield_kwh",
    "Peak AC load W": "peak_ac_load_w",
    "P95 AC load W": "p95_ac_load_w",
    "Min battery SOC %": "min_battery_soc_pct",
    "Mean battery SOC %": "mean_battery_soc_pct",
  });
  writeTable(sheet, 23, 0, headers, rows, {
    tableName: "MiniGridDaily",
    headerFill: colors.blue,
  });
  setFormats(sheet, 23, 0, headers, rows.length, {
    "AC consumption kWh": "0.0",
    "PV inverter kWh": "0.0",
    "DC solar yield kWh": "0.0",
    "Peak AC load W": "#,##0",
    "P95 AC load W": "#,##0",
    "Min battery SOC %": "0.0",
    "Mean battery SOC %": "0.0",
  });

  const chartData = [["date", "AC consumption kWh", "PV inverter kWh", "DC solar yield kWh"]];
  for (const row of data.minigrid.daily) {
    chartData.push([
      row.date,
      numberOrBlank(row.ac_consumption_kwh_integrated),
      numberOrBlank(row.pv_inverter_kwh_integrated),
      numberOrBlank(row.dc_solar_yield_kwh),
    ]);
  }
  writeMatrix(sheet, 23, 10, chartData);
  const helperHeader = sheet.getRangeByIndexes(23, 10, 1, 4);
  helperHeader.format = { fill: colors.amber, font: { bold: true, color: colors.ink } };
  const chart = sheet.charts.add("line", sheet.getRange(rangeA1(23, 10, chartData.length, 4)));
  chart.title = "Daily Mini-Grid Energy";
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 8 } };
  chart.yAxis = { numberFormatCode: "0.0" };
  chart.setPosition("J4", "R20");

  finishSheet(sheet, 18, 4);
  setColumnWidths(sheet, { A: 280, B: 140, C: 80, D: 135, E: 135, F: 135, G: 135, H: 135 });
}

function addCaseLessons() {
  const sheet = workbook.worksheets.add("Case Lessons");
  writeTitle(sheet, "Implementation Lessons", "UNHCR/WLPGA case study lessons translated into safeguards for the GridCook AI pilot.");
  writeTable(sheet, 4, 0, ["lesson", "evidence", "design_implication"], data.concept.case_study_lessons, {
    tableName: "CaseStudyLessons",
    headerFill: colors.teal,
  });
  sheet.getRange("A:C").format.wrapText = true;
  finishSheet(sheet, 5, 4);
  setColumnWidths(sheet, { A: 220, B: 520, C: 560 });
}

function addSources() {
  const sheet = workbook.worksheets.add("Sources");
  writeTitle(sheet, "Sources and Assumptions", "Supplemental population data is kept separate from the local clean-cooking inputs. URLs and local paths are plain text for auditability.");
  writeTable(sheet, 4, 0, ["source", "used_for", "url_or_path"], data.concept.sources, {
    tableName: "SourcesTable",
    headerFill: colors.slate,
  });
  writeTable(sheet, 17, 0, ["topic", "assumption"], data.concept.assumptions, {
    tableName: "AssumptionsTable",
    headerFill: colors.amber,
  });
  sheet.getRange("A:C").format.wrapText = true;
  finishSheet(sheet, 5, 4);
  setColumnWidths(sheet, { A: 300, B: 520, C: 760 });
}

addPitchBrief();
addDashboard();
addTargetCountries();
addCountryData();
addEcooker();
addMiniGrid();
addCaseLessons();
addSources();

await fs.mkdir(outputDir, { recursive: true });

const dashboardPreview = await workbook.render({
  sheetName: "Dashboard",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(`${buildDir}/dashboard_preview.png`, new Uint8Array(await dashboardPreview.arrayBuffer()));

const pitchPreview = await workbook.render({
  sheetName: "Pitch Brief",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(`${buildDir}/pitch_preview.png`, new Uint8Array(await pitchPreview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(`${outputDir}/clean_cooking_hackathon_aggregate.xlsx`);

const inspect = await workbook.inspect({
  kind: "sheet,table",
  maxChars: 4000,
  tableMaxRows: 3,
  tableMaxCols: 6,
});
console.log(inspect.ndjson);
