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
Charts for RepoDiagnose. Built on matplotlib's Figure (no pyplot), so they work
inside the Tk window, in the HTML report and on the command line alike.

Four charts, each answering one question:
  score_breakdown   Where does each repository's score come from?
  star_curves       What does each repository's star history look like? (small multiples)
  timeline          When did each repository draw attention, on one calendar?
  momentum_map      Which repositories are both used and still alive?

Colours: a validated colour-blind-safe categorical palette (light and dark steps),
recessive grid and axes, text in ink colours, never in series colours.
"""
import base64, io
from datetime import datetime, timezone

import numpy as np
from matplotlib.figure import Figure
import matplotlib.dates as mdates

import repodiagnose_core as rk

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7",
                  series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
                  on_fill=["#ffffff", "#ffffff", "#ffffff", "#0b0b0b"]),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835",
                 series=["#3987e5", "#d95926", "#199e70", "#c98500"],
                 on_fill=["#ffffff", "#ffffff", "#ffffff", "#ffffff"]),
}
def _pick_font():
    """Choose one installed font once, so matplotlib does not warn on every draw."""
    import logging
    from matplotlib import font_manager
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"):
        if name in installed:
            return name
    return "sans-serif"


FONT = _pick_font()

SHORT_SHAPE = {rk.SHAPE_YOUNG: "Too new", rk.SHAPE_HYPE: "Spike and fade", rk.SHAPE_HEALTHY: "Healthy",
               rk.SHAPE_STEADY: "Steady growth", rk.SHAPE_NORMAL: "Normal maturing",
               rk.SHAPE_STAGNANT: "Stagnant"}


def _short(name, n):
    return name if len(name) <= n else name[: n - 1] + "…"


def _fig(t, w=10.5, h=5.2):
    fig = Figure(figsize=(w, h), dpi=100, facecolor=t["surface"])
    fig.patch.set_facecolor(t["surface"])
    return fig


def _style(ax, t, grid_axis="x"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.tick_params(colors=t["muted"], labelsize=8, length=0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=t["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontfamily(FONT)


def _title(fig, t, title, subtitle):
    fig.text(0.012, 0.975, title, ha="left", va="top", fontsize=12, fontweight="bold", color=t["ink"], family=FONT)
    fig.text(0.012, 0.925, subtitle, ha="left", va="top", fontsize=9, color=t["ink2"], family=FONT)


# ----------------------------------------------------------------------------
def score_breakdown(results, mode="light"):
    """Stacked horizontal bars: Momentum + Usage + Maintenance + Community."""
    t = THEMES[mode]
    fig = _fig(t, h=max(3.2, 0.42 * len(results) + 1.7))
    ax = fig.add_axes([0.30, 0.10, 0.64, 0.70])
    _style(ax, t, "x")
    names = [f"{i}. {_short(d['repo'], 34)}" for i, d in enumerate(results, 1)]
    y = np.arange(len(results))[::-1]
    left = np.zeros(len(results))
    keys = list(rk.PART_LABELS)
    for k, key in enumerate(keys):
        vals = np.array([d["parts"][key] for d in results])
        ax.barh(y, vals, left=left, height=0.62, color=t["series"][k], edgecolor=t["surface"], linewidth=2,
                label=f"{rk.PART_LABELS[key][0]} (max {rk.PART_LABELS[key][1]})")
        for yi, l, v in zip(y, left, vals):
            if v >= 5:                                     # label the segment if it is wide enough
                ax.text(l + v / 2, yi, f"{v:.0f}", ha="center", va="center", fontsize=7.5,
                        color=t["on_fill"][k], family=FONT)
        left += vals
    for yi, total in zip(y, left):
        ax.text(total + 1.2, yi, f"{total:.1f}", va="center", fontsize=9, fontweight="bold", color=t["ink"], family=FONT)
    ax.set_yticks(y, names)
    for lab in ax.get_yticklabels():
        lab.set_color(t["ink"]); lab.set_fontsize(9)
    ax.set_xlim(0, 108); ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_ylim(-0.6, len(results) - 0.4)
    leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=4, frameon=False, fontsize=8.5,
                    handlelength=1.2, columnspacing=1.4)
    for txt in leg.get_texts():
        txt.set_color(t["ink2"])
    _title(fig, t, "Where each score comes from", "Score = Momentum + Usage + Maintenance + Community (0–100). "
           "Stars are not part of the score.")
    return fig


# ----------------------------------------------------------------------------
def star_curves(results, mode="light"):
    """Small multiples: weekly new stars for each repository, its own scale.
    The shaded band is the plateau (rate at ≥50% of peak); the dot is the peak."""
    t = THEMES[mode]
    n = len(results)
    cols = 5 if n > 4 else n
    rows = int(np.ceil(n / cols))
    h = 2.45 * rows + 1.1
    fig = _fig(t, h=h)
    gs = fig.add_gridspec(rows, cols, left=0.03, right=0.99, top=1 - 1.25 / h,   # room for the title block
                          bottom=0.32 / h, wspace=0.18, hspace=0.85)
    c = t["series"][0]
    for i, d in enumerate(results):
        ax = fig.add_subplot(gs[i // cols, i % cols])
        _style(ax, t, None)
        r = d["series"][1]
        v = np.convolve(r, np.ones(3) / 3, mode="same")
        x = np.arange(len(v)) / 52
        ax.fill_between(x, v, color=c, alpha=0.16, linewidth=0)
        ax.plot(x, v, color=c, linewidth=2)
        ipk = int(np.argmax(v)); peak = v[ipk] or 1
        above = np.where(v >= 0.5 * peak)[0]
        if len(above):                                    # contiguous plateau around the peak
            l = r_ = ipk
            while l > 0 and v[l - 1] >= 0.5 * peak: l -= 1
            while r_ < len(v) - 1 and v[r_ + 1] >= 0.5 * peak: r_ += 1
            ax.axvspan(x[l], x[r_], color=t["muted"], alpha=0.14, linewidth=0)
        ax.plot([x[ipk]], [v[ipk]], "o", color=c, markersize=6, markeredgecolor=t["surface"], markeredgewidth=2)
        ax.set_yticks([]); ax.set_ylim(0, peak * 1.25)
        ax.set_xlim(0, max(x[-1], 0.5))
        yrs = int(np.floor(x[-1]))
        ax.set_xticks(range(0, yrs + 1) if yrs >= 1 else [0], [f"{k}y" for k in range(0, yrs + 1)] if yrs >= 1 else ["0y"])
        ax.set_title(f"{i + 1}. {_short(d['repo'].split('/')[1], 22)}", loc="left", fontsize=9,
                     color=t["ink"], fontweight="bold", family=FONT, pad=16)
        label = SHORT_SHAPE.get(d["shape"], d["shape"]) + (" · few stars" if d.get("low_data") else "")
        ax.text(0, 1.04, f"{label} · peak {d['peak_rate']:.0f}/wk", transform=ax.transAxes, fontsize=7.5,
                color=t["ink2"], family=FONT, va="bottom")
    _title(fig, t, "Star curves", "New stars per week since the first star, each on its own scale. "
           "Grey band = plateau (at least half the peak pace); dot = peak.")
    return fig


# ----------------------------------------------------------------------------
def timeline(results, mode="light"):
    """Ridgeline on one calendar: each row is a repository's weekly star rate,
    scaled to its own peak. Shows launch dates and who took over from whom."""
    t = THEMES[mode]
    n = len(results)
    fig = _fig(t, h=max(3.2, 0.48 * n + 1.6))
    ax = fig.add_axes([0.25, 0.10, 0.72, 0.72])
    _style(ax, t, "x")
    c = t["series"][0]
    for i, d in enumerate(results):
        base = n - 1 - i
        w, r = d["series"][0], d["series"][1]
        v = np.convolve(r, np.ones(4) / 4, mode="same")
        v = v / (v.max() or 1) * 0.85
        dates = [datetime.fromtimestamp(s, timezone.utc) for s in w]
        ax.fill_between(dates, base, base + v, color=c, alpha=0.28, linewidth=0)
        ax.plot(dates, base + v, color=c, linewidth=1.5)
        ax.plot([dates[0], dates[-1]], [base, base], color=t["axis"], linewidth=0.8)
    ax.set_yticks(range(n), [f"{n - k}. {_short(results[n - 1 - k]['repo'], 30)}" for k in range(n)])
    for lab in ax.get_yticklabels():
        lab.set_color(t["ink"]); lab.set_fontsize(9)
    ax.set_ylim(-0.2, n)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    _title(fig, t, "When each repository drew attention", "Weekly new stars on one calendar, each row scaled to its "
           "own peak. Later launches next to fading rows can mean one replaced the other.")
    return fig


# ----------------------------------------------------------------------------
MAP_GROUPS = [("Healthy or growing", (rk.SHAPE_HEALTHY, rk.SHAPE_STEADY)),
              ("Spike and fade", (rk.SHAPE_HYPE,)),
              ("Other", None)]


def _group(d):
    if d.get("low_data"):
        return 2
    for gi, (_, shapes) in enumerate(MAP_GROUPS):
        if shapes and d["shape"] in shapes:
            return gi
    return 2


def momentum_map(results, mode="light"):
    """Scatter: Momentum (x) vs Usage (y). Dot size = stars, colour = curve group,
    number = rank. Returns the figure; fig.rd_hover holds data for hover tooltips."""
    t = THEMES[mode]
    fig = _fig(t, h=5.6)
    ax = fig.add_axes([0.08, 0.11, 0.66, 0.72])
    _style(ax, t, "both")
    ax.spines["left"].set_visible(True); ax.spines["left"].set_color(t["axis"])
    ax.set_xlim(0, 31); ax.set_ylim(0, 31)
    ax.set_xticks([0, 10, 20, 30]); ax.set_yticks([0, 10, 20, 30])
    ax.axvline(15, color=t["muted"], linewidth=1, linestyle=(0, (4, 4)))
    ax.axhline(15, color=t["muted"], linewidth=1, linestyle=(0, (4, 4)))
    for x, y, txt, ha, va in ((30.5, 30.5, "Used and alive", "right", "top"),
                              (0.5, 30.5, "Used, interest faded", "left", "top"),
                              (30.5, 0.5, "Attention without use", "right", "bottom"),
                              (0.5, 0.5, "Quiet", "left", "bottom")):
        ax.text(x, y, txt, ha=ha, va=va, fontsize=8.5, color=t["muted"], family=FONT, style="italic")
    ax.set_xlabel("Momentum (0–30)", color=t["ink2"], fontsize=9, family=FONT)
    ax.set_ylabel("Usage (0–30)", color=t["ink2"], fontsize=9, family=FONT)
    xs, ys, sizes, cols = [], [], [], []
    for d in results:
        xs.append(d["parts"]["momentum"]); ys.append(d["parts"]["usage"])
        sizes.append(50 + 6 * np.sqrt(d["stars"])); cols.append(t["series"][_group(d)])
    sc = ax.scatter(xs, ys, s=sizes, c=cols, alpha=0.9, edgecolors=t["surface"], linewidths=2, zorder=3)
    for i, (x, y) in enumerate(zip(xs, ys), 1):
        ax.annotate(str(i), (x, y), xytext=(7, 5), textcoords="offset points", fontsize=8.5,
                    color=t["ink"], fontweight="bold", family=FONT, zorder=4)
    # legend: colour groups + size key
    lax = fig.add_axes([0.77, 0.30, 0.22, 0.50]); lax.axis("off")
    lax.text(0, 1.0, "Curve shape", fontsize=9, fontweight="bold", color=t["ink"], family=FONT, va="top")
    for gi, (label, _) in enumerate(MAP_GROUPS):
        yy = 0.88 - gi * 0.11
        lax.scatter([0.04], [yy], s=90, color=t["series"][gi], edgecolors=t["surface"], linewidths=2)
        lax.text(0.12, yy, label, fontsize=8.5, color=t["ink2"], family=FONT, va="center")
    lax.text(0, 0.48, "Dot size = stars\nNumber = rank in the table", fontsize=8.5, color=t["ink2"],
             family=FONT, va="top", linespacing=1.5)
    lax.set_xlim(0, 1); lax.set_ylim(0, 1.02)
    _title(fig, t, "Momentum vs. usage", "Top right: people use it and interest is still alive. "
           "Bottom right: attention without much sign of use.")
    fig.rd_hover = (ax, sc, results)
    return fig


ALL_CHARTS = [("Scores", score_breakdown), ("Star curves", star_curves),
              ("Timeline", timeline), ("Momentum vs usage", momentum_map)]


def to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    return base64.b64encode(buf.getvalue()).decode()
