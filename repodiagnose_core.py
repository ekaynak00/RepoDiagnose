#!/usr/bin/env python3
# RepoDiagnose — Your second opinion before you clone.
# Copyright (C) 2026 Erdal Kaynak
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file.
"""
RepoDiagnose core (repodiagnose_core.py) — compares GitHub repositories WITHOUT
reading or running their code.

Idea: a star count measures attention, not quality. Signals closer to quality:
  1. Star VELOCITY and ACCELERATION -> Does the weekly star rate rise gradually,
                                       hold a plateau and decline slowly (healthy),
                                       or spike like a needle and crash (hype)?
  2. Usage trail                    -> Do people actually run the code and open
                                       issues, fork it and commit on top of it?
  3. Maintenance                    -> Commits in the last 12 months, issue replies
  4. Community                      -> Contributors, pull requests from outsiders
  5. Competitor effect              -> When a newer repo on the same topic appears,
                                       does the older one's momentum drop more than
                                       its own trend predicts? (substitution)
  Note: Star data comes from GitHub's /stargazers/history endpoint (daily
  resolution). The old /stargazers list has been restricted to repository
  admins since July 2026, so fake-star (account profile) checks are no longer
  possible.

Usage:
  export GITHUB_TOKEN=github_pat_xxx     # without a token: 60 requests/hour, not enough
  python repodiagnose_core.py owner/repo1 owner/repo2 ... [--out report]

Output: summary table in the terminal, <out>/scorecard.csv and <out>/report.html
Requires: requests, numpy, matplotlib
"""
import argparse, base64, csv, io, math, os, re, sys, time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

API = "https://api.github.com"
WEEK = 7 * 24 * 3600
NOW = datetime.now(timezone.utc)

PART_LABELS = {"momentum": ("Momentum", 30), "usage": ("Usage", 30),
               "maintenance": ("Maintenance", 25), "community": ("Community", 15)}

SHAPE_YOUNG = "Too new (too early to judge)"
SHAPE_HYPE = "Spike and fade (hype suspected)"
SHAPE_HEALTHY = "Healthy: rise-plateau-slowdown"
SHAPE_STEADY = "Steady / organic growth"
SHAPE_NORMAL = "Normal maturing"
SHAPE_STAGNANT = "Stagnant"


# ----------------------------------------------------------------------------
# GitHub client
# ----------------------------------------------------------------------------
class Cancelled(Exception):
    """The user stopped the run."""


class GH:
    def __init__(self, token=None, stop_event=None):
        self.stop = stop_event
        self.remaining = None
        self.s = requests.Session()
        self.s.headers["Accept"] = "application/vnd.github+json"
        self.token = token
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, params=None, accept=None, headers=None):
        url = path if path.startswith("http") else API + path
        h = {"Accept": accept} if accept else {}
        h.update(headers or {})
        for _ in range(5):
            self._check()
            r = self.s.get(url, params=params, headers=h, timeout=30)
            self.remaining = r.headers.get("X-RateLimit-Remaining", self.remaining)
            if r.status_code == 202:                      # statistics are being computed
                self._sleep(2); continue
            if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
                wait = int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time()
                print(f"  ! Rate limit reached, waiting {int(wait)} s...", file=sys.stderr)
                self._sleep(max(wait, 1) + 1); continue
            if r.status_code >= 500:
                self._sleep(3); continue
            return r
        return r

    def _check(self):
        if self.stop is not None and self.stop.is_set():
            raise Cancelled()

    def _sleep(self, sec):
        """Sleep that can be interrupted by the stop button."""
        end = time.time() + sec
        while True:
            self._check()
            left = end - time.time()
            if left <= 0:
                break
            time.sleep(min(1.0, left))

    @staticmethod
    def last_page(r):
        m = re.search(r'[?&]page=(\d+)>; rel="last"', r.headers.get("Link", ""))
        return int(m.group(1)) if m else None

    def count(self, path, params=None):
        """Total number of records, using the per_page=1 trick."""
        p = dict(params or {}); p["per_page"] = 1
        r = self.get(path, p)
        if r.status_code != 200:
            return 0
        lp = self.last_page(r)
        return lp if lp else len(r.json())


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def api_message(r):
    try:
        return r.json().get("message", "")
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------------------
HISTORY_API_VERSION = "2026-03-10"


def star_curve(gh, repo, total, created_iso):
    """Fetches the star history from GitHub's star history endpoint:
        GET /repos/{owner}/{repo}/stargazers/history
    (In July 2026 GitHub restricted the old /stargazers list to repo admins and
    introduced this identity-free endpoint instead.)
    Response, newest week first: [{week: Sunday 00:00 epoch seconds, total: stars
    that week, days: [7 daily counts]}]. 30 weeks per page, up to 100 pages.
    Daily resolution, complete, no 40,000-star cap.
    Returns: (t, cumulative) points, coverage ratio, method / error text"""
    created = ts(created_iso).timestamp()
    hdr = {"X-GitHub-Api-Version": HISTORY_API_VERSION}
    days = {}
    for page in range(1, 101):
        r = gh.get(f"/repos/{repo}/stargazers/history", {"per_page": 100, "page": page}, headers=hdr)
        if r.status_code != 200:
            if days:                                  # keep what we already have
                break
            return [], 0.0, f"ERROR: star history HTTP {r.status_code} {api_message(r)}".strip()
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        for w in data:
            wk = int(w["week"])
            for i, n in enumerate(w.get("days") or [w.get("total", 0)]):
                days[wk + i * 86400] = days.get(wk + i * 86400, 0) + int(n or 0)
        oldest = min(int(w["week"]) for w in data)
        link = r.headers.get("Link", "")
        if oldest <= created - 7 * 86400 or (link and 'rel="next"' not in link):
            break                                     # reached the repo's creation week
    if not days:
        return [], 0.0, "empty star history"
    ts_sorted = sorted(days)
    first = next((t for t in ts_sorted if days[t] > 0), None)
    if first is None:
        return [], 0.0, "empty star history"
    pts, cum = [(float(first), 0)], 0
    now = NOW.timestamp()
    for t in ts_sorted:
        if t < first or t > now:
            continue
        cum += days[t]
        pts.append((float(min(t + 86400, now)), cum))     # running total at the end of that day
    coverage = min(1.0, cum / max(total, 1))
    return pts, coverage, "complete (star history API)"


def fork_activity(gh, repo, pages=3):
    """In how many forks did the owner actually commit? (pushed_at > created_at + 1 day)"""
    total = active = 0
    for p in range(1, pages + 1):
        r = gh.get(f"/repos/{repo}/forks", {"per_page": 100, "page": p, "sort": "newest"})
        if r.status_code != 200 or not r.json():
            break
        for f in r.json():
            total += 1
            if f.get("pushed_at") and ts(f["pushed_at"]) - ts(f["created_at"]) > timedelta(days=1):
                active += 1
    return total, active


def issue_stats(gh, repo, owner, pages=5):
    """Latest ≤500 issues/PRs: distinct issue authors, share answered, share
    closed, PRs from outsiders."""
    issues, prs = [], []
    for p in range(1, pages + 1):
        r = gh.get(f"/repos/{repo}/issues", {"state": "all", "per_page": 100, "page": p})
        if r.status_code != 200 or not r.json():
            break
        for it in r.json():
            (prs if "pull_request" in it else issues).append(it)
    authors = {i["user"]["login"] for i in issues if i.get("user") and i["user"]["login"] != owner}
    answered = sum(1 for i in issues if i.get("comments", 0) > 0)
    closed = sum(1 for i in issues if i["state"] == "closed")
    outside_prs = sum(1 for i in prs if i.get("user") and i["user"]["login"] != owner)
    return dict(n_issue=len(issues), issue_authors=len(authors),
                answered=answered / len(issues) if issues else 0.0,
                closed=closed / len(issues) if issues else 0.0,
                outside_prs=outside_prs)


# ----------------------------------------------------------------------------
# Curve analysis
# ----------------------------------------------------------------------------
def weekly_series(pts, total_stars):
    """Puts the cumulative points on a weekly grid and returns the weekly star rate."""
    if len(pts) < 5:
        return None
    t = np.array([p[0] for p in pts]); c = np.array([p[1] for p in pts], float)
    t0, t1 = t[0], NOW.timestamp()
    # From the last known star to today: close the gap to the total only if the
    # data is complete. Bridging a gap with a straight line would fake a plateau.
    if total_stars - c[-1] <= max(5, 0.02 * total_stars):
        t = np.append(t, t1); c = np.append(c, max(total_stars, c[-1]))
    else:
        t1 = t[-1]
    grid = np.arange(t0, t1 + WEEK, WEEK)
    cum = np.interp(grid, t, c)
    rate = np.diff(cum)
    weeks = grid[1:]
    return weeks, rate, cum


def curve_metrics(weeks, rate):
    """Profile built on the weekly star VELOCITY (v) and its change, ACCELERATION
    (a = Δv). Healthy: v rises gradually (small a>0) -> holds for a while (a≈0,
    plateau) -> declines slowly (small a<0). Hype: v shoots up in a week and
    collapses right away (|a| very large relative to the peak, no plateau)."""
    n = len(rate)
    v = np.convolve(rate, np.ones(3) / 3, mode="same") if n >= 3 else rate   # light smoothing
    ipk = int(np.argmax(v)); peak = float(v[ipk]) or 1e-9
    a = np.diff(v) / peak                                     # acceleration normalised to the peak
    total = float(rate.sum()) or 1e-9
    lo, hi = max(0, ipk - 4), min(n, ipk + 5)
    spike_share = float(rate[lo:hi].sum()) / total
    recent = float(rate[-26:].mean()) if n >= 26 else float(rate.mean())
    persistence = recent / peak

    # 1) Rise time: from the first week above 20% of peak up to the peak
    k = ipk
    while k > 0 and v[k - 1] >= 0.2 * peak:
        k -= 1
    rise_w = ipk - k
    # 2) Plateau: consecutive weeks at ≥50% of peak, around the peak
    l = r = ipk
    while l > 0 and v[l - 1] >= 0.5 * peak: l -= 1
    while r < n - 1 and v[r + 1] >= 0.5 * peak: r += 1
    plateau_w = r - l + 1
    # 3) Decline time: from the end of the plateau until the rate drops below 20% of peak
    f = r
    while f < n - 1 and v[f] >= 0.2 * peak: f += 1
    fall_w = f - r if v[f] < 0.2 * peak else None             # None = has not declined yet
    # 4) Crash: largest single-week drop after the peak (as a share of the peak)
    crash = float(-a[ipk:].min()) if ipk < len(a) else 0.0

    if n < 26:
        shape = SHAPE_YOUNG
    elif plateau_w <= 4 and crash >= 0.25 and persistence < 0.05:
        shape = SHAPE_HYPE
    elif plateau_w >= 12 and (fall_w is None or fall_w >= 8):
        shape = SHAPE_HEALTHY
    elif persistence >= 0.30:
        shape = SHAPE_STEADY
    elif persistence >= 0.08:
        shape = SHAPE_NORMAL
    else:
        shape = SHAPE_STAGNANT
    return dict(age_weeks=n, peak_week=datetime.fromtimestamp(weeks[ipk], timezone.utc).date(),
                peak_rate=peak, recent_rate=recent, persistence=persistence, spike_share=spike_share,
                rise_w=rise_w, plateau_w=plateau_w, fall_w=fall_w, crash=crash, shape=shape)


def substitution(a, b):
    """If b appeared after a: over the 24 weeks after b's first star, how far did
    a's momentum deviate from a's own prior trend? (<0.7 => likely substitution)"""
    wa, ra = a["series"][0], a["series"][1]
    t0 = b["first_star"]
    def mean_between(t_lo, t_hi):
        m = (wa >= t_lo) & (wa < t_hi)
        return ra[m].mean() if m.sum() >= 8 else None
    W = 24 * WEEK
    pre2, pre1, post = mean_between(t0 - 2 * W, t0 - W), mean_between(t0 - W, t0), mean_between(t0, t0 + W)
    if None in (pre2, pre1, post) or pre2 <= 0 or pre1 <= 0:
        return None
    observed = post / pre1        # change actually seen after b appeared
    expected = pre1 / pre2        # a's natural decay trend
    return observed / expected if expected > 0 else None


# ----------------------------------------------------------------------------
# Score
# ----------------------------------------------------------------------------
def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# Small-number adjustments. Ratios built on a handful of events are noisy: 8 issue
# authors on a 135-star repo look like "59 per 1,000 stars" (near full marks), and a
# repo that gets 2-3 stars a week shows a "crash" whenever one week is quiet.
# Each noisy measure is therefore pulled toward a neutral value in proportion to
# how little data it rests on (Bayesian shrinkage with pseudo-counts).
PRIOR_AUTHORS_PER_K = 15      # neutral guess: 15 distinct issue authors per 1,000 stars
PRIOR_STARS = 300             # ...worth as much evidence as 300 stars
PRIOR_FORK_ACTIVE = 0.08      # neutral guess: 8% of forks active
PRIOR_FORKS = 20              # ...worth as much evidence as 20 forks
PRIOR_ANSWERED = 0.5          # neutral guess: half of issues get a comment
PRIOR_ISSUES = 5              # ...worth as much evidence as 5 issues
FULL_CONF_RATE = 10           # momentum fully trusted from a peak of 10 new stars/week
LOW_DATA_RATE = 5             # below this peak pace the curve shape is flagged "few stars"


def adjusted_inputs(d):
    """Shrunk versions of the noisy inputs. Large repositories barely change."""
    authors_k = (d["issue_authors"] + PRIOR_AUTHORS_PER_K / 1000 * PRIOR_STARS) / (d["stars"] + PRIOR_STARS) * 1000
    fork_ratio = (d["forks_active"] + PRIOR_FORK_ACTIVE * PRIOR_FORKS) / (d["forks_sampled"] + PRIOR_FORKS)
    answered = (d["answered"] * d["n_issue"] + PRIOR_ANSWERED * PRIOR_ISSUES) / (d["n_issue"] + PRIOR_ISSUES)
    momentum_conf = clamp(d["peak_rate"] / FULL_CONF_RATE)
    return dict(authors_per_k_adj=authors_k, fork_ratio_adj=fork_ratio, answered_adj=answered,
                momentum_conf=momentum_conf, low_data=d["peak_rate"] < LOW_DATA_RATE)


def score(d):
    """Transparent 0-100 score. Weights: momentum 30, usage 30, maintenance 25,
    community 15. Inputs are ratios independent of the star count, adjusted for
    small numbers (see adjusted_inputs), so neither size nor luck decides."""
    s1p = clamp(math.log10(1 + 100 * d["persistence"]) / 1.6)         # 40% persistence ≈ full marks
    s1q = clamp(d["plateau_w"] / 26)                                   # 6-month plateau ≈ full marks
    s1c = 1 - clamp(d["crash"] / 0.5)                                  # 50% crash in one week = 0
    s1_raw = 0.4 * s1p + 0.35 * s1q + 0.25 * s1c                       # momentum profile as measured
    c = d["momentum_conf"]
    s1 = c * s1_raw + (1 - c) * 0.5                                    # little data -> toward neutral (15/30)
    s2a = clamp(d["authors_per_k_adj"] / 60)                           # 60 distinct people per 1000 stars
    s2b = clamp(d["fork_ratio_adj"] / 0.25)                            # 25% of forks active
    s2 = 0.6 * s2a + 0.4 * s2b
    s3a = clamp(math.log10(1 + d["commits_12m"]) / 2)                  # 100 commits a year
    s3b = clamp(1 - d["days_since_push"] / 730)                        # untouched for 2 years = 0
    s3c = d["answered_adj"]
    s3 = 0.4 * s3a + 0.3 * s3b + 0.3 * s3c
    s4 = clamp(math.log10(1 + d["contributors"]) / 1.5) * 0.7 + clamp(d["outside_prs"] / 30) * 0.3
    k = 0.85 if d["shape"] == SHAPE_YOUNG else 1.0                     # uncertainty discount for young repos
    parts = dict(momentum=round(k * 30 * s1, 1), usage=round(k * 30 * s2, 1),
                 maintenance=round(k * 25 * s3, 1), community=round(k * 15 * s4, 1))
    return round(sum(parts.values()), 1), parts                       # parts always add up to the score


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
SLOGAN = "Your second opinion before you clone."


def write_html(results, subs, charts, path, note="", logo_path=None):
    """charts = [(title, base64 PNG), ...]. The page is laid out to print cleanly
    (browser: Print -> Save as PDF)."""
    import html as _h
    logo = ""
    if logo_path and os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo = f'<img class="logo" src="data:image/png;base64,{base64.b64encode(f.read()).decode()}" alt="">'
    def shape_cell(d):
        cls = "hype" if d["shape"] == SHAPE_HYPE else "good" if d["shape"] in (SHAPE_HEALTHY, SHAPE_STEADY) else ""
        if d.get("low_data"):
            cls = "low"
        short = {SHAPE_HEALTHY: "Healthy", SHAPE_STEADY: "Steady growth", SHAPE_NORMAL: "Normal maturing",
                 SHAPE_STAGNANT: "Stagnant", SHAPE_HYPE: "Spike and fade", SHAPE_YOUNG: "Too new"}.get(d["shape"], d["shape"])
        return f"<td class='shape {cls}'>{short}{' · few stars' if d.get('low_data') else ''}</td>"
    rows = "".join(
        f"<tr><td class='num'>{i}</td><td class='repo'><a href='https://github.com/{d['repo']}'>{_h.escape(d['repo'])}</a>"
        f"<div class='desc'>{_h.escape((d.get('description') or '')[:110])}</div></td>"
        f"<td class='num'><span class='score' style='--w:{d['score']:.0f}%'>{d['score']:.1f}</span></td>"
        f"<td class='num'>{d['parts']['momentum']}</td><td class='num'>{d['parts']['usage']}</td>"
        f"<td class='num'>{d['parts']['maintenance']}</td><td class='num'>{d['parts']['community']}</td>"
        f"<td class='num'>{d['stars']:,}</td>{shape_cell(d)}"
        f"<td class='num'>{d['plateau_w']}</td><td class='num'>{d['crash']:.0%}</td>"
        f"<td class='num'>{d['persistence']:.0%}</td><td class='num'>{d['issue_authors']}</td>"
        f"<td class='num'>{d['commits_12m']}</td><td class='num'>{d['days_since_push']}</td></tr>"
        for i, d in enumerate(results, 1))
    names = {d["repo"] for d in results}
    subs = sorted([x for x in subs if x[0] in names and x[1] in names], key=lambda x: x[2])[:5]
    srows = "".join(f"<li>After <b>{_h.escape(b)}</b> appeared, <b>{_h.escape(a)}</b> lost <b>{1 - x:.0%}</b> "
                    f"more momentum than its own trend predicted.</li>" for a, b, x in subs) \
        or "<li>No clear substitution between these repositories.</li>"
    figs = "".join(f"<figure><img src='data:image/png;base64,{b64}' alt='{_h.escape(t)}'></figure>" for t, b64 in charts)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>RepoDiagnose Report</title>
<style>
:root{{--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--surface:#fcfcfb;--accent:#0E2A47}}
*{{box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1180px;margin:auto;padding:28px 24px;color:var(--ink);background:var(--surface)}}
header{{display:flex;align-items:center;gap:14px;border-bottom:2px solid var(--accent);padding-bottom:14px;margin-bottom:16px}}
.logo{{width:52px;height:52px}} h1{{margin:0;font-size:24px}} .slogan{{margin:2px 0 0;color:var(--ink2)}}
.meta{{color:var(--ink2);font-size:13px;margin:4px 0}} .print{{margin-left:auto;padding:8px 14px;border:1px solid var(--line);
border-radius:6px;background:#fff;cursor:pointer;font:inherit}}
h2{{font-size:17px;margin:26px 0 10px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th{{text-align:left;background:#f1f0ec;color:var(--ink2);font-weight:600;padding:7px 6px;border-bottom:1px solid var(--line)}}
td{{padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
td.repo{{min-width:240px}} td.shape{{white-space:nowrap}} th{{white-space:nowrap}} td.num,th.num{{text-align:right;white-space:nowrap}}
a{{color:#1f5fbf;text-decoration:none;font-weight:600}} .desc{{color:var(--muted);font-size:11.5px;margin-top:2px}}
.score{{display:inline-block;min-width:64px;padding:2px 6px;border-radius:4px;font-weight:700;
background:linear-gradient(90deg,#d6e6fa var(--w),transparent var(--w))}}
td.hype{{color:#b3261e;font-weight:600}} td.good{{color:#1b7f3b;font-weight:600}} td.low{{color:var(--muted)}}
figure{{margin:14px 0;page-break-inside:avoid;break-inside:avoid}} figure img{{width:100%;border:1px solid var(--line);border-radius:6px}}
ul.guide li{{margin:4px 0;color:var(--ink2);font-size:13px}}
@media print{{
  body{{padding:0;max-width:none;background:#fff}} .print{{display:none}}
  a{{color:var(--ink)}} table{{font-size:9.5px}} td.repo{{min-width:0;width:24%}} tr{{page-break-inside:avoid}}
  h2{{page-break-after:avoid}} .charts{{page-break-before:always}}
  @page{{size:A4 landscape;margin:12mm}}
}}
</style></head><body>
<header>{logo}<div><h1>RepoDiagnose Report</h1><p class="slogan">{SLOGAN}</p></div>
<button class="print" onclick="window.print()">Print / Save as PDF</button></header>
<p class="meta">{note}</p>
<p class="meta">Generated {NOW:%Y-%m-%d}. Score = Momentum (30) + Usage trail (30) + Maintenance (25) + Community (15).
The star count does not enter the score directly.</p>
<h2>Results</h2>
<div style="overflow-x:auto"><table><tr><th class='num'>#</th><th>Repository</th><th class='num'>Score</th>
<th class='num'>Momentum</th><th class='num'>Usage</th><th class='num'>Maint.</th><th class='num'>Community</th>
<th class='num'>Stars</th><th>Curve shape</th><th class='num'>Plateau<br>(wk)</th><th class='num'>Crash</th>
<th class='num'>Rate now<br>/ peak</th><th class='num'>Issue<br>authors</th><th class='num'>Commits<br>12 mo</th>
<th class='num'>Days since<br>push</th></tr>{rows}</table></div>
<h2>Competitor effect</h2><p class="meta">The strongest cases among these repositories (up to five).</p><ul>{srows}</ul>
<div class="charts"><h2>Charts</h2>{figs}</div>
<h2>How to read this</h2><ul class="guide">
<li><b>Momentum:</b> the shape of the weekly star rate. A long plateau and a slow decline mean lasting interest; a needle spike that collapses means hype.</li>
<li><b>Plateau:</b> weeks the weekly star rate stayed at 50% of its peak or higher.</li>
<li><b>Crash:</b> the largest drop of the weekly star rate in a single week after the peak. Above 25% is a sudden collapse.</li>
<li><b>Rate now / peak:</b> how much of the peak pace of new stars is still going in the last 6 months.</li>
<li><b>Issue authors:</b> distinct people who opened issues: the best sign that people actually ran the code.</li>
<li><b>Small-number adjustment:</b> values based on few stars, issues or forks are pulled toward a neutral value; "few stars" marks curves with a peak under 5 new stars per week.</li>
<li>This is a pre-screen. For the final decision, try the top 2-3 repositories on your own data.</li></ul>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ----------------------------------------------------------------------------
def analyze(gh, repo):
    print(f"→ {repo}", file=sys.stderr)
    m = gh.get(f"/repos/{repo}")
    if m.status_code != 200:
        print(f"  ! not found (HTTP {m.status_code}) {api_message(m)}", file=sys.stderr); return None
    m = m.json(); owner = m["owner"]["login"]
    pts, coverage, method = star_curve(gh, repo, m["stargazers_count"], m["created_at"])
    if method.startswith("ERROR"):
        print(f"  ! {method}", file=sys.stderr); return None
    if coverage < 0.9:
        print(f"  ! Star history covers only {coverage:.0%} of the total; momentum metrics are approximate",
              file=sys.stderr)
    ser = weekly_series(pts, m["stargazers_count"])
    if ser is None:
        print("  ! not enough star data", file=sys.stderr); return None
    cm = curve_metrics(*ser[:2])
    f_tot, f_act = fork_activity(gh, repo)
    ist = issue_stats(gh, repo, owner)
    since = (NOW - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = dict(repo=repo, stars=m["stargazers_count"], forks=m["forks_count"],
             created=m["created_at"][:10], first_star=pts[0][0], series=ser, coverage=coverage, method=method,
             days_since_push=(NOW - ts(m["pushed_at"])).days, archived=m.get("archived", False),
             commits_12m=gh.count(f"/repos/{repo}/commits", {"since": since}),
             contributors=gh.count(f"/repos/{repo}/contributors", {"anon": 1}),
             releases=gh.count(f"/repos/{repo}/releases"),
             active_fork_ratio=f_act / f_tot if f_tot else 0.0, forks_sampled=f_tot, forks_active=f_act,
             **cm, **ist)
    d.update(adjusted_inputs(d))
    d["score"], d["parts"] = score(d)
    return d


def find_substitutions(res):
    subs = []
    for x in res:
        for y in res:
            if y["first_star"] > x["first_star"] + 26 * WEEK:
                v = substitution(x, y)
                if v is not None and v < 0.7:
                    subs.append((x["repo"], y["repo"], v))
    return subs


CSV_KEYS = ["repo", "score", "stars", "shape", "persistence", "spike_share", "rise_w", "plateau_w", "fall_w",
            "crash", "peak_week", "issue_authors", "n_issue", "answered", "closed", "outside_prs",
            "active_fork_ratio", "commits_12m", "days_since_push", "contributors", "releases", "method",
            "coverage", "created", "peak_rate", "momentum_conf", "low_data", "authors_per_k_adj",
            "fork_ratio_adj", "answered_adj"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repos", nargs="+", help="in owner/repo form")
    ap.add_argument("--out", default="report")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    a = ap.parse_args()
    gh = GH(a.token)
    res = [d for d in (analyze(gh, r) for r in a.repos) if d]
    if not res:
        sys.exit("No repository could be analysed.")
    res.sort(key=lambda d: -d["score"])
    subs = find_substitutions(res)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "scorecard.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(CSV_KEYS); [w.writerow([d[k] for k in CSV_KEYS]) for d in res]
    import repodiagnose_charts as ch
    top = res[:10]
    charts = [(title, ch.to_b64(fn(top, "light"))) for title, fn in ch.ALL_CHARTS]
    here = os.path.dirname(os.path.abspath(__file__))
    write_html(top, subs, charts, os.path.join(a.out, "report.html"),
               logo_path=os.path.join(here, "assets", "logo_64.png"))
    print(f"\n{'Repository':40} {'Score':>5} {'Stars':>7} {'Plat.':>6} {'Crash':>6}  Shape")
    for d in res:
        print(f"{d['repo'][:40]:40} {d['score']:5.1f} {d['stars']:7d} {d['plateau_w']:5d}w {d['crash']:6.0%}  {d['shape']}")
    for x, y, v in subs:
        print(f"  substitution: after {y} appeared, {x} lost {1 - v:.0%} more momentum than its trend predicted")
    print(f"\nReport: {a.out}/report.html")


if __name__ == "__main__":
    main()
