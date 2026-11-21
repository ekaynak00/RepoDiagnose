# Changelog

## 1.0.0 — first public release

- Search GitHub by topic, keywords, date range, language and minimum stars; candidates are picked by relevance, not star count.
- Four-part score (0–100): Momentum, Usage trail, Maintenance, Community. The star count does not enter the score directly.
- Momentum read from the shape of the daily star history: rise, plateau, decline and the sharpest weekly drop; six curve shapes from "Healthy" to "Spike and fade (hype suspected)".
- Small-number adjustment: values based on few stars, issues or forks are pulled toward a neutral value; curves with a peak under 5 new stars per week are flagged "few stars".
- Competitor effect: flags when a newer repository in the results took momentum from an older one.
- Desktop interface with a modern light/dark look, logo, score bars, hover help on every column and value, and a details panel with plain-language reasons.
- Four charts: score breakdown, star curves (one small chart per repository), timeline on one calendar, momentum-vs-usage map with hover; colour-blind-safe palette.
- Exports: HTML report laid out for printing to PDF, and a formatted Excel workbook (results, search settings, column guide).
- Defaults tuned for reliability: 20 candidates, minimum 50 stars.
- Uses GitHub's star history endpoint (`/stargazers/history`), introduced after GitHub restricted the stargazer list in July 2026.
- Skips "awesome" link collections; warns when GitHub returns incomplete search results.
