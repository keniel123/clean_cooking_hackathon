from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/kenielpeart/Downloads/innovation camp data")
ONE = ROOT / "OneDrive_1_06-07-2026"
BUILD = ROOT / "outputs" / "clean_cooking_hackathon" / "build"
POP_ZIP = Path("/private/tmp/wb_population.zip")


ALIASES = {
    "Tanzania": ["United Republic of Tanzania", "United Rep. of Tanzania", "Tanzania"],
    "Congo, Dem. Rep.": ["Democratic Republic of the Congo", "Congo, Dem. Rep."],
    "Congo, Rep.": ["Congo"],
    "Gambia, The": ["Gambia"],
    "Egypt, Arab Rep.": ["Egypt"],
    "Yemen, Rep.": ["Yemen"],
    "Venezuela, RB": ["Venezuela (Bolivarian Republic of)"],
    "Iran, Islamic Rep.": ["Iran (Islamic Republic of)"],
    "Lao PDR": ["Lao People's Democratic Republic"],
    "Korea, Dem. People's Rep.": ["Democratic People's Republic of Korea"],
    "Korea, Rep.": ["Republic of Korea"],
    "Micronesia, Fed. Sts.": ["Micronesia (Federated States of)"],
    "Cote d'Ivoire": ["Côte d'Ivoire"],
    "Syrian Arab Republic": ["Syrian Arab Republic"],
}


def clean_value(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def records(df: pd.DataFrame) -> list[dict]:
    return [
        {str(k): clean_value(v) for k, v in row.items()}
        for row in df.replace({np.nan: None}).to_dict(orient="records")
    ]


def lookup_by_name(mapping: dict[str, float], name: str):
    candidates = [name] + ALIASES.get(name, [])
    for candidate in candidates:
        if candidate in mapping and pd.notna(mapping[candidate]):
            return mapping[candidate]
    return np.nan


def integrate_power_kwh(df: pd.DataFrame, power_col: str) -> float:
    data = df.dropna(subset=["timestamp", power_col]).sort_values("timestamp").copy()
    if data.empty:
        return np.nan
    dt_hours = data["timestamp"].shift(-1).sub(data["timestamp"]).dt.total_seconds() / 3600
    dt_hours = dt_hours.where(dt_hours.between(0, 0.5), 0)
    return float((data[power_col] * dt_hours).sum() / 1000)


def country_data():
    with zipfile.ZipFile(ROOT / "API_EG.CFT.ACCS.ZS_DS2_en_csv_v2_6378.zip") as zf:
        with zf.open("API_EG.CFT.ACCS.ZS_DS2_en_csv_v2_6378.csv") as f:
            clean = pd.read_csv(f, skiprows=4)
        with zf.open("Metadata_Country_API_EG.CFT.ACCS.ZS_DS2_en_csv_v2_6378.csv") as f:
            meta = pd.read_csv(f)

    with zipfile.ZipFile(POP_ZIP) as zf:
        api = [name for name in zf.namelist() if name.startswith("API_") and name.endswith(".csv")][0]
        with zf.open(api) as f:
            pop = pd.read_csv(f, skiprows=4)

    countries = clean[["Country Name", "Country Code", "2023"]].rename(
        columns={"2023": "clean_access_2023_pct"}
    )
    countries["clean_access_2023_pct"] = pd.to_numeric(countries["clean_access_2023_pct"], errors="coerce")
    countries = countries.merge(meta[["Country Code", "Region", "IncomeGroup"]], on="Country Code", how="left")
    countries = countries.merge(
        pop[["Country Code", "2023"]].rename(columns={"2023": "population_2023"}),
        on="Country Code",
        how="left",
    )
    countries["population_2023"] = pd.to_numeric(countries["population_2023"], errors="coerce")
    countries["clean_cooking_gap_pct"] = 100 - countries["clean_access_2023_pct"]
    countries["people_without_clean_cooking_2023"] = (
        countries["population_2023"] * countries["clean_cooking_gap_pct"] / 100
    )

    electricity = pd.read_excel(ROOT / "sdg7.1.1_-_access_to_electricity.xlsx", sheet_name="UN reporting")
    electricity = electricity.rename(
        columns={"GeoAreaName/Reference Area Name": "GeoAreaName", " Value ": "electricity_access_pct"}
    )
    electricity["electricity_access_pct"] = pd.to_numeric(electricity["electricity_access_pct"], errors="coerce")
    electricity = electricity[(electricity["Type"].eq("Country")) & (electricity["TimePeriod"].eq(2022))]
    electricity_piv = (
        electricity.pivot_table(
            index="ISOalpha3", columns="Location", values="electricity_access_pct", aggfunc="first"
        )
        .reset_index()
        .rename(
            columns={
                "ALLAREA": "electricity_total_2022_pct",
                "RURAL": "electricity_rural_2022_pct",
                "URBAN": "electricity_urban_2022_pct",
            }
        )
    )
    countries = countries.merge(electricity_piv, left_on="Country Code", right_on="ISOalpha3", how="left")

    who = pd.read_excel(ROOT / "sdg7.1.2_-_clean_cooking.xlsx", sheet_name="Data Global SDG Database")
    who22 = who[(who["TimePeriod"].eq(2022)) & (who["Location"].isin(["ALLAREA", "RURAL", "URBAN"]))]
    who_piv = (
        who22.pivot_table(index="GeoAreaName", columns="Location", values="Value", aggfunc="first")
        .reset_index()
        .rename(
            columns={
                "ALLAREA": "clean_cooking_total_2022_pct",
                "RURAL": "clean_cooking_rural_2022_pct",
                "URBAN": "clean_cooking_urban_2022_pct",
            }
        )
    )
    for col in [
        "clean_cooking_total_2022_pct",
        "clean_cooking_rural_2022_pct",
        "clean_cooking_urban_2022_pct",
    ]:
        mapping = dict(zip(who_piv["GeoAreaName"], who_piv[col]))
        countries[col] = countries["Country Name"].apply(lambda name: lookup_by_name(mapping, name))
        countries[col] = pd.to_numeric(countries[col], errors="coerce")

    renewables = pd.read_excel(ROOT / "sdg7.2.1_-_renewable_energy.xlsx", sheet_name="7.2 SDG7 Report data (raw)")
    renewables["Product_clean"] = renewables["Product"].astype(str).str.strip()
    renewable_share = renewables[
        (renewables["Flow"].eq("Share in total final energy consumption (%)"))
        & (renewables["Product_clean"].eq("Renewables"))
    ][["GeoAreaName", 2021]].rename(columns={2021: "renewable_energy_share_2021_pct"})
    mapping = dict(zip(renewable_share["GeoAreaName"], renewable_share["renewable_energy_share_2021_pct"]))
    countries["renewable_energy_share_2021_pct"] = countries["Country Name"].apply(
        lambda name: lookup_by_name(mapping, name)
    )
    countries["renewable_energy_share_2021_pct"] = pd.to_numeric(
        countries["renewable_energy_share_2021_pct"], errors="coerce"
    )

    capacity = pd.read_excel(ROOT / "sdg7.b.1-renewable-capacity-per-capita.xlsx", sheet_name="Data")
    cap19 = capacity[capacity["TimePeriod"].eq(2019)][["GeoAreaName", "Value"]].rename(
        columns={"Value": "renewable_capacity_2019_w_per_capita"}
    )
    mapping = dict(zip(cap19["GeoAreaName"], cap19["renewable_capacity_2019_w_per_capita"]))
    countries["renewable_capacity_2019_w_per_capita"] = countries["Country Name"].apply(
        lambda name: lookup_by_name(mapping, name)
    )
    countries["renewable_capacity_2019_w_per_capita"] = pd.to_numeric(
        countries["renewable_capacity_2019_w_per_capita"], errors="coerce"
    )

    finance = pd.read_excel(ROOT / "sdg7.a.1-public_financial_flows_0.xlsx", sheet_name="Data")
    flow18 = finance[finance["TimePeriod"].eq(2018)][["GeoAreaName", "Value"]].rename(
        columns={"Value": "clean_energy_finance_2018_usd_m"}
    )
    mapping = dict(zip(flow18["GeoAreaName"], flow18["clean_energy_finance_2018_usd_m"]))
    countries["clean_energy_finance_2018_usd_m"] = countries["Country Name"].apply(
        lambda name: lookup_by_name(mapping, name)
    )
    countries["clean_energy_finance_2018_usd_m"] = pd.to_numeric(
        countries["clean_energy_finance_2018_usd_m"], errors="coerce"
    )

    country_only = countries[countries["Region"].notna()].copy()
    for col in ["clean_cooking_gap_pct", "electricity_total_2022_pct"]:
        mn = country_only[col].min()
        mx = country_only[col].max()
        country_only[f"{col}_n"] = (country_only[col] - mn) / (mx - mn)
    country_only["unserved_log"] = np.log1p(country_only["people_without_clean_cooking_2023"])
    country_only["unserved_log_n"] = (
        (country_only["unserved_log"] - country_only["unserved_log"].min())
        / (country_only["unserved_log"].max() - country_only["unserved_log"].min())
    )
    country_only["ecooking_pilot_score"] = (
        0.45 * country_only["clean_cooking_gap_pct_n"]
        + 0.35 * country_only["electricity_total_2022_pct_n"]
        + 0.20 * country_only["unserved_log_n"]
    )
    countries = countries.merge(
        country_only[["Country Code", "ecooking_pilot_score"]], on="Country Code", how="left"
    )

    region_rows = []
    for region, group in country_only.dropna(subset=["population_2023"]).groupby("Region"):
        population = group["population_2023"].sum()
        unserved = group["people_without_clean_cooking_2023"].sum()
        region_rows.append(
            {
                "Region": region,
                "countries": len(group),
                "population_2023": population,
                "people_without_clean_cooking_2023": unserved,
                "weighted_clean_access_2023_pct": (1 - unserved / population) * 100 if population else np.nan,
            }
        )
    region_summary = pd.DataFrame(region_rows).sort_values("people_without_clean_cooking_2023", ascending=False)

    target_names = [
        "Kenya",
        "Uganda",
        "Tanzania",
        "Rwanda",
        "Ethiopia",
        "Nigeria",
        "India",
        "Bangladesh",
        "Congo, Dem. Rep.",
        "Mozambique",
        "Ghana",
    ]
    target = countries[countries["Country Name"].isin(target_names)].copy()
    target["recommended_role"] = target["Country Name"].map(
        {
            "Kenya": "Primary pilot: local mini-grid and e-cooker telemetry available",
            "Uganda": "Replication candidate: extreme cooking gap, nearby market",
            "Tanzania": "Replication candidate: high unserved population",
            "Rwanda": "Smaller controlled pilot candidate",
            "Ethiopia": "Large-scale future market after infrastructure review",
            "Nigeria": "Large-market future expansion; grid constraints need separate design",
            "India": "Benchmark for large clean-cooking transition programs",
            "Bangladesh": "Benchmark for refugee/host-community fuel transition lessons",
            "Congo, Dem. Rep.": "High-need market; implementation risk high",
            "Mozambique": "High-need market; mini-grid assessment needed",
            "Ghana": "Higher electricity readiness comparison case",
        }
    )
    target["target_order"] = target["Country Name"].map(
        {
            "Kenya": 0,
            "Uganda": 1,
            "Tanzania": 2,
            "Rwanda": 3,
            "Ethiopia": 4,
            "Nigeria": 5,
            "India": 6,
            "Bangladesh": 7,
            "Congo, Dem. Rep.": 8,
            "Mozambique": 9,
            "Ghana": 10,
        }
    )
    target = target.sort_values("target_order")

    top_unserved = country_only.sort_values("people_without_clean_cooking_2023", ascending=False).head(25)

    world = countries[countries["Country Name"].eq("World")].iloc[0]
    ssa = countries[countries["Country Name"].eq("Sub-Saharan Africa")].iloc[0]
    kenya = countries[countries["Country Name"].eq("Kenya")].iloc[0]

    return {
        "countries": records(
            country_only[
                [
                    "Country Name",
                    "Country Code",
                    "Region",
                    "IncomeGroup",
                    "population_2023",
                    "clean_access_2023_pct",
                    "clean_cooking_gap_pct",
                    "people_without_clean_cooking_2023",
                    "clean_cooking_total_2022_pct",
                    "clean_cooking_rural_2022_pct",
                    "clean_cooking_urban_2022_pct",
                    "electricity_total_2022_pct",
                    "electricity_rural_2022_pct",
                    "electricity_urban_2022_pct",
                    "renewable_energy_share_2021_pct",
                    "renewable_capacity_2019_w_per_capita",
                    "clean_energy_finance_2018_usd_m",
                    "ecooking_pilot_score",
                ]
            ].sort_values("people_without_clean_cooking_2023", ascending=False)
        ),
        "target_countries": records(
            target[
                [
                    "Country Name",
                    "recommended_role",
                    "Region",
                    "IncomeGroup",
                    "population_2023",
                    "clean_access_2023_pct",
                    "clean_cooking_gap_pct",
                    "people_without_clean_cooking_2023",
                    "clean_cooking_rural_2022_pct",
                    "clean_cooking_urban_2022_pct",
                    "electricity_total_2022_pct",
                    "electricity_rural_2022_pct",
                    "renewable_energy_share_2021_pct",
                    "renewable_capacity_2019_w_per_capita",
                    "clean_energy_finance_2018_usd_m",
                    "ecooking_pilot_score",
                ]
            ]
        ),
        "top_unserved": records(
            top_unserved[
                [
                    "Country Name",
                    "Region",
                    "IncomeGroup",
                    "population_2023",
                    "clean_access_2023_pct",
                    "people_without_clean_cooking_2023",
                    "electricity_total_2022_pct",
                    "ecooking_pilot_score",
                ]
            ]
        ),
        "region_summary": records(region_summary),
        "country_kpis": {
            "global_without_clean_cooking_2023": clean_value(world["people_without_clean_cooking_2023"]),
            "global_clean_access_2023_pct": clean_value(world["clean_access_2023_pct"]),
            "ssa_without_clean_cooking_2023": clean_value(ssa["people_without_clean_cooking_2023"]),
            "ssa_clean_access_2023_pct": clean_value(ssa["clean_access_2023_pct"]),
            "kenya_without_clean_cooking_2023": clean_value(kenya["people_without_clean_cooking_2023"]),
            "kenya_clean_access_2023_pct": clean_value(kenya["clean_access_2023_pct"]),
            "kenya_rural_clean_cooking_2022_pct": clean_value(kenya["clean_cooking_rural_2022_pct"]),
            "kenya_electricity_access_2022_pct": clean_value(kenya["electricity_total_2022_pct"]),
        },
    }


def oloika_ecooker_data():
    plug_hh = {"002": "B", "006": "B", "010": "H", "011": "H", "013": "E", "015": "F", "017": "G", "018": "G"}
    db = ONE / "HA_Oloika.sqlite"
    con = sqlite3.connect(db)
    pow_df = pd.read_sql_query(
        "SELECT plug,last_changed,hod_EAT,dow_EAT,gl,value FROM pow", con, parse_dates=["last_changed"]
    )
    nrg_df = pd.read_sql_query(
        "SELECT plug,last_changed,hod_EAT,dow_EAT,gl,value FROM nrg", con, parse_dates=["last_changed"]
    )
    vlt_df = pd.read_sql_query(
        "SELECT plug,last_changed,hod_EAT,dow_EAT,gl,value FROM vlt", con, parse_dates=["last_changed"]
    )
    con.close()

    energy_rows = []
    for plug, group in nrg_df.groupby("plug"):
        group = group.sort_values("last_changed")
        start = group["last_changed"].min()
        end = group["last_changed"].max()
        vals = group["value"].dropna()
        kwh = vals.max() - vals.min() if len(vals) else np.nan
        days = (end - start).total_seconds() / 86400 if pd.notna(start) and pd.notna(end) else np.nan
        energy_rows.append(
            {
                "plug": plug,
                "household": plug_hh.get(plug, ""),
                "observed_days": days,
                "cumulative_kwh_delta": kwh,
                "kwh_per_observed_day": kwh / days if days else np.nan,
                "first_reading_utc": start,
                "last_reading_utc": end,
            }
        )
    energy = pd.DataFrame(energy_rows)
    mapped_energy = energy[energy["household"].ne("")]

    sessions = []
    for plug, group in pow_df.sort_values(["plug", "last_changed"]).groupby("plug"):
        group = group.copy()
        gaps = group["last_changed"].diff().dt.total_seconds().fillna(999999)
        group["session_id"] = (gaps > 20 * 60).cumsum()
        for _, session in group.groupby("session_id"):
            start = session["last_changed"].min()
            end = session["last_changed"].max()
            duration_min = (end - start).total_seconds() / 60
            session_sorted = session.sort_values("last_changed").copy()
            dt = session_sorted["last_changed"].shift(-1).sub(session_sorted["last_changed"]).dt.total_seconds() / 3600
            dt = dt.where(dt.between(0, 20 / 60), 0)
            approx_kwh = (session_sorted["value"] * dt).sum() / 1000
            sessions.append(
                {
                    "plug": plug,
                    "household": plug_hh.get(plug, ""),
                    "start_utc": start,
                    "end_utc": end,
                    "duration_min": duration_min,
                    "samples": len(session),
                    "avg_power_w": session["value"].mean(),
                    "peak_power_w": session["value"].max(),
                    "approx_kwh_from_power": approx_kwh,
                    "green_light_sample_pct": session["gl"].astype(str).str.upper().eq("TRUE").mean() * 100,
                    "start_hour_utc": start.hour,
                }
            )
    sessions_df = pd.DataFrame(sessions)
    valid_sessions = sessions_df[(sessions_df["duration_min"] >= 2) | (sessions_df["approx_kwh_from_power"] >= 0.02)]

    session_summary = (
        valid_sessions.groupby(["plug", "household"])
        .agg(
            sessions=("start_utc", "count"),
            median_duration_min=("duration_min", "median"),
            mean_duration_min=("duration_min", "mean"),
            median_approx_kwh=("approx_kwh_from_power", "median"),
            total_approx_kwh_from_power=("approx_kwh_from_power", "sum"),
            avg_power_w=("avg_power_w", "mean"),
            peak_power_w=("peak_power_w", "max"),
            green_light_sample_pct=("green_light_sample_pct", "mean"),
        )
        .reset_index()
    )

    voltage = (
        vlt_df.groupby("plug")["value"]
        .agg(
            voltage_samples="count",
            voltage_min_v="min",
            voltage_p05_v=lambda x: x.quantile(0.05),
            voltage_mean_v="mean",
            voltage_p95_v=lambda x: x.quantile(0.95),
            voltage_max_v="max",
        )
        .reset_index()
    )
    plug_summary = energy.merge(session_summary, on=["plug", "household"], how="left").merge(
        voltage, on="plug", how="left"
    )
    plug_summary = plug_summary[plug_summary["household"].ne("")]

    start_hour = (
        valid_sessions.groupby("start_hour_utc")
        .size()
        .reset_index(name="sessions")
        .sort_values("start_hour_utc")
    )

    overall = {
        "participating_households": int(plug_summary["household"].nunique()),
        "active_smart_plugs": int(plug_summary["plug"].nunique()),
        "total_e_cooker_kwh_from_cumulative_readings": float(mapped_energy["cumulative_kwh_delta"].sum()),
        "median_kwh_per_plug_day": float(mapped_energy["kwh_per_observed_day"].median()),
        "valid_cooking_sessions": int(len(valid_sessions)),
        "median_session_duration_min": float(valid_sessions["duration_min"].median()),
        "median_session_approx_kwh_from_power": float(valid_sessions["approx_kwh_from_power"].median()),
        "peak_observed_power_w": float(valid_sessions["peak_power_w"].max()),
        "power_sample_green_light_pct": float(pow_df["gl"].astype(str).str.upper().eq("TRUE").mean() * 100),
        "lowest_voltage_observed_v": float(vlt_df["value"].min()),
        "voltage_p05_all_samples_v": float(vlt_df["value"].quantile(0.05)),
    }

    return {
        "plug_summary": records(plug_summary),
        "session_start_hour": records(start_hour),
        "overall": overall,
    }


def minigrid_data(ecooker_kwh: float):
    path = ONE / "OloikaMinigridUniversityofSouthampton_Victron_June_2025.csv"
    raw = pd.read_csv(path, low_memory=False)
    df = raw.iloc[2:].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    colmap = {
        "pv_dc_w": "System overview [0].10",
        "ac_cons_l1_w": "System overview [0].11",
        "ac_cons_l2_w": "System overview [0].12",
        "ac_cons_l3_w": "System overview [0].13",
        "battery_power_w": "System overview [0].18",
        "battery_soc_pct": "System overview [0].20",
        "solar277_yield_today_kwh": "Solar Charger [277].11",
        "solar278_yield_today_kwh": "Solar Charger [278].11",
        "solar279_yield_today_kwh": "Solar Charger [279].11",
        "pvinv_l1_power_w": "PV Inverter [20].6",
        "pvinv_l2_power_w": "PV Inverter [20].7",
        "pvinv_l3_power_w": "PV Inverter [20].8",
        "pvinv_total_energy_kwh": "PV Inverter [20].12",
    }
    for new_col, old_col in colmap.items():
        df[new_col] = pd.to_numeric(df[old_col], errors="coerce")
    df["ac_cons_total_w"] = df[["ac_cons_l1_w", "ac_cons_l2_w", "ac_cons_l3_w"]].sum(axis=1, min_count=1)
    df["pvinv_total_power_w"] = df[["pvinv_l1_power_w", "pvinv_l2_power_w", "pvinv_l3_power_w"]].sum(
        axis=1, min_count=1
    )
    df["date"] = df["timestamp"].dt.date
    df = df[df["timestamp"].dt.month.eq(6)].copy()

    ac_consumption_kwh = integrate_power_kwh(df, "ac_cons_total_w")
    pv_inverter_kwh_integrated = integrate_power_kwh(df, "pvinv_total_power_w")
    pv_dc_kwh_integrated = integrate_power_kwh(df, "pv_dc_w")

    pvinv_counter = df.dropna(subset=["pvinv_total_energy_kwh"]).sort_values("timestamp")
    pvinv_counter_delta = (
        float(pvinv_counter["pvinv_total_energy_kwh"].iloc[-1] - pvinv_counter["pvinv_total_energy_kwh"].iloc[0])
        if len(pvinv_counter)
        else np.nan
    )
    yield_cols = ["solar277_yield_today_kwh", "solar278_yield_today_kwh", "solar279_yield_today_kwh"]
    daily_yield = df.groupby("date")[yield_cols].max(min_count=1)
    daily_yield["dc_solar_yield_kwh"] = daily_yield.sum(axis=1, min_count=1)
    dc_solar_yield_kwh = float(daily_yield["dc_solar_yield_kwh"].sum())

    daily = []
    for date, group in df.groupby("date"):
        daily.append(
            {
                "date": str(date),
                "ac_consumption_kwh_integrated": integrate_power_kwh(group, "ac_cons_total_w"),
                "pv_inverter_kwh_integrated": integrate_power_kwh(group, "pvinv_total_power_w"),
                "dc_solar_yield_kwh": daily_yield.loc[date, "dc_solar_yield_kwh"]
                if date in daily_yield.index
                else np.nan,
                "peak_ac_load_w": group["ac_cons_total_w"].max(),
                "p95_ac_load_w": group["ac_cons_total_w"].quantile(0.95),
                "min_battery_soc_pct": group["battery_soc_pct"].min(),
                "mean_battery_soc_pct": group["battery_soc_pct"].mean(),
            }
        )
    daily_df = pd.DataFrame(daily)

    load = df["ac_cons_total_w"].dropna()
    soc = df["battery_soc_pct"].dropna()
    summary = {
        "telemetry_rows_june": int(len(df)),
        "ac_consumption_kwh_integrated": ac_consumption_kwh,
        "pv_inverter_kwh_counter_delta": pvinv_counter_delta,
        "pv_inverter_kwh_integrated": pv_inverter_kwh_integrated,
        "dc_solar_yield_kwh_from_daily_counters": dc_solar_yield_kwh,
        "dc_pv_kwh_integrated": pv_dc_kwh_integrated,
        "total_pv_kwh_counter_plus_dc_yield": pvinv_counter_delta + dc_solar_yield_kwh,
        "mean_ac_load_w": float(load.mean()),
        "p95_ac_load_w": float(load.quantile(0.95)),
        "peak_ac_load_w": float(load.max()),
        "mean_battery_soc_pct": float(soc.mean()),
        "battery_soc_below_40_pct_samples": float((soc < 40).mean() * 100),
        "e_cooker_share_of_site_consumption_pct": float(ecooker_kwh / ac_consumption_kwh * 100),
    }
    return {"summary": summary, "daily": records(daily_df.sort_values("date"))}


def concept_data(country_kpis, ecooker, minigrid):
    total_kwh = ecooker["overall"]["total_e_cooker_kwh_from_cumulative_readings"]
    monthly_cooking_energy_per_household = total_kwh / ecooker["overall"]["participating_households"]
    return {
        "pitch_brief": [
            {
                "section": "Project name",
                "content": "GridCook AI: a mini-grid aware clean-cooking planner for electric pressure cookers and compatible clean cooking appliances.",
            },
            {
                "section": "Problem framing",
                "content": "Clean-cooking access is the binding problem, not just appliance availability. Kenya has roughly 37.9 million people without clean cooking in the 2023 World Bank/SDG access data, and the 2022 WHO rural estimate is only about 10.4%.",
            },
            {
                "section": "Solution",
                "content": "Use smart-plug data, mini-grid telemetry, PV forecasts, and household preference signals to forecast cooking load, recommend clean-cooking windows, stagger appliance use, and give operators a dashboard for adoption, safety, and grid headroom.",
            },
            {
                "section": "AI implementation",
                "content": "MVP models: cooking-session detection, short-horizon load/PV forecast, household clustering, and a constrained scheduler that respects voltage, battery SOC, phase load, and meal-time preferences.",
            },
            {
                "section": "Pilot design",
                "content": "Start in Oloika-style Kenyan mini-grids with 50-100 households, using smart plugs and SMS/WhatsApp prompts. Compare fuel stacking, e-cooker kWh, peak load, voltage events, and self-reported time/health outcomes before and after scheduling.",
            },
            {
                "section": "Scale path",
                "content": "After the pilot, replicate in nearby East African markets with high clean-cooking gaps: Uganda, Tanzania, Rwanda, and Ethiopia. Keep the model portable by using standard telemetry fields and a low-bandwidth phone interface.",
            },
            {
                "section": "Cost and time horizon",
                "content": "Hackathon proof of concept: 2-4 days. MVP build: 8-10 weeks at roughly USD 75k-120k. Field pilot: 6 months at roughly USD 350k-600k for devices, field staff, training, data platform, and evaluation. Multi-site scale: 18-24 months at roughly USD 2m-5m.",
            },
            {
                "section": "Failure cases",
                "content": "Main risks are appliance affordability, fuel stacking, unreliable connectivity, low user trust, unsafe wiring, insufficient evening battery headroom, and behavior change fatigue. Mitigations are lease-to-own appliances, local champions, offline-first scheduling, safety checks, tariff incentives, and explicit opt-out control.",
            },
            {
                "section": "Clean Cooking Alliance ask",
                "content": "Fund a data-backed field pilot that proves whether AI-assisted scheduling can accelerate clean-cooking adoption without overloading mini-grids or pushing costs onto low-income households.",
            },
        ],
        "judge_mapping": [
            {
                "criterion": "Problem relevance and framing",
                "evidence": "Uses SDG 7.1.2 clean-cooking access gap; Kenya and Sub-Saharan Africa have large measured gaps.",
            },
            {
                "criterion": "AI implementation quality",
                "evidence": "Model is tied to real telemetry: smart-plug sessions, voltage, PV, battery SOC, and grid consumption.",
            },
            {
                "criterion": "Impact potential",
                "evidence": "Global unserved estimate is about 2.06 billion people; Kenya pilot TAM is about 37.9 million without clean cooking.",
            },
            {
                "criterion": "Feasibility",
                "evidence": "Oloika data shows e-cooking consumed only about "
                + f"{minigrid['summary']['e_cooker_share_of_site_consumption_pct']:.1f}%"
                + " of June site load in the trial, so a staged scheduling pilot is plausible.",
            },
            {
                "criterion": "Presentation and technical proof",
                "evidence": "Workbook includes target-country ranking, e-cooker load summaries, mini-grid daily energy, and implementation assumptions.",
            },
        ],
        "key_metrics": [
            {"metric": "World population without clean cooking, 2023", "value": country_kpis["global_without_clean_cooking_2023"], "unit": "people"},
            {"metric": "Sub-Saharan Africa without clean cooking, 2023", "value": country_kpis["ssa_without_clean_cooking_2023"], "unit": "people"},
            {"metric": "Kenya without clean cooking, 2023", "value": country_kpis["kenya_without_clean_cooking_2023"], "unit": "people"},
            {"metric": "Kenya clean-cooking access, 2023", "value": country_kpis["kenya_clean_access_2023_pct"], "unit": "%"},
            {"metric": "Kenya rural clean-cooking access, 2022", "value": country_kpis["kenya_rural_clean_cooking_2022_pct"], "unit": "%"},
            {"metric": "Oloika e-cooker energy in June trial", "value": total_kwh, "unit": "kWh"},
            {"metric": "Oloika e-cooker energy per participating household", "value": monthly_cooking_energy_per_household, "unit": "kWh/month"},
            {"metric": "Oloika June mini-grid AC consumption", "value": minigrid["summary"]["ac_consumption_kwh_integrated"], "unit": "kWh"},
            {"metric": "E-cooker trial share of mini-grid AC consumption", "value": minigrid["summary"]["e_cooker_share_of_site_consumption_pct"], "unit": "%"},
        ],
        "case_study_lessons": [
            {
                "lesson": "Partnership infrastructure matters",
                "evidence": "The UNHCR/WLPGA case succeeded because LPG suppliers, logistics, equipment procurement, and safety guidance were in place.",
                "design_implication": "Do not pitch AI alone. Pair the scheduler with appliance financing, local technicians, and operator training.",
            },
            {
                "lesson": "Measure more than fuel switching",
                "evidence": "The case tracked firewood demand, kitchen air quality, food diversity, host-community effects, and safety.",
                "design_implication": "Pilot evaluation should track adoption, fuel stacking, voltage events, household time saved, and health/forest proxies.",
            },
            {
                "lesson": "Behavior change requires trust",
                "evidence": "The case highlighted local champions, site visits, and stakeholder understanding of the cooking technology.",
                "design_implication": "Use local champions and simple phone prompts; do not rely on a black-box app to change cooking routines.",
            },
            {
                "lesson": "Environmental outcomes can be large",
                "evidence": "The case reports firewood demand dropping from about 462,000 MT/year to about 37,000 MT/year after LPG introduction.",
                "design_implication": "Frame GridCook AI around avoided biomass demand and reduced peak-load risk, not just app engagement.",
            },
        ],
        "sources": [
            {
                "source": "Local workbook: sdg7.1.2_-_clean_cooking.xlsx",
                "used_for": "WHO/SDG 7.1.2 clean cooking access, rural/urban 2022 values",
                "url_or_path": str(ROOT / "sdg7.1.2_-_clean_cooking.xlsx"),
            },
            {
                "source": "Local World Bank zip: API_EG.CFT.ACCS.ZS_DS2_en_csv_v2_6378.zip",
                "used_for": "World Bank clean fuels and technologies for cooking, total 2023 values",
                "url_or_path": str(ROOT / "API_EG.CFT.ACCS.ZS_DS2_en_csv_v2_6378.zip"),
            },
            {
                "source": "World Bank population indicator SP.POP.TOTL",
                "used_for": "Population denominator for people-without-clean-cooking estimates",
                "url_or_path": "https://api.worldbank.org/v2/en/indicator/SP.POP.TOTL?downloadformat=csv",
            },
            {
                "source": "Local workbook: sdg7.1.1_-_access_to_electricity.xlsx",
                "used_for": "Electricity access context, total/rural/urban 2022 values",
                "url_or_path": str(ROOT / "sdg7.1.1_-_access_to_electricity.xlsx"),
            },
            {
                "source": "Local Oloika SQLite: HA_Oloika.sqlite",
                "used_for": "Smart-plug power, energy, voltage, and connection summaries",
                "url_or_path": str(ONE / "HA_Oloika.sqlite"),
            },
            {
                "source": "Local Victron CSV: OloikaMinigridUniversityofSouthampton_Victron_June_2025.csv",
                "used_for": "Mini-grid PV, consumption, battery SOC, and daily energy summaries",
                "url_or_path": str(ONE / "OloikaMinigridUniversityofSouthampton_Victron_June_2025.csv"),
            },
            {
                "source": "Local PDF: UNHCR-Case-Study.pdf",
                "used_for": "Implementation lessons from clean-cooking fuel transition in refugee camps",
                "url_or_path": str(ONE / "UNHCR-Case-Study.pdf"),
            },
        ],
        "assumptions": [
            {
                "topic": "Population sizing",
                "assumption": "People without clean cooking = population x (100 - clean-cooking access %) / 100, using 2023 access and 2023 population.",
            },
            {
                "topic": "Oloika e-cooker kWh",
                "assumption": "Cumulative smart-plug energy readings are treated as more reliable than irregular power integration for kWh totals.",
            },
            {
                "topic": "Session detection",
                "assumption": "A new cooking session starts after a power-data gap greater than 20 minutes; values below 100 W were already excluded in the source data.",
            },
            {
                "topic": "Mini-grid consumption",
                "assumption": "AC consumption kWh is integrated from power telemetry with gaps over 30 minutes excluded.",
            },
            {
                "topic": "Cost estimates",
                "assumption": "Budget ranges are order-of-magnitude hackathon planning estimates, not vendor quotes.",
            },
        ],
    }


def main():
    country = country_data()
    ecooker = oloika_ecooker_data()
    minigrid = minigrid_data(ecooker["overall"]["total_e_cooker_kwh_from_cumulative_readings"])
    concept = concept_data(country["country_kpis"], ecooker, minigrid)
    data = {
        "country": country,
        "ecooker": ecooker,
        "minigrid": minigrid,
        "concept": concept,
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "aggregate_data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
