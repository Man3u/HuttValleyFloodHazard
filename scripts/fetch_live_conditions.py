"""
Fetch live Hutt River gauge readings from GWRC's public Hilltop Server, log
them, and flag whether current conditions are outside the recent normal
range -- the data-and-automation layer of the "agentic hazard monitor"
extension to this project. No API key needed; this is a genuinely public,
no-auth government hydrology data service.

WHY THIS FILE EXISTS / HOW IT WAS FOUND:
GWRC's live dashboard (https://graphs.gw.govt.nz) is a JS single-page app
with no documented public API page. Its underlying data calls were found by
opening it in a browser and inspecting the actual network requests it makes
-- they hit https://hilltop.gw.govt.nz/Data.hts, a standard "Hilltop Server"
instance (used by several NZ regional councils). That endpoint is reachable
directly, no login, but it is picky about encoding: site names contain
spaces and MUST be percent-encoded as %20 (i.e. via urllib.parse.quote).
Sending '+' for spaces (what some HTTP client conveniences do by default)
gets silently rejected with a "No data for site ..." error -- this was
hit and diagnosed during development, not assumed.

TWO GAUGES, TWO DIFFERENT REAL SIGNALS -- disclosed honestly, not glossed
over as "the same kind of number":
  - Hutt River at Birchville, measurement "Flow": true volumetric flow in
    m3/sec (mid-valley, downstream of the confluence with major tributaries).
  - Hutt River at Kaitoke, measurement "Stage": water level in mm, NOT
    flow (this site's only live recorder is a "Water Level" data source --
    there is no true flow measurement here). Useful anyway as an upstream
    leading indicator: a stage rise at Kaitoke precedes a flow rise at
    Birchville by roughly the catchment's travel time.

WATCH THRESHOLD: derived from each gauge's own recently-fetched data (the
95th percentile of the lookback window), not a hardcoded number pulled out
of the air -- same discipline as the stream-extraction threshold in
step2_hydrology.py. This is a simple, disclosed heuristic, not a calibrated
flood warning level -- it tells you "this is unusually high compared to the
last N days", nothing more. A human (or the reviewing agent) still decides
what that means.

USAGE:
    python3 scripts/fetch_live_conditions.py
    python3 scripts/fetch_live_conditions.py --lookback-days 60

To run this on a real schedule rather than by hand, see the launchd/cron
setup notes in README.md.
"""

import argparse
import csv
import json
import os
import re
import statistics
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HILLTOP_BASE = "https://hilltop.gw.govt.nz/Data.hts/"

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
LIVE_DIR = os.path.join(DATA_DIR, "live_conditions")
os.makedirs(LIVE_DIR, exist_ok=True)

LOG_CSV = os.path.join(LIVE_DIR, "live_conditions_log.csv")
STATUS_JSON = os.path.join(LIVE_DIR, "latest_status.json")

GAUGES = [
    {
        "site": "Hutt River at Birchville",
        "measurement": "Flow",
        "kind": "flow",
        "units": "m3/sec",
        "note": "Mid-valley volumetric flow -- the primary signal.",
    },
    {
        "site": "Hutt River at Kaitoke",
        "measurement": "Stage",
        "kind": "stage",
        "units": "mm",
        "note": "Upper-catchment water level, not flow -- leading indicator only.",
    },
]

WATCH_PERCENTILE = 95


def quote(s: str) -> str:
    """Percent-encode exactly like a browser's encodeURIComponent (%20 for
    space), NOT like urllib.parse.urlencode (which defaults to '+' for
    space and gets silently rejected by this particular server)."""
    from urllib.parse import quote as _quote
    return _quote(s, safe="")


def fetch_hilltop_xml(site: str, measurement: str, from_dt: datetime, to_dt: datetime) -> str:
    url = (
        f"{HILLTOP_BASE}?Service=Hilltop&Request=GetData"
        f"&Site={quote(site)}&Measurement={quote(measurement)}"
        f"&From={quote(from_dt.strftime('%d/%m/%Y %H:%M:%S'))}"
        f"&To={quote(to_dt.strftime('%d/%m/%Y %H:%M:%S'))}"
        f"&ShowQuality=Yes"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HuttValleyFloodHazard-live-watch/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_readings(xml_text: str):
    """Returns (units, list of (timestamp_str, value_float)). Raises
    ValueError with the server's own message if Hilltop returned an error
    or empty result -- surfaced explicitly, not swallowed."""
    err = re.search(r"<Error>([^<]+)</Error>", xml_text)
    if err:
        raise ValueError(f"Hilltop error: {err.group(1)}")
    units_m = re.search(r"<Units>([^<]*)</Units>", xml_text)
    units = units_m.group(1) if units_m else "unknown"
    rows = re.findall(r"<E><T>([^<]+)</T><I1>([^<]+)</I1>", xml_text)
    if not rows:
        raise ValueError("No <E> data rows found in response")
    readings = [(t, float(v)) for t, v in rows]
    return units, readings


def evaluate_gauge(gauge: dict, lookback_days: int) -> dict:
    now = datetime.now()
    from_dt = now - timedelta(days=lookback_days)
    result = {
        "site": gauge["site"],
        "measurement": gauge["measurement"],
        "kind": gauge["kind"],
        "note": gauge["note"],
        "fetched_at": now.isoformat(timespec="seconds"),
        "ok": False,
    }
    try:
        xml_text = fetch_hilltop_xml(gauge["site"], gauge["measurement"], from_dt, now)
        units, readings = parse_readings(xml_text)
        values = [v for _, v in readings]
        latest_ts, latest_val = readings[-1]
        threshold = _percentile(values, WATCH_PERCENTILE)
        status = "WATCH" if latest_val >= threshold else "NORMAL"
        result.update({
            "ok": True,
            "units": units,
            "n_readings": len(readings),
            "lookback_days": lookback_days,
            "latest_timestamp": latest_ts,
            "latest_value": latest_val,
            "min": min(values),
            "max": max(values),
            "median": statistics.median(values),
            "watch_threshold_p95": round(threshold, 3),
            "status": status,
        })
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        result.update({"ok": False, "error": str(e)})
    return result


def _percentile(values, pct):
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def append_log(results):
    is_new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["fetched_at", "site", "measurement", "units", "latest_timestamp",
                        "latest_value", "watch_threshold_p95", "status", "ok", "error"])
        for r in results:
            w.writerow([
                r.get("fetched_at"), r.get("site"), r.get("measurement"), r.get("units", ""),
                r.get("latest_timestamp", ""), r.get("latest_value", ""),
                r.get("watch_threshold_p95", ""), r.get("status", ""), r.get("ok"),
                r.get("error", ""),
            ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-days", type=int, default=30,
                     help="Days of history to fetch for the watch-threshold baseline (default: 30)")
    args = ap.parse_args()

    print(f"--- Fetching live Hutt River conditions ({datetime.now().isoformat(timespec='seconds')}) ---\n")
    results = []
    for gauge in GAUGES:
        print(f"Querying {gauge['site']} ({gauge['measurement']})...")
        r = evaluate_gauge(gauge, args.lookback_days)
        results.append(r)
        if r["ok"]:
            print(f"  Latest: {r['latest_value']} {r['units']} at {r['latest_timestamp']}")
            print(f"  {args.lookback_days}-day range: {r['min']:.2f}-{r['max']:.2f} "
                  f"(median {r['median']:.2f}), watch threshold (p{WATCH_PERCENTILE}): "
                  f"{r['watch_threshold_p95']:.2f}")
            print(f"  Status: {r['status']}\n")
        else:
            print(f"  FAILED: {r['error']}\n")

    append_log(results)
    with open(STATUS_JSON, "w") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"), "gauges": results}, f, indent=2)

    any_watch = any(r.get("status") == "WATCH" for r in results)
    any_fail = any(not r["ok"] for r in results)
    print(f"Log appended: {LOG_CSV}")
    print(f"Status written: {STATUS_JSON}")
    n_ok = sum(1 for r in results if r["ok"])
    if any_fail:
        print(f"\nNote: {len(results) - n_ok} of {len(results)} gauge queries FAILED -- see 'error' "
              "field above/in the JSON. This is reported, not hidden.")
    if n_ok == 0:
        print("No gauges returned data this run -- cannot assess current conditions. "
              "Check network access to hilltop.gw.govt.nz and retry.")
    elif any_watch:
        print("\n>>> At least one gauge is at/above its recent-history watch threshold. "
              "Share latest_status.json for a reasoned assessment. <<<")
    elif any_fail:
        print(f"\nThe {n_ok} gauge(s) that did return data are within their recent normal range, "
              "but this is a partial picture -- one or more gauges failed to report.")
    else:
        print("\nAll gauges within their recent normal range.")


if __name__ == "__main__":
    main()
