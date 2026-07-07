#!/usr/bin/env python3
"""Per-plug / per-household cooking-session distributions from HA_Oloika.sqlite.

Reproduces the pipeline's session definition (build/prepare_data.py):
  - split a plug's power stream into sessions when the gap between consecutive
    readings exceeds 20 min;
  - duration = last-first; approx_kwh = sum(power * dt), dt capped at 20 min;
  - a session is VALID if duration >= 2 min OR approx_kwh >= 0.02 kWh.
Adds: local EAT cooking hour (UTC+3), per-plug + per-household distributions,
green-light (solar-window) share of sessions and energy, active days.
Pure stdlib (no pandas) so it runs anywhere.
"""
import sqlite3, statistics as st
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "raw" / "HA_Oloika.sqlite"
PLUG_HH = {"002": "B", "006": "B", "010": "H", "011": "H",
           "013": "E", "015": "F", "017": "G", "018": "G"}
EAT = timezone(timedelta(hours=3))
GAP = 20 * 60          # session split threshold (s)
DT_CAP = 20 / 60       # hours, energy-integration cap per interval


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT plug,last_changed,gl,value FROM pow WHERE value IS NOT NULL ORDER BY plug,last_changed"
).fetchall()
con.close()

by_plug = {}
for plug, ts, gl, val in rows:
    by_plug.setdefault(plug, []).append((parse(ts), str(gl).upper() == "TRUE", float(val)))

sessions = []       # one dict per valid session
for plug, recs in by_plug.items():
    recs.sort(key=lambda r: r[0])
    # split into sessions on >20min gaps
    sess, prev = [], None
    for t, gl, v in recs:
        if prev is not None and (t - prev).total_seconds() > GAP:
            if sess:
                sessions.append((plug, sess)); sess = []
        sess.append((t, gl, v)); prev = t
    if sess:
        sessions.append((plug, sess))

valid = []
for plug, sess in sessions:
    ts = [s[0] for s in sess]
    start, end = min(ts), max(ts)
    dur = (end - start).total_seconds() / 60
    kwh = 0.0
    ss = sorted(sess, key=lambda r: r[0])
    for i in range(len(ss) - 1):
        dt = (ss[i + 1][0] - ss[i][0]).total_seconds() / 3600
        if 0 <= dt <= DT_CAP:
            kwh += ss[i][2] * dt
    kwh /= 1000
    if not (dur >= 2 or kwh >= 0.02):
        continue
    powers = [s[2] for s in sess]
    valid.append({
        "plug": plug, "hh": PLUG_HH.get(plug, ""),
        "start_eat": start.astimezone(EAT), "dur": dur, "kwh": kwh,
        "peak": max(powers), "avg": sum(powers) / len(powers),
        "green": st.mean(1 if s[1] else 0 for s in sess),
        "day": start.astimezone(EAT).date(),
    })

print(f"Total valid sessions: {len(valid)}  (pipeline reports 176)\n")

# ---- per-plug ----
print("PER PLUG")
hdr = ("plug", "hh", "n", "dur_med", "kwh_med", "kwh_tot", "peak_max", "avg_W", "sess/day", "green%")
print("  " + " ".join(f"{h:>8}" for h in hdr))
for plug in sorted(by_plug):
    vs = [v for v in valid if v["plug"] == plug]
    if not vs:
        continue
    days = len({v["day"] for v in vs})
    print("  " + " ".join(f"{x:>8}" for x in (
        plug, PLUG_HH.get(plug, "?"), len(vs),
        f"{st.median(v['dur'] for v in vs):.1f}",
        f"{st.median(v['kwh'] for v in vs):.2f}",
        f"{sum(v['kwh'] for v in vs):.1f}",
        f"{max(v['peak'] for v in vs):.0f}",
        f"{st.mean(v['avg'] for v in vs):.0f}",
        f"{len(vs)/days:.1f}",
        f"{100*st.mean(v['green'] for v in vs):.0f}",
    )))

# ---- per-household ----
print("\nPER HOUSEHOLD (5)")
hdr = ("hh", "plugs", "n", "dur_med", "dur_p25", "dur_p75", "kwh_med", "kwh/day",
       "sess/day", "peak_max", "green%", "peak_meal(EAT)")
print("  " + " ".join(f"{h:>8}" for h in hdr))
persona_rows = {}
for hh in sorted(set(PLUG_HH.values())):
    vs = [v for v in valid if v["hh"] == hh]
    if not vs:
        continue
    days = len({v["day"] for v in vs})
    hours = [v["start_eat"].hour for v in vs]
    # meal-time histogram (EAT), pick modal 2h window
    hist = {}
    for h in hours:
        hist[h] = hist.get(h, 0) + 1
    peak_hour = max(hist, key=hist.get)
    durs = [v["dur"] for v in vs]
    row = {
        "hh": hh, "plugs": sum(1 for p, h in PLUG_HH.items() if h == hh),
        "n": len(vs), "days": days,
        "dur_med": st.median(durs), "dur_p25": pct(durs, .25), "dur_p75": pct(durs, .75),
        "kwh_med": st.median(v["kwh"] for v in vs),
        "kwh_day": sum(v["kwh"] for v in vs) / days,
        "sess_day": len(vs) / days,
        "peak_max": max(v["peak"] for v in vs),
        "green": 100 * st.mean(v["green"] for v in vs),
        "peak_hour": peak_hour,
        "hist": hist,
    }
    persona_rows[hh] = row
    print("  " + " ".join(f"{x:>8}" for x in (
        hh, row["plugs"], row["n"], f"{row['dur_med']:.1f}", f"{row['dur_p25']:.1f}",
        f"{row['dur_p75']:.1f}", f"{row['kwh_med']:.2f}", f"{row['kwh_day']:.2f}",
        f"{row['sess_day']:.1f}", f"{row['peak_max']:.0f}", f"{row['green']:.0f}",
        f"{peak_hour:02d}:00",
    )))

# ---- cooking-hour histogram (EAT), all households ----
print("\nSESSION START HOUR (EAT, all valid sessions)")
allh = {}
for v in valid:
    allh[v["start_eat"].hour] = allh.get(v["start_eat"].hour, 0) + 1
for h in range(24):
    n = allh.get(h, 0)
    if n:
        print(f"  {h:02d}:00 EAT  {'#'*n} {n}")

# ---- green baseline: how much cooking already lands in solar windows ----
green_sessions = st.mean(v["green"] for v in valid) * 100
kwh_green = sum(v["kwh"] * v["green"] for v in valid)
kwh_tot = sum(v["kwh"] for v in valid)
print(f"\nGREEN-WINDOW BASELINE")
print(f"  session-weighted green sample share : {green_sessions:.0f}%")
print(f"  energy already cooked in green      : {100*kwh_green/kwh_tot:.0f}%  "
      f"({kwh_green:.1f} of {kwh_tot:.1f} kWh)")
print(f"  => ~{100-100*kwh_green/kwh_tot:.0f}% of cooking energy is shiftable into solar windows")
