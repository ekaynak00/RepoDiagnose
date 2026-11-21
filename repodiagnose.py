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
RepoDiagnose — Your second opinion before you clone.

Searches GitHub for a topic and keywords, collects repositories within a date
range, scores each one without reading or running its code, and lists the top
10 with the reasons behind each score.

Score (0-100): Momentum 30 + Usage trail 30 + Maintenance 25 + Community 15.
The star count does not enter the score directly. Details: repodiagnose_core.py
"""
import base64, io, json, os, queue, re, sys, threading, webbrowser
from datetime import date, datetime, timezone

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repodiagnose_core as rk
import repodiagnose_charts as ch

try:                                   # modern Windows 11 style theme (optional)
    import sv_ttk
except Exception:
    sv_ttk = None

SLOGAN = "Your second opinion before you clone."
ASSETS = os.path.join(HERE, "assets")

# Colours for the parts of the UI that the ttk theme does not cover
UI = {
    "light": dict(text_bg="#fbfbfb", text_fg="#1c1c1c", muted="#5f6368", tip_bg="#ffffe1", tip_fg="#222222",
                  tip_border="#c9c9a3", hype="#b3261e", good="#1b7f3b", young="#8a6d00", lowdata="#6b6b6b"),
    "dark": dict(text_bg="#1f1f1f", text_fg="#e8e8e8", muted="#a8a8a8", tip_bg="#2d2d2d", tip_fg="#f0f0f0",
                 tip_border="#555555", hype="#ff8a80", good="#7ee2a8", young="#ffd36e", lowdata="#a0a0a0"),
}

APP = "RepoDiagnose"
VERSION = "1.0.0"
CONF = os.path.join(os.path.expanduser("~"), ".repodiagnose.json")
TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def parse_date(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Could not read the date '{s}'. Example: 2024-01-31")


OLD_CONF = os.path.join(os.path.expanduser("~"), ".repopulse.json")     # settings file before the rename


def load_conf():
    for path in (CONF, OLD_CONF):              # carry over settings and token from the old name
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def save_conf(d):
    try:
        with open(CONF, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


class QueueWriter(io.TextIOBase):
    """Routes the warnings the core writes to stderr into the Log tab."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s.strip():
            self.q.put(("log", s.rstrip()))
        return len(s)


def _term(t):
    """Quote multi-word terms so "fire detection" is searched as a phrase."""
    t = t.strip().strip('"')
    return f'"{t}"' if " " in t else t


def build_queries(topic, keywords, field, d1, d2, min_stars, language, readme):
    where = "in:name,description,topics" + (",readme" if readme else "")
    filt = f"{field}:{d1:%Y-%m-%d}..{d2:%Y-%m-%d} stars:>={min_stars} fork:false archived:false {where}"
    if language:
        filt += f" language:{language}"
    kws = [_term(k) for k in keywords.split(",") if k.strip()]
    qs = []
    if topic.strip():
        tp = _term(topic)
        qs.append(f"{tp} {filt}")
        qs += [f"{tp} {k} {filt}" for k in kws]
    else:
        qs += [f"{k} {filt}" for k in kws]
    return qs[:8]                              # the search API allows 30 requests per minute


LIST_HINTS = ("curated list", "awesome list", "a list of", "list of awesome", "collection of resources")


def is_list_repo(it):
    """Collections such as 'awesome-xxx' are link lists, not working code."""
    name = it["full_name"].split("/")[1].lower()
    desc = (it.get("description") or "").lower()
    return name.startswith("awesome") or any(h in desc for h in LIST_HINTS)


def search_candidates(gh, queries, n, log, skip_lists=True):
    """Runs each query with GitHub's best-match ordering. Candidates are ranked by
    how many queries they appeared in, then by best-match position. Stars play no
    part at this stage; the RepoDiagnose score decides the final ranking."""
    pool, skipped = {}, 0
    for q in queries:
        r = gh.get("/search/repositories", {"q": q, "per_page": 100})
        if r.status_code != 200:
            log(f"  ! Search error (HTTP {r.status_code}) {rk.api_message(r)}")
            continue
        if r.json().get("incomplete_results"):
            log("  ! GitHub returned incomplete search results (search timed out on its side). "
                "Candidates may differ from run to run; try again or narrow the search.")
        for pos, it in enumerate(r.json().get("items", [])):
            if skip_lists and is_list_repo(it):
                skipped += 1
                continue
            e = pool.setdefault(it["full_name"], {"hits": 0, "best": pos, "item": it})
            e["hits"] += 1
            e["best"] = min(e["best"], pos)
        log(f"  search: {q.split(' created:')[0].split(' pushed:')[0]}  → {len(pool)} candidates so far")
    if skipped:
        log(f"  Skipped {skipped} list/collection ('awesome') results.")
    ranked = sorted(pool.values(), key=lambda e: (-e["hits"], e["best"]))
    return [e["item"] for e in ranked[:n]], len(pool)


# ----------------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------------
COLS = [("rank", "#", 34), ("repo", "Repository", 200), ("score", "Score", 168), ("mom", "Momentum", 82),
        ("use", "Usage", 56), ("mnt", "Maint.", 58), ("com", "Community", 86), ("stars", "Stars", 58),
        ("shape", "Curve shape", 225), ("plateau", "Plateau (wk)", 92), ("crash", "Crash", 56), ("data", "Data", 78)]


# ----------------------------------------------------------------------------
# Hover help for the results table
# ----------------------------------------------------------------------------
HEAD_TIPS = {
    "rank": "Rank by Score.",
    "repo": "owner/name. Double-click a row to open the repository on GitHub.",
    "score_bar": "Score shown as a bar: each block is 10 points.",
    "score": "Total score, 0-100 = Momentum + Usage + Maint. + Community.\n"
             "The star count is not part of it, so a small but well-used repository can outrank a famous one.\n"
             "Repositories with less than 26 weeks of star history get a x0.85 discount.\n"
             "Small-number adjustment: values based on few stars, issues or forks are pulled toward a neutral "
             "value, so a tiny repository cannot win or lose on luck.",
    "mom": "Momentum (0-30): how healthy the weekly star rate is over time.\n"
           "  • 40%  Is interest still alive? (rate in the last 6 months vs. the peak rate)\n"
           "  • 35%  How long the rate stayed near the peak (Plateau)\n"
           "  • 25%  No sudden collapse after the peak (Crash)\n"
           "Trusted fully only from a peak of 10 new stars/week; below that it is pulled toward 15/30 (neutral).",
    "use": "Usage (0-30): traces that only real users leave.\n"
           "  • 60%  Distinct people who opened issues, per 1,000 stars\n"
           "  • 40%  Share of forks whose owner committed code on top\n"
           "Both are adjusted for small numbers: on a repository with few stars or forks, a handful of "
           "issue authors does not count as a high rate.",
    "mnt": "Maintenance (0-25): is anyone still looking after the code?\n"
           "  • 40%  Commits in the last 12 months\n"
           "  • 30%  How recently code was pushed\n"
           "  • 30%  Share of issues with at least one comment",
    "com": "Community (0-15):\n"
           "  • 70%  Number of contributors\n"
           "  • 30%  Pull requests from people other than the owner",
    "stars": "Current star count. For reference only; it is not part of the score.",
    "shape": "The pattern of the weekly star rate over the repository's life.\n"
             "Hover over a value in this column to see what it means.\n"
             "'· few stars' (grey): the peak was under 5 new stars/week, so the shape is uncertain.",
    "plateau": "Plateau: how many weeks in a row the weekly star rate stayed at 50% of its peak or higher.\n"
               "Long plateau = lasting interest. 2-3 weeks = one short burst.",
    "crash": "Crash: after the weekly star rate peaked, the biggest drop of that RATE within a single week, "
             "as a share of the peak.\n"
             "Example: peak 10 new stars/week, the next week 2 new stars/week -> 80%.\n"
             "It is about the rate of new stars, not the total: the total never goes down.\n"
             "A big drop right after a launch is common; what matters is whether interest continues "
             "(see Curve shape). With few stars (peak under ~5 stars/week) this value is noisy.",
    "data": "complete: GitHub's star history covers at least 90% of the current stars.\n"
            "partial: it covers less, so the momentum values are approximate.",
}

SHAPE_TIPS = {
    rk.SHAPE_YOUNG: "Too new: less than 26 weeks of star history. Too early to judge the pattern; "
                    "every part of the score gets a x0.85 discount.",
    rk.SHAPE_HYPE: "Spike and fade: stars came in one short burst (plateau of 4 weeks or less), the rate "
                   "collapsed (crash of 25% or more) and new stars now arrive at under 5% of the peak pace. "
                   "Typical of a viral post. Check carefully before using.",
    rk.SHAPE_HEALTHY: "Healthy: interest grew, stayed near the peak for at least 12 weeks and is fading "
                      "slowly. The pattern of a project people keep finding useful.",
    rk.SHAPE_STEADY: "Steady / organic growth: new stars still arrive at 30% or more of the peak pace. "
                     "Interest is very much alive.",
    rk.SHAPE_NORMAL: "Normal maturing: past its peak, but new stars still arrive at 8-30% of the peak pace. "
                     "Typical of an older project that people still use.",
    rk.SHAPE_STAGNANT: "Stagnant: new stars arrive at less than 8% of the peak pace. Interest has mostly "
                       "ended; check whether the code is still maintained and works for you.",
}


def cell_tip(key, d):
    """Explanation of one table cell, using that repository's own numbers."""
    p = d["parts"]
    per_k = d["issue_authors"] * 1000 / max(d["stars"], 1)
    if key == "score":
        return (f"Momentum {p['momentum']} + Usage {p['usage']} + Maint. {p['maintenance']} + "
                f"Community {p['community']} = {d['score']:.1f}")
    if key == "mom":
        t = (f"New stars now arrive at {d['persistence']:.0%} of the peak pace · plateau {d['plateau_w']} wk · "
             f"crash {d['crash']:.0%}\nTrust in this curve: {d['momentum_conf']:.0%} "
             f"(peak about {d['peak_rate']:.1f} new stars/week; full trust from 10).")
        if d["momentum_conf"] < 1:
            t += f" The remaining {1 - d['momentum_conf']:.0%} is filled with a neutral 15/30."
        return t + "\n\n" + HEAD_TIPS["mom"]
    if key == "use":
        return (f"{d['issue_authors']} distinct issue authors on {d['stars']} stars = {per_k:.0f} per 1,000 stars; "
                f"after the small-number adjustment {d['authors_per_k_adj']:.0f} (60 earns full marks).\n"
                f"Forks: {d['forks_active']} of {d['forks_sampled']} checked are active ({d['active_fork_ratio']:.0%}); "
                f"adjusted {d['fork_ratio_adj']:.0%} (25% earns full marks).")
    if key == "mnt":
        return (f"{d['commits_12m']} commits in 12 months · last push {d['days_since_push']} days ago · "
                f"{d['answered']:.0%} of {d['n_issue']} issues commented (adjusted {d['answered_adj']:.0%})")
    if key == "com":
        return f"{d['contributors']} contributors · {d['outside_prs']} pull requests from outsiders"
    if key == "stars":
        return f"{d['stars']} stars · {d['forks']} forks. Not part of the score."
    if key == "shape":
        t = SHAPE_TIPS.get(d["shape"], d["shape"])
        if d["low_data"]:
            t += (f"\n\nFew stars: the peak was only about {d['peak_rate']:.1f} new stars/week, so this shape "
                  "rests on small numbers and may be chance. Momentum is pulled toward neutral accordingly.")
        return t
    if key == "plateau":
        return (f"The weekly star rate stayed at 50% of its peak or higher for {d['plateau_w']} weeks in a row "
                f"(peak about {d['peak_rate']:.1f} new stars/week, week of {d['peak_week']:%Y-%m-%d}).")
    if key == "crash":
        drop = d["crash"] * d["peak_rate"]
        t = (f"Peak pace: about {d['peak_rate']:.1f} new stars/week. After the peak, the pace fell by "
             f"{d['crash']:.0%} of that (about {drop:.1f} stars/week) within a single week.")
        if d["low_data"]:
            t += ("\nLow numbers: with so few stars per week, one quiet week looks like a crash. "
                  "Treat this value with caution.")
        return t
    if key == "data":
        return f"GitHub's star history covers {d['coverage']:.0%} of the current stars."
    return HEAD_TIPS.get(key)


class TreeTooltip:
    """Small help box for Treeview headings and cells."""
    colors = UI["light"]

    def __init__(self, tree, text_fn, delay=450):
        self.tree, self.text_fn, self.delay = tree, text_fn, delay
        self.win = self.after_id = self.key = None
        tree.bind("<Motion>", self._motion, add="+")
        for ev in ("<Leave>", "<ButtonPress>", "<MouseWheel>"):
            tree.bind(ev, lambda e: self.hide(), add="+")

    def _motion(self, e):
        region = self.tree.identify_region(e.x, e.y)
        col = self.tree.identify_column(e.x)
        row = self.tree.identify_row(e.y) if region == "cell" else ""
        key = (region, col, row)
        if key == self.key:
            return
        self.hide()
        self.key = key
        text = self.text_fn(region, col, row)
        if text:
            self.after_id = self.tree.after(self.delay, lambda: self._show(text, e.x_root, e.y_root))

    def _show(self, text, x, y):
        self.win = tw = tk.Toplevel(self.tree)
        tw.wm_overrideredirect(True)
        try:
            tw.attributes("-topmost", True)
        except tk.TclError:
            pass
        c = self.colors
        frame = tk.Frame(tw, background=c["tip_border"], padx=1, pady=1)
        frame.pack()
        tk.Label(frame, text=text, justify="left", background=c["tip_bg"], foreground=c["tip_fg"],
                 wraplength=460, padx=10, pady=7, font=("Segoe UI", 9)).pack()
        tw.update_idletasks()
        w, h = tw.winfo_width(), tw.winfo_height()
        sw, sh = tw.winfo_screenwidth(), tw.winfo_screenheight()
        x, y = min(x + 14, sw - w - 4), y + 18
        if y + h > sh - 40:
            y = y - h - 30
        tw.wm_geometry(f"+{max(0, x)}+{max(0, y)}")

    def hide(self):
        if self.after_id:
            self.tree.after_cancel(self.after_id)
            self.after_id = None
        if self.win:
            self.win.destroy()
            self.win = None
        self.key = None


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP} — {SLOGAN}")
        root.geometry("1280x880")
        root.minsize(1000, 680)
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.results, self.subs, self.note, self.note_plain = [], [], "", ""
        self.conf = load_conf()
        self.mode = self.conf.get("theme", "light")
        sys.stderr = QueueWriter(self.q)
        self._icons()
        self._build()
        self._apply_theme(self.mode)
        self.root.after(100, self._poll)

    def _icons(self):
        self.logo = None
        try:
            self.logo = tk.PhotoImage(file=os.path.join(ASSETS, "logo_48.png"))
            icons = [tk.PhotoImage(file=os.path.join(ASSETS, f"logo_{s}.png")) for s in (64, 32)]
            self.root.iconphoto(True, *icons)
            self._icon_refs = icons
            if sys.platform.startswith("win"):
                self.root.iconbitmap(os.path.join(ASSETS, "logo.ico"))
        except Exception:
            pass

    # ---------------- layout ----------------
    def _build(self):
        pad = dict(padx=6, pady=4)

        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=14, pady=(12, 4))
        if self.logo:
            ttk.Label(head, image=self.logo).pack(side="left", padx=(0, 10))
        titles = ttk.Frame(head); titles.pack(side="left")
        ttk.Label(titles, text=APP, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        self.l_slogan = ttk.Label(titles, text=SLOGAN, font=("Segoe UI", 10))
        self.l_slogan.pack(anchor="w")
        self.b_theme = ttk.Button(head, text="", command=self._toggle_theme, width=12)
        self.b_theme.pack(side="right")
        ttk.Label(head, text=f"v{VERSION}", font=("Segoe UI", 9)).pack(side="right", padx=10)

        top = ttk.LabelFrame(self.root, text=" Search ", padding=(8, 4))
        top.pack(fill="x", padx=14, pady=(6, 4))
        for c in (1, 3):
            top.columnconfigure(c, weight=1)

        ttk.Label(top, text="Topic:").grid(row=0, column=0, sticky="e", **pad)
        self.v_topic = tk.StringVar(value=self.conf.get("topic", "fire detection"))
        ttk.Entry(top, textvariable=self.v_topic).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(top, text="Keywords (comma-separated):").grid(row=0, column=2, sticky="e", **pad)
        self.v_kw = tk.StringVar(value=self.conf.get("keywords", "yolo, smoke, cctv"))
        ttk.Entry(top, textvariable=self.v_kw).grid(row=0, column=3, sticky="ew", **pad)

        ttk.Label(top, text="From:").grid(row=1, column=0, sticky="e", **pad)
        dfrm = ttk.Frame(top); dfrm.grid(row=1, column=1, sticky="w", **pad)
        d1_default = f"{date.today().year - 3}-01-01"
        d1 = self.conf.get("d1", d1_default)
        try:
            d1 = parse_date(d1).isoformat()               # convert older DD.MM.YYYY settings
        except ValueError:
            d1 = d1_default
        self.v_d1 = tk.StringVar(value=d1)
        self.v_d2 = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(dfrm, textvariable=self.v_d1, width=12).pack(side="left")
        ttk.Label(dfrm, text="  To:").pack(side="left")
        ttk.Entry(dfrm, textvariable=self.v_d2, width=12).pack(side="left")
        self.l_datefmt = ttk.Label(dfrm, text="  YYYY-MM-DD")
        self.l_datefmt.pack(side="left")

        ttk.Label(top, text="Date refers to:").grid(row=1, column=2, sticky="e", **pad)
        rfrm = ttk.Frame(top); rfrm.grid(row=1, column=3, sticky="w", **pad)
        self.v_field = tk.StringVar(value=self.conf.get("field", "created"))
        ttk.Radiobutton(rfrm, text="Created", value="created", variable=self.v_field).pack(side="left")
        ttk.Radiobutton(rfrm, text="Last updated", value="pushed", variable=self.v_field).pack(side="left", padx=12)

        ttk.Label(top, text="Language:").grid(row=2, column=0, sticky="e", **pad)
        ofrm = ttk.Frame(top); ofrm.grid(row=2, column=1, sticky="w", **pad)
        self.v_lang = tk.StringVar(value=self.conf.get("lang", ""))
        ttk.Entry(ofrm, textvariable=self.v_lang, width=12).pack(side="left")
        ttk.Label(ofrm, text="  Min stars:").pack(side="left")
        self.v_min = tk.IntVar(value=self.conf.get("min_stars", 50))
        ttk.Spinbox(ofrm, from_=1, to=10000, textvariable=self.v_min, width=7).pack(side="left")
        ttk.Label(ofrm, text="  Candidates:").pack(side="left")
        self.v_n = tk.IntVar(value=self.conf.get("n", 20))
        ttk.Spinbox(ofrm, from_=10, to=100, textvariable=self.v_n, width=6).pack(side="left")

        xfrm = ttk.Frame(top); xfrm.grid(row=2, column=2, columnspan=2, sticky="w", **pad)
        self.v_readme = tk.BooleanVar(value=False)        # when on, huge unrelated repos tend to appear
        ttk.Checkbutton(xfrm, text="Also search READMEs", variable=self.v_readme).pack(side="left")
        self.v_skip = tk.BooleanVar(value=self.conf.get("skip_lists", True))
        ttk.Checkbutton(xfrm, text="Skip 'awesome' lists", variable=self.v_skip).pack(side="left", padx=14)

        ttk.Label(top, text="GitHub token:").grid(row=3, column=0, sticky="e", **pad)
        tfrm = ttk.Frame(top); tfrm.grid(row=3, column=1, columnspan=3, sticky="ew", **pad)
        self.v_token = tk.StringVar(value=self.conf.get("token", os.environ.get("GITHUB_TOKEN", "")))
        ttk.Entry(tfrm, textvariable=self.v_token, show="•", width=48).pack(side="left")
        self.v_save_tok = tk.BooleanVar(value=bool(self.conf.get("token")))
        ttk.Checkbutton(tfrm, text="Remember on this computer", variable=self.v_save_tok).pack(side="left", padx=10)
        lnk = ttk.Label(tfrm, text="How do I get a token?", foreground="#3a7bd5", cursor="hand2")
        lnk.pack(side="left", padx=8)
        lnk.bind("<Button-1>", lambda e: self._token_help())

        bar = ttk.Frame(self.root); bar.pack(fill="x", padx=14, pady=6)
        self.b_run = ttk.Button(bar, text="▶  Search and Score", command=self.start, style="Accent.TButton")
        self.b_run.pack(side="left", ipadx=6)
        self.b_stop = ttk.Button(bar, text="■  Stop", command=self.cancel, state="disabled")
        self.b_stop.pack(side="left", padx=8)
        self.pb = ttk.Progressbar(bar, mode="determinate", length=260)
        self.pb.pack(side="left", padx=10)
        self.v_status = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.v_status).pack(side="left", fill="x", expand=True)

        pw = ttk.PanedWindow(self.root, orient="vertical")
        pw.pack(fill="both", expand=True, padx=14, pady=(2, 4))

        tf = ttk.LabelFrame(pw, text=" Results — top 10 ", padding=(6, 2))
        self.v_all = tk.BooleanVar(value=False)
        hdr = ttk.Frame(tf); hdr.pack(fill="x", pady=(0, 4))
        self.l_hint = ttk.Label(hdr, text="Hover over a heading or value for help · double-click a row to open it on GitHub")
        self.l_hint.pack(side="left")
        ttk.Checkbutton(hdr, text="Show all analysed candidates", variable=self.v_all,
                        command=self._fill_table).pack(side="right", padx=6)
        tbox = ttk.Frame(tf); tbox.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tbox, columns=[c[0] for c in COLS], show="headings", height=11)
        for key, title, w in COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=w, anchor="w" if key in ("repo", "shape", "data", "score") else "center",
                             stretch=key in ("repo", "shape"))
        sb = ttk.Scrollbar(tbox, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.tree.bind("<Double-1>", lambda e: self._open_repo())
        self.tip = TreeTooltip(self.tree, self._tip_text)
        self.empty = ttk.Label(tbox, justify="center", anchor="center", font=("Segoe UI", 11), text=(
            "No results yet.\n\nEnter a topic and a few keywords, then press  ▶ Search and Score.\n"
            "Tip: 15–20 candidates and a minimum of 50–100 stars give the most reliable ranking."))
        self.empty.place(relx=0.5, rely=0.55, anchor="center")
        pw.add(tf, weight=3)

        nb = ttk.Notebook(pw)
        def text_tab(font, title):
            fr = ttk.Frame(nb)
            t = tk.Text(fr, wrap="word", height=10, font=font, padx=10, pady=8, relief="flat", borderwidth=0)
            sb2 = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
            t.configure(yscrollcommand=sb2.set)
            t.pack(side="left", fill="both", expand=True); sb2.pack(side="right", fill="y")
            nb.add(fr, text=title)
            return t, fr
        self.t_detail, self.f_detail = text_tab(("Segoe UI", 10), "Details and reasons")
        self.t_log, self.f_log = text_tab(("Consolas", 9), "Log")
        self.nb = nb
        pw.add(nb, weight=2)
        self._detail_text(self._help_text())

        bot = ttk.Frame(self.root); bot.pack(fill="x", padx=14, pady=(2, 12))
        self.b_chart = ttk.Button(bot, text="Charts", command=self.show_charts, state="disabled")
        self.b_html = ttk.Button(bot, text="HTML / PDF report", command=self.save_html, state="disabled")
        self.b_xlsx = ttk.Button(bot, text="Excel", command=self.save_excel, state="disabled")
        self.b_open = ttk.Button(bot, text="Open on GitHub", command=self._open_repo, state="disabled")
        for b in (self.b_chart, self.b_html, self.b_xlsx, self.b_open):
            b.pack(side="left", padx=(0, 8))
        self.v_rate = tk.StringVar(value="")
        self.l_rate = ttk.Label(bot, textvariable=self.v_rate)
        self.l_rate.pack(side="right")

    # ---------------- theme ----------------
    def _apply_theme(self, mode):
        self.mode = mode
        style = ttk.Style()
        if sv_ttk:
            sv_ttk.set_theme(mode)
        elif mode == "light" and "clam" in style.theme_names():
            style.theme_use("clam")
        c = UI[mode]
        TreeTooltip.colors = c
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        for t in (self.t_detail, self.t_log):
            t.configure(background=c["text_bg"], foreground=c["text_fg"], insertbackground=c["text_fg"],
                        selectbackground="#3a7bd5")
        for lab in (self.l_slogan, self.l_datefmt, self.l_hint, self.l_rate):
            lab.configure(foreground=c["muted"])
        for tag in ("hype", "good", "young", "lowdata"):
            self.tree.tag_configure(tag, foreground=c[tag])
        self.b_theme.configure(text="☀  Light mode" if mode == "dark" else "☾  Dark mode")

    def _toggle_theme(self):
        self._apply_theme("light" if self.mode == "dark" else "dark")
        self.conf["theme"] = self.mode
        save_conf(self.conf)

    def _help_text(self):
        return ("How it works\n"
                "Hover the mouse over any column heading or value in the results table: a small window explains "
                "what it means for that repository.\n\n"
                "1) Enter a topic and keywords, set the date range and press 'Search and Score'.\n"
                "2) RepoDiagnose searches GitHub, collects candidates and fetches each one's daily star history.\n"
                "3) Each repository is scored on four criteria (100 in total):\n"
                "   • Momentum (30): Does the weekly star rate rise gradually, hold a plateau and decline slowly,\n"
                "     or spike like a needle and crash? Is interest still alive in the last 6 months?\n"
                "   • Usage trail (30): Distinct people who ran the code and opened issues; share of forks with commits.\n"
                "   • Maintenance (25): Commits in the last 12 months, time since last update, share of issues answered.\n"
                "   • Community (15): Number of contributors, pull requests from outsiders.\n"
                "The star count does not enter the score directly, so a solid repo with few stars can rank high.\n\n"
                "Best results: 15–20 candidates and a minimum of 50–100 stars. Small repositories have too little "
                "data for a reliable star curve.\n\n"
                "Note: this is a pre-screen. For the final decision, try the top 2-3 repositories on your own data.")

    def _token_help(self):
        messagebox.showinfo(APP, "Without a GitHub token you get only 60 requests per hour, which is not enough "
                            "for even one repository.\n\n1) Sign in to GitHub.\n2) On the page that opens, "
                            "create a fine-grained token.\n3) Repository access: 'Public repositories "
                            "(read-only)'. No other permissions are needed.\n4) Copy the token and paste it "
                            "into RepoDiagnose.\n\nThe page will now open in your browser.")
        webbrowser.open(TOKEN_URL)

    # ---------------- run ----------------
    def start(self):
        try:
            d1, d2 = parse_date(self.v_d1.get()), parse_date(self.v_d2.get())
            if d1 > d2:
                raise ValueError("The start date cannot be after the end date.")
            n, min_stars = int(self.v_n.get()), int(self.v_min.get())
        except (ValueError, tk.TclError) as e:
            messagebox.showerror(APP, str(e)); return
        if not self.v_topic.get().strip() and not self.v_kw.get().strip():
            messagebox.showerror(APP, "Enter a topic or at least one keyword."); return
        token = self.v_token.get().strip()
        if not token and not messagebox.askyesno(APP, "No token entered. GitHub allows only 60 requests per hour, "
                                                 "so the analysis will most likely stop halfway.\n\nContinue anyway?"):
            return
        save_conf(dict(theme=self.mode, topic=self.v_topic.get(), keywords=self.v_kw.get(), d1=self.v_d1.get(),
                       field=self.v_field.get(), lang=self.v_lang.get(), min_stars=min_stars, n=n,
                       skip_lists=self.v_skip.get(), token=token if self.v_save_tok.get() else ""))
        queries = build_queries(self.v_topic.get(), self.v_kw.get(), self.v_field.get(), d1, d2,
                                min_stars, self.v_lang.get().strip(), self.v_readme.get())
        fld = "created" if self.v_field.get() == "created" else "last updated"
        kw = self.v_kw.get().strip()
        self.note = (f"Topic: <b>{self.v_topic.get().strip() or '-'}</b> · Keywords: <b>{kw or '-'}</b> · "
                     f"{fld} {d1:%Y-%m-%d} – {d2:%Y-%m-%d} · at least {min_stars} stars")
        self.note_plain = re.sub(r"<[^>]+>", "", self.note)
        self.results, self.subs = [], []
        self.tree.delete(*self.tree.get_children())
        self.t_log.delete("1.0", "end")
        self.nb.select(self.f_log)
        self.stop.clear()
        self._busy(True)
        args = (token, queries, n, self.v_skip.get())
        self.worker = threading.Thread(target=self._work, args=args, daemon=True)
        self.worker.start()

    def cancel(self):
        self.stop.set()
        self.v_status.set("Stopping…")

    def _work(self, token, queries, n, skip_lists):
        put = self.q.put
        gh = rk.GH(token or None, self.stop)
        try:
            put(("status", "Searching GitHub…"))
            cands, pool = search_candidates(gh, queries, n, lambda m: put(("log", m)), skip_lists)
            if not cands:
                put(("done", "No repositories match these criteria. Widen the date range or lower the minimum stars."))
                return
            put(("log", f"Found {pool} repositories; analysing the {len(cands)} most relevant."))
            put(("max", len(cands)))
            ok = 0
            for i, it in enumerate(cands, 1):
                name = it["full_name"]
                put(("status", f"{i}/{len(cands)}  analysing {name}…"))
                try:
                    d = rk.analyze(gh, name)
                except rk.Cancelled:
                    raise
                except Exception as e:                         # one bad repo must not stop the run
                    put(("log", f"  ! {name}: {type(e).__name__}: {e}"))
                    d = None
                if d:
                    d["description"] = it.get("description") or ""
                    d["language"] = it.get("language") or ""
                    put(("result", d)); ok += 1
                elif i == 3 and ok == 0:                       # first 3 all failed: stop, something is wrong
                    put(("done", "Error: Could not get the star history of the first 3 repositories. "
                                 "See the 'Log' tab for details."))
                    return
                put(("step", i))
                put(("rate", gh.remaining))
            put(("done", None))
        except rk.Cancelled:
            put(("done", "Stopped. Repositories analysed so far are listed."))
        except Exception as e:
            put(("done", f"Error: {type(e).__name__}: {e}"))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.t_log.insert("end", val + "\n"); self.t_log.see("end")
                elif kind == "status":
                    self.v_status.set(val)
                elif kind == "max":
                    self.pb.configure(maximum=val, value=0)
                elif kind == "step":
                    self.pb.configure(value=val)
                elif kind == "rate" and val is not None:
                    self.v_rate.set(f"GitHub requests left: {val}")
                elif kind == "result":
                    self.results.append(val)
                    self.results.sort(key=lambda d: -d["score"])
                    self._fill_table()
                elif kind == "done":
                    self._finish(val)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, msg):
        self._busy(False)
        self.subs = rk.find_substitutions(self.results)
        if self.results:
            self.nb.select(self.f_detail)
            first = self.tree.get_children()
            if first:
                self.tree.selection_set(first[0]); self.tree.focus(first[0])
        self.v_status.set(msg or f"Done. {len(self.results)} repositories scored.")
        if msg and msg.startswith(("Error", "No repositories")):
            self.nb.select(self.f_log)
            messagebox.showwarning(APP, msg)

    def _busy(self, on):
        self.b_run.configure(state="disabled" if on else "normal")
        self.b_stop.configure(state="normal" if on else "disabled")
        st = "disabled" if on or not self.results else "normal"
        for b in (self.b_chart, self.b_html, self.b_xlsx, self.b_open):
            b.configure(state=st)

    # ---------------- table and details ----------------
    def _visible(self):
        return self.results if self.v_all.get() else self.results[:10]

    def _fill_table(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self._visible(), 1):
            sh = d["shape"]
            if d["low_data"]:
                tag = "lowdata"
            else:
                tag = "hype" if sh == rk.SHAPE_HYPE else "good" if sh in (rk.SHAPE_HEALTHY, rk.SHAPE_STEADY) else \
                      "young" if sh == rk.SHAPE_YOUNG else ""
            shown = sh + (" · few stars" if d["low_data"] else "")
            data = "complete" if d["coverage"] >= 0.9 else f"partial {d['coverage']:.0%}"
            p = d["parts"]
            blocks = int(round(d["score"] / 10))
            self.tree.insert("", "end", iid=d["repo"], tags=(tag,), values=(
                i, d["repo"], f"{'█' * blocks}{'░' * (10 - blocks)}  {d['score']:.1f}", p["momentum"], p["usage"], p["maintenance"], p["community"],
                d["stars"], shown, d["plateau_w"], f"{d['crash']:.0%}", data))
        for s in sel:
            if self.tree.exists(s):
                self.tree.selection_set(s)
        if self.results:
            self.empty.place_forget()

    def _sort_by(self, key):
        rows = [(self.tree.set(k, key), k) for k in self.tree.get_children()]
        def conv(v):
            try:
                return float(str(v).split()[-1].replace("%", ""))
            except ValueError:
                return str(v).lower()
        if getattr(self, "_last", None) == key:
            rev = not self._rev
        else:
            rev = key not in ("repo", "shape", "rank")
        rows.sort(key=lambda t: conv(t[0]), reverse=rev)
        for pos, (_, k) in enumerate(rows):
            self.tree.move(k, "", pos)
        self._last, self._rev = key, rev

    def _tip_text(self, region, col, row):
        try:
            key = COLS[int(col.lstrip("#")) - 1][0]
        except (ValueError, IndexError):
            return None
        if region == "heading":
            return HEAD_TIPS.get(key)
        if region == "cell" and row:
            d = next((r for r in self.results if r["repo"] == row), None)
            return cell_tip(key, d) if d else None
        return None

    def _selected(self):
        s = self.tree.selection()
        if not s:
            return None
        return next((d for d in self.results if d["repo"] == s[0]), None)

    def _detail_text(self, txt):
        self.t_detail.configure(state="normal")
        self.t_detail.delete("1.0", "end")
        self.t_detail.insert("1.0", txt)
        self.t_detail.configure(state="disabled")

    def _show_detail(self):
        d = self._selected()
        if not d:
            return
        rank = self.results.index(d) + 1
        fall = "not declined yet" if d["fall_w"] is None else f"{d['fall_w']} wk"
        why = []
        if d["low_data"]:
            why.append(f"Few stars: the peak pace was only about {d['peak_rate']:.1f} new stars/week, so the curve "
                       f"shape is uncertain. Momentum is trusted {d['momentum_conf']:.0%} and pulled toward neutral.")
        elif d["shape"] == rk.SHAPE_HYPE:
            why.append("Most stars came in one short spike, then interest dropped to almost zero.")
        if d["plateau_w"] >= 12:
            why.append(f"Interest stayed above half of the peak for {d['plateau_w']} weeks: lasting attention.")
        if d["crash"] >= 0.25 and not d["low_data"]:
            why.append(f"After the peak the rate fell by {d['crash']:.0%} in a single week: sudden crash.")
        per_k = d["issue_authors"] * 1000 / max(d["stars"], 1)
        adj = d["authors_per_k_adj"]
        level = "high usage" if adj >= 30 else "moderate" if adj >= 15 else "weak usage trail"
        note = f" (adjusted for small size: {adj:.0f})" if abs(adj - per_k) >= 3 else ""
        why.append(f"{d['issue_authors']} distinct people opened issues = {per_k:.0f} per 1,000 stars{note}: {level}.")
        if d["days_since_push"] > 365:
            why.append(f"No updates for {d['days_since_push']} days: maintenance may have stopped.")
        if d["commits_12m"] >= 50:
            why.append(f"{d['commits_12m']} commits in the last 12 months: actively developed.")
        if d["coverage"] < 0.9:
            why.append(f"Warning: GitHub's star history explains only {d['coverage']:.0%} of the total stars; "
                       "momentum metrics are approximate.")
        rel = [f"  • After {b} appeared, {a} lost {1 - v:.0%} more momentum than its own trend predicted"
               for a, b, v in self.subs if d["repo"] in (a, b)]
        p = d["parts"]
        young = "   (new repository: ×0.85 uncertainty discount on every part)" if d["shape"] == rk.SHAPE_YOUNG else ""
        t = (f"{rank}. {d['repo']}   —   Score {d['score']:.1f} / 100\n"
             f"{d.get('description', '')}\n"
             f"https://github.com/{d['repo']}   ·   Language: {d.get('language') or '-'}   ·   First star: "
             f"{datetime.fromtimestamp(d['first_star'], timezone.utc):%Y-%m-%d}\n\n"
             f"Score breakdown:  Momentum {p['momentum']}/30   Usage {p['usage']}/30   "
             f"Maintenance {p['maintenance']}/25   Community {p['community']}/15{young}\n\n"
             f"Momentum profile: {d['shape']}\n"
             f"  Rise {d['rise_w']} wk · Plateau {d['plateau_w']} wk · Decline {fall} · "
             f"Sharpest weekly drop {d['crash']:.0%}\n"
             f"  Rate in the last 6 months / peak rate: {d['persistence']:.1%}   (peak week {d['peak_week']:%Y-%m-%d}, "
             f"about {d['peak_rate']:.1f} new stars/week; trust in this curve {d['momentum_conf']:.0%})\n"
             f"Usage: {d['stars']} stars · {d['forks']} forks ({d['active_fork_ratio']:.0%} active) · "
             f"{d['issue_authors']} distinct issue authors · {d['outside_prs']} PRs from outsiders\n"
             f"Maintenance: {d['commits_12m']} commits in 12 months · last push {d['days_since_push']} days ago · "
             f"{d['answered']:.0%} of issues answered · {d['closed']:.0%} closed · {d['releases']} releases\n"
             f"Community: {d['contributors']} contributors\n\n"
             "Reasons:\n" + "\n".join("  • " + w for w in why) +
             ("\n\nCompetitor effect:\n" + "\n".join(rel) if rel else ""))
        self._detail_text(t)

    def _open_repo(self):
        d = self._selected()
        if d:
            webbrowser.open(f"https://github.com/{d['repo']}")

    # ---------------- outputs ----------------
    def show_charts(self):
        if not self.results:
            return
        top = self.results[:10]
        win = tk.Toplevel(self.root)
        win.title(f"{APP} — Charts (top {len(top)})")
        win.geometry("1120x700")
        nb = ttk.Notebook(win); nb.pack(fill="both", expand=True, padx=8, pady=8)
        win.rd_canvases = []
        for title, fn in ch.ALL_CHARTS:
            fig = fn(top, self.mode)
            outer = ttk.Frame(nb); nb.add(outer, text=title)
            cv = FigureCanvasTkAgg(fig, master=outer)
            NavigationToolbar2Tk(cv, outer).update()
            cv.get_tk_widget().pack(fill="both", expand=True)
            cv.draw()
            if hasattr(fig, "rd_hover"):
                self._attach_map_hover(cv, fig)
            win.rd_canvases.append(cv)

    def _attach_map_hover(self, canvas, fig):
        """Tooltip on the momentum map: hovering a dot names the repository."""
        ax, sc, results = fig.rd_hover
        t = ch.THEMES[self.mode]
        ann = ax.annotate("", xy=(0, 0), xytext=(14, 14), textcoords="offset points", fontsize=8.5,
                          color=t["ink"], family=ch.FONT, zorder=10,
                          bbox=dict(boxstyle="round,pad=0.5", fc=t["surface"], ec=t["axis"], lw=1))
        ann.set_visible(False)

        def on_move(event):
            if event.inaxes != ax:
                if ann.get_visible():
                    ann.set_visible(False); canvas.draw_idle()
                return
            hit, info = sc.contains(event)
            if hit:
                i = info["ind"][0]; d = results[i]
                ann.xy = sc.get_offsets()[i]
                ann.set_text(f"{i + 1}. {d['repo']}\nScore {d['score']:.1f} · {d['stars']} stars\n"
                             f"Momentum {d['parts']['momentum']} · Usage {d['parts']['usage']}\n{d['shape']}")
                ann.set_visible(True); canvas.draw_idle()
            elif ann.get_visible():
                ann.set_visible(False); canvas.draw_idle()
        canvas.mpl_connect("motion_notify_event", on_move)

    def save_html(self):
        if not self.results:
            return
        p = filedialog.asksaveasfilename(defaultextension=".html", initialfile="RepoDiagnose_report.html",
                                         filetypes=[("HTML", "*.html")])
        if not p:
            return
        top = self.results[:10]
        names = {d["repo"] for d in top}
        charts = [(title, ch.to_b64(fn(top, "light"))) for title, fn in ch.ALL_CHARTS]
        rk.write_html(top, [s for s in self.subs if s[0] in names or s[1] in names], charts, p,
                      note=self.note, logo_path=os.path.join(ASSETS, "logo_64.png"))
        if messagebox.askyesno(APP, "Report saved.\n\nTo get a PDF, open it in your browser and use "
                                    "'Print → Save as PDF' (the page is laid out for printing).\n\n"
                                    "Open it in your browser now?"):
            webbrowser.open("file://" + os.path.abspath(p))

    def save_excel(self):
        if not self.results:
            return
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="RepoDiagnose_results.xlsx",
                                         filetypes=[("Excel workbook", "*.xlsx")])
        if not p:
            return
        try:
            export_excel(self.results, self.subs, p, self.note_plain)
        except ImportError:
            messagebox.showerror(APP, "The 'openpyxl' package is missing. Run run.bat again to install it.")
            return
        self.v_status.set(f"Excel file saved: {p}")
        if messagebox.askyesno(APP, "Excel file saved. Open it now?"):
            try:
                os.startfile(p)                                 # Windows
            except AttributeError:
                webbrowser.open("file://" + os.path.abspath(p))


def export_excel(results, subs, path, note=""):
    """Formatted workbook: Results (colour scale, links, filters), Search, Guide."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter

    head_fill = PatternFill("solid", fgColor="0E2A47")
    head_font = Font(bold=True, color="FFFFFF")
    shape_color = {rk.SHAPE_HYPE: "B3261E", rk.SHAPE_HEALTHY: "1B7F3B", rk.SHAPE_STEADY: "1B7F3B",
                   rk.SHAPE_YOUNG: "8A6D00"}
    cols = [("Rank", 6, None), ("Repository", 38, None), ("Score", 8, "0.0"), ("Momentum /30", 13, "0.0"),
            ("Usage /30", 10, "0.0"), ("Maintenance /25", 15, "0.0"), ("Community /15", 13, "0.0"),
            ("Stars", 9, "#,##0"), ("Curve shape", 34, None), ("Plateau (wk)", 12, "0"), ("Crash", 9, "0%"),
            ("Rate now / peak", 15, "0.0%"), ("Peak stars/week", 15, "0.0"), ("Momentum trust", 15, "0%"),
            ("Issue authors", 13, "0"), ("Issue authors /1k stars (adj.)", 26, "0"),
            ("Active forks (adj.)", 17, "0%"), ("Commits 12 mo", 14, "0"), ("Days since push", 15, "0"),
            ("Issues commented", 16, "0%"), ("Contributors", 13, "0"), ("Outside PRs", 12, "0"),
            ("Releases", 10, "0"), ("Star data", 10, "0%"), ("Created", 12, None), ("Description", 60, None)]
    wb = Workbook()
    ws = wb.active; ws.title = "Results"
    for j, (name, width, _) in enumerate(cols, 1):
        c = ws.cell(row=1, column=j, value=name)
        c.fill, c.font = head_fill, head_font
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.row_dimensions[1].height = 32
    for i, d in enumerate(results, 1):
        p = d["parts"]
        shape = d["shape"] + (" · few stars" if d.get("low_data") else "")
        row = [i, d["repo"], d["score"], p["momentum"], p["usage"], p["maintenance"], p["community"],
               d["stars"], shape, d["plateau_w"], d["crash"], d["persistence"], d["peak_rate"],
               d["momentum_conf"], d["issue_authors"], d["authors_per_k_adj"], d["fork_ratio_adj"],
               d["commits_12m"], d["days_since_push"], d["answered"], d["contributors"], d["outside_prs"],
               d["releases"], d["coverage"], d["created"], d.get("description", "")]
        for j, v in enumerate(row, 1):
            c = ws.cell(row=i + 1, column=j, value=v)
            if cols[j - 1][2]:
                c.number_format = cols[j - 1][2]
        link = ws.cell(row=i + 1, column=2)
        link.hyperlink = f"https://github.com/{d['repo']}"
        link.font = Font(color="1F5FBF", underline="single")
        if not d.get("low_data") and d["shape"] in shape_color:
            ws.cell(row=i + 1, column=9).font = Font(color=shape_color[d["shape"]], bold=True)
        ws.cell(row=i + 1, column=26).alignment = Alignment(wrap_text=False)
    last = len(results) + 1
    ws.conditional_formatting.add(f"C2:C{last}", ColorScaleRule(start_type="num", start_value=0,
                                  start_color="F8696B", mid_type="num", mid_value=50, mid_color="FFEB84",
                                  end_type="num", end_value=100, end_color="63BE7B"))
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{last}"

    ws2 = wb.create_sheet("Search")
    info = [("RepoDiagnose", SLOGAN), ("Version", VERSION), ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Search", note), ("Repositories scored", len(results))]
    for k, (a, b) in enumerate(info, 1):
        ws2.cell(row=k, column=1, value=a).font = Font(bold=True)
        ws2.cell(row=k, column=2, value=b)
    if subs:
        ws2.cell(row=len(info) + 2, column=1, value="Competitor effect").font = Font(bold=True)
        for k, (a, b, v) in enumerate(subs):
            ws2.cell(row=len(info) + 3 + k, column=2,
                     value=f"After {b} appeared, {a} lost {1 - v:.0%} more momentum than its own trend predicted")
    ws2.column_dimensions["A"].width = 22; ws2.column_dimensions["B"].width = 110

    ws3 = wb.create_sheet("Guide")
    ws3.cell(row=1, column=1, value="Column").font = Font(bold=True)
    ws3.cell(row=1, column=2, value="Meaning").font = Font(bold=True)
    guide = [("Score", HEAD_TIPS["score"]), ("Momentum", HEAD_TIPS["mom"]), ("Usage", HEAD_TIPS["use"]),
             ("Maintenance", HEAD_TIPS["mnt"]), ("Community", HEAD_TIPS["com"]), ("Curve shape", HEAD_TIPS["shape"]),
             ("Plateau (wk)", HEAD_TIPS["plateau"]), ("Crash", HEAD_TIPS["crash"]), ("Star data", HEAD_TIPS["data"])]
    guide += [(f"Shape: {k}", v) for k, v in SHAPE_TIPS.items()]
    for k, (a, b) in enumerate(guide, 2):
        ws3.cell(row=k, column=1, value=a).font = Font(bold=True)
        c = ws3.cell(row=k, column=2, value=b)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws3.cell(row=k, column=1).alignment = Alignment(vertical="top")
    ws3.column_dimensions["A"].width = 34; ws3.column_dimensions["B"].width = 110
    wb.save(path)


def main():
    try:                                         # sharp text and own taskbar icon on Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RepoDiagnose.App")
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
