<p align="center"><img src="assets/logo.png" width="120" alt="RepoDiagnose logo"></p>

<h1 align="center">RepoDiagnose</h1>
<p align="center"><b>Your second opinion before you clone.</b></p>

<p align="center">
<img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3">
<img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+">
</p>

**RepoDiagnose ranks GitHub repositories by how their attention behaves over time, by real usage and by maintenance — without reading or running their code.**

A star count tells you how much attention a repository once got, not whether the code is any good. A repo that was shared on social media can collect thousands of stars in a week and then be forgotten. A solid one often grows more slowly and keeps growing. RepoDiagnose looks at the *shape* of the star history (velocity and acceleration), at traces that only real users leave (issues, forks with commits, outside pull requests) and at whether anyone still maintains the code. It then lists the top 10 repositories for your topic with the reasons behind each score.

Typical use: you need a fire-detection, behaviour-analysis or tracking model and there are 300 repositories on GitHub. RepoDiagnose narrows them down to a short list worth trying.

<!-- Add a screenshot of a real run here, e.g.:
![RepoDiagnose results](docs/screenshot.png)
-->

---

## Install and run

**Windows**
1. If Python 3.10 or newer is not installed, get it from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"** during setup.
2. Double-click **`run.bat`**. The first start installs the required packages into a private `.venv` folder (1–2 minutes). Later starts take a few seconds.

**macOS / Linux:** run `run.command` (on Linux you may need `sudo apt install python3-tk`).

**Command line (no interface):**
```
pip install -r requirements.txt
export GITHUB_TOKEN=github_pat_xxx
python repodiagnose_core.py owner/repo1 owner/repo2 --out report
```

**Requirements:** Python 3.10 or newer with tkinter (included in the python.org installers), plus the packages in `requirements.txt` (requests, numpy, matplotlib, openpyxl for Excel export, sv-ttk for the modern look). The launchers install them automatically.

### GitHub token (required)
Without a token GitHub allows only 60 requests per hour, which is not enough for even one repository. In the app, click **"How do I get a token?"**, create a *fine-grained* token with **Repository access → Public repositories (read-only)** and paste it into the token field. No other permissions are needed. If you tick *Remember on this computer*, the token is stored as plain text in `.repodiagnose.json` in your user folder. (Settings saved by earlier versions under the name RepoPulse are picked up automatically.)

---

## Using the search panel

| Field | Meaning |
|---|---|
| **Topic** | Main subject, e.g. `fire detection`. Multi-word terms are searched as a phrase. |
| **Keywords** | Comma-separated extra terms, e.g. `yolo, smoke, cctv`. Each keyword runs as a separate search together with the topic; results are merged. |
| **From / To** | Date range (YYYY-MM-DD). |
| **Date refers to** | *Created*: when the repository was created. *Last updated*: when code was last pushed. |
| **Language** | Optional programming language filter, e.g. `Python`. |
| **Min stars** | Ignore repositories with fewer stars (too little data for a momentum profile). Default 50. |
| **Candidates** | How many of the most relevant search results to score (10–100). Default 20. More = slower and wider, but the extra candidates are less relevant. |
| **Also search READMEs** | Also match text inside README files. Usually brings in large unrelated repositories; leave it off unless needed. |
| **Skip 'awesome' lists** | Excludes link collections ("awesome-…", "a curated list of…") that are not working code. |

**Best results:** 15–20 candidates and a minimum of 50–100 stars. Small repositories have too little data for a reliable star curve, and a long candidate list pulls in less relevant repositories.

Candidates are picked by **relevance** (how many of your searches they appear in, then GitHub's best-match order), not by star count. The RepoDiagnose score then decides the final ranking.

---

## Result columns

Hover over any column heading or value in the app for a short explanation. Value tooltips use that repository's own numbers (for example, the peak pace behind a Crash value).


| Column | What it means |
|---|---|
| **#** | Rank by Score. |
| **Repository** | `owner/name`. Double-click to open it on GitHub. |
| **Score** (0–100) | Sum of the four parts below. The star count is **not** part of the score, so a solid repository with few stars can rank above a famous one. Repositories with less than 26 weeks of star history get a ×0.85 uncertainty discount on every part. Values based on few stars, issues or forks are adjusted (see *Small-number adjustment* below). |
| **Momentum** (0–30) | How healthy the star *velocity* is over time. 40 % **persistence** (current rate vs. peak rate; about 40 % of peak earns full marks), 35 % **plateau length** (26 weeks earns full marks), 25 % **crash** (no sudden drop = full marks; losing 50 % or more of the rate in one week = zero). Trusted fully only when the peak pace reached 10 new stars per week; below that, the measured value is blended with a neutral 15/30. |
| **Usage** (0–30) | Traces left by people who actually used the code. 60 % **distinct issue authors per 1,000 stars** (60 people per 1,000 stars earns full marks; the owner is excluded; based on the latest 500 issues and pull requests), 40 % **active forks** (share of forks whose owner committed on top; 25 % earns full marks; based on the newest 300 forks). |
| **Maint.** (0–25) | Maintenance. 40 % **commits in the last 12 months** (logarithmic; about 100 commits earns full marks), 30 % **recency of the last push** (today = full, 2 years or more = zero), 30 % **share of issues with at least one comment**. |
| **Community** (0–15) | 70 % **number of contributors** (logarithmic; about 30 earns full marks), 30 % **pull requests from people other than the owner** (30 earns full marks). |
| **Stars** | Current star count. Shown for reference only. |
| **Curve shape** | Classification of the star-velocity profile (see below). **· few stars** (grey) means the peak pace was under 5 new stars per week, so the shape rests on small numbers and may be chance. |
| **Plateau (wk)** | Number of consecutive weeks, around the peak, in which the weekly star rate stayed at **50 % of the peak or higher**. Long plateau = lasting interest. 1–3 weeks = a single burst. (The rate is smoothed over 3 weeks, so even a one-day spike shows a plateau of about 3 weeks.) |
| **Crash** | The largest drop of the weekly star **rate** in a single week after the peak, as a share of the peak (negative acceleration). Example: peak 10 new stars/week, the next week 2 new stars/week → 80 %. The total star count never goes down; this is about the pace of new stars. Above 25 % is a sudden collapse. A big drop right after a launch is common; what matters is whether interest continues (see *Curve shape*). With few stars (peak under about 5 new stars per week) this value is noisy. |
| **Data** | *complete*: GitHub's star history accounts for at least 90 % of the current star count. *partial X %*: it accounts for less (stars removed, deleted accounts or gaps in GitHub's data); momentum metrics are then approximate. |

Row colours: **red** = spike and fade (hype suspected), **green** = healthy or steady growth, **amber** = too new to judge, **grey** = few stars, shape uncertain.

### Curve shapes
RepoDiagnose measures the weekly star rate (velocity) and how it changes (acceleration). Rules are checked in this order:

| Shape | Rule | Reading |
|---|---|---|
| **Too new (too early to judge)** | Less than 26 weeks of star history | Not enough history; score discounted ×0.85. |
| **Spike and fade (hype suspected)** | Plateau ≤ 4 weeks **and** crash ≥ 25 % **and** current rate < 5 % of peak | Attention came in one burst and is gone. Typical of viral posts; check carefully before using. |
| **Healthy: rise-plateau-slowdown** | Plateau ≥ 12 weeks **and** decline ≥ 8 weeks (or not declined yet) | Interest grew, held for months and is fading slowly. The pattern of a useful project. |
| **Steady / organic growth** | Current rate ≥ 30 % of peak | Still gaining stars at a good pace. |
| **Normal maturing** | Current rate 8–30 % of peak | Past its peak but still attracting people. |
| **Stagnant** | Current rate < 8 % of peak | Interest has mostly ended. |

### Small-number adjustment
Ratios built on a handful of events are noisy. Eight people opening issues on a 135-star repository looks like "59 per 1,000 stars" (near full marks), and a repository that gets 2–3 stars a week shows a "crash" whenever one week is quiet. Without a correction, small repositories win or lose on luck.

RepoDiagnose therefore pulls each noisy value toward a neutral value, in proportion to how little data it rests on (Bayesian shrinkage with pseudo-counts):

| Value | Neutral value | Weight of the neutral value |
|---|---|---|
| Issue authors per 1,000 stars | 15 | as much as 300 stars |
| Share of active forks | 8 % | as much as 20 forks |
| Share of issues with a comment | 50 % | as much as 5 issues |
| Momentum (whole part) | 15 / 30 | falls linearly from 100 % (no clear peak) to 0 % at a peak of 10 new stars/week |

Example: 8 issue authors on 135 stars → raw 59 per 1,000, adjusted (8 + 4.5) / (135 + 300) × 1,000 ≈ 29 per 1,000. A repository with 2,900 stars and 100 issue authors barely changes (34 → 33).

Trust in the momentum curve is based on the **peak pace**, not the total star count. A 135-star repository that got 100 stars in one week has a reliable spike; one that collected 135 stars at 1 star per week does not. The constants are at the top of `adjusted_inputs()` in `repodiagnose_core.py`.

### Details panel
Selecting a row shows the full breakdown and the reasons in plain sentences. Extra metrics:

- **Rise**: weeks for the rate to climb from 20 % of the peak to the peak. Gradual rise suggests word of mouth.
- **Decline**: weeks from the end of the plateau until the rate falls below 20 % of the peak.
- **Rate in the last 6 months / peak rate** (persistence): how much of the peak pace is still going.
- **Competitor effect**: if a newer repository in your results appeared and an older one then lost at least 30 % more momentum than its own trend predicted, both are flagged. It compares the 24 weeks after the newcomer's first star with the 24 weeks before, against the older repository's earlier trend, so normal decay is not mistaken for substitution.

### Charts
The *Charts* button opens four views of the top 10 (they follow the light or dark mode of the app; the colours are a colour-blind-safe palette):

- **Scores**: where each score comes from; the four parts stacked, with their values.
- **Star curves**: one small chart per repository with new stars per week since the first star, each on its own scale. The grey band is the plateau, the dot is the peak. This is the "diagnosis" view: a wide hump is healthy, a needle is hype.
- **Timeline**: all repositories on one calendar, each row scaled to its own peak. Shows when each one launched and whether a newcomer took over from an older one.
- **Momentum vs usage**: a map with Momentum on one axis and Usage on the other. Top right = used and still alive; bottom right = attention without much sign of use. Dot size = stars; hover a dot to see its name.

### Saving the results
- **HTML / PDF report**: a self-contained web page with the table, the competitor effect, all four charts and a reading guide. It is laid out for printing: open it in your browser and choose *Print → Save as PDF* (A4 landscape).
- **Excel**: a formatted workbook with three sheets: *Results* (every metric, clickable repository links, a colour scale on the score, filters), *Search* (your search settings and the competitor effect) and *Guide* (what each column means).

### Light and dark mode
The button in the top-right corner switches between a light and a dark look. Your choice is remembered.

---

## Will I get the same result if I run it again?

The calculation itself has no randomness: the same data always gives the same scores. Results can still change because the **data is live**:

- **Within minutes:** usually identical. Occasionally a score moves by a few tenths when a new star, issue or commit arrives, and two repositories with almost equal scores may swap places.
- **Over days or weeks:** scores drift. Stars keep arriving, "the last 12 months" and "the last 6 months" windows move, "days since last push" grows. This is intended: RepoDiagnose measures the *current* state.
- **Candidate list:** GitHub's search ranking can change as its index updates. If GitHub returns incomplete search results (it times out on very broad searches), the Log tab shows a warning and the candidate list may differ from run to run.
- **Network errors:** if a repository fails to load, it is skipped and the Log tab says so.

To compare runs, save the CSV each time and compare the files.

---

## How it differs from other tools
- **Star history charts** (e.g. star-history.com, OSS Insight) show the curve; you still have to read it yourself, one repository at a time. RepoDiagnose reads the curve for you and turns its shape into a score.
- **Star velocity / trending trackers** rank repositories by how fast they gain stars, so a viral spike ranks first. RepoDiagnose treats a spike that fades as a warning sign, not a strength.
- **Repository health scorers** check maintenance and project hygiene of a repository you already picked. RepoDiagnose starts from a topic search and compares the candidates against each other, including the competitor effect between them.
- It runs on your own computer with your own token; nothing is sent anywhere except to GitHub's API.

## Where the star data comes from
In July 2026 GitHub restricted the list of stargazers (`/stargazers`) to repository admins. RepoDiagnose uses GitHub's newer star history endpoint (`/stargazers/history`), which returns daily star counts without identities. It has daily resolution and no star cap. Because stargazer identities are no longer visible, RepoDiagnose does not check for fake (empty) accounts.

## Limitations
- RepoDiagnose is a **pre-screen**. Metadata cannot tell you how accurate a model is on *your* cameras or data. Try the top 2–3 repositories yourself before deciding.
- Issue and fork statistics use the latest 500 issues/pull requests and the newest 300 forks to keep requests low.
- Repositories with issues disabled score lower on Usage and Maintenance even if they are good.
- The thresholds (for example "60 issue authors per 1,000 stars") and the small-number priors are reasonable defaults, not scientific constants. They are defined in `adjusted_inputs()`, `score()` and `curve_metrics()` in `repodiagnose_core.py`.

## Files
| File | Purpose |
|---|---|
| `run.bat` | Windows launcher |
| `run.command` | macOS / Linux launcher |
| `repodiagnose.py` | User interface |
| `repodiagnose_core.py` | Data collection and scoring engine (also usable from the command line) |
| `repodiagnose_charts.py` | The four charts (used by the app, the HTML report and the command line) |
| `assets/` | Logo (SVG, PNG, ICO) |
| `requirements.txt` | Python packages |
| `CHANGELOG.md` | Version history |
| `LICENSE` | GNU AGPL v3 |

## Contributing
Bug reports and ideas are welcome as GitHub issues. If a repository ends up somewhere you think it does not belong, open an issue with the search settings and the repository name; those cases are the best way to tune the scoring.

## License
Copyright (C) 2026 Erdal Kaynak.

RepoDiagnose is free software, licensed under the **GNU Affero General Public License v3.0 or later** (see `LICENSE`). You may use, study, modify and share it. If you distribute a modified version, or offer it to others as a network service, you must make your source code available under the same license.
