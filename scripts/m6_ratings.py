# ruff: noqa: E501
"""M6: human-rating sheets and honest summaries. Never invents a rating.

    python scripts/m6_ratings.py gemma-sheet      # eval/m5/human_rating.csv  ->  eval/m6/gemma_human_rating.csv (6 criteria)
    python scripts/m6_ratings.py gemma-summary    # reads the filled sheet; prints means per condition, or PENDING
    python scripts/m6_ratings.py listening-summary path/to/unheard-listening-ratings.csv

Gemma sheet: each row is one game moment with the facts the narrator was given and two anonymous options (the deterministic
template and a validated Gemma line, in shuffled order; the key is in the last column, read it only after rating).
Rate each option 1-5 on: factual (says nothing the facts do not support), grounding (stays on what actually happened),
character (curious, precise, uncertain, never cheerful), creativity, relevance (fits the current game state), readability.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "eval" / "m5" / "human_rating.csv"
OUT = ROOT / "eval" / "m6" / "gemma_human_rating.csv"
CRIT = ["factual", "grounding", "character", "creativity", "relevance", "readability"]
MIN_ROWS = 10  # below this the summary says so instead of implying a result


def make_sheet() -> None:
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    key_col = next(k for k in rows[0] if k.startswith("_key"))
    head = ["moment_step", "facts", "option_1", "option_2"]
    head += [f"{c}_{i}" for i in (1, 2) for c in CRIT] + [
        "preferred (1/2/tie)",
        "notes",
        "_key (do not look): option_1 is",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in rows:
            w.writerow(
                [r["moment_step"], r["facts"], r["option_1"], r["option_2"]]
                + [""] * (2 * len(CRIT))
                + ["", "", r[key_col]]
            )
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rows)} moments, nothing pre-filled)")


def _num(x: str) -> int | None:
    x = (x or "").strip()
    return int(x) if x.isdigit() and 1 <= int(x) <= 5 else None


def gemma_summary() -> None:
    if not OUT.exists():
        print("PENDING: no sheet; run `gemma-sheet` first")
        return
    rows = list(csv.DictReader(OUT.open(encoding="utf-8")))
    key_col = next(k for k in rows[0] if k.startswith("_key"))
    scores: dict[str, dict[str, list[int]]] = {
        "template": defaultdict(list),
        "gemma": defaultdict(list),
    }
    pref = {"template": 0, "gemma": 0, "tie": 0}
    rated = 0
    for r in rows:
        first = r[key_col].strip()  # which condition option_1 is
        second = "gemma" if first == "template" else "template"
        got = False
        for i, cond in ((1, first), (2, second)):
            for c in CRIT:
                v = _num(r[f"{c}_{i}"])
                if v is not None:
                    scores[cond][c].append(v)
                    got = True
        rated += got
        p = r["preferred (1/2/tie)"].strip().lower()
        if p == "1":
            pref[first] += 1
        elif p == "2":
            pref[second] += 1
        elif p == "tie":
            pref["tie"] += 1
    if rated == 0:
        print(
            "PENDING: the sheet has no ratings. No claim about Gemma vs template quality can be made."
        )
        return
    print(
        f"{rated} rated moments of {len(rows)}"
        + ("  (too few for any conclusion)" if rated < MIN_ROWS else "")
    )
    print(f"{'criterion':12s} {'template':>9s} {'gemma':>9s}")
    for c in CRIT:
        t, g = scores["template"][c], scores["gemma"][c]
        print(
            f"{c:12s} {mean(t) if t else float('nan'):9.2f} {mean(g) if g else float('nan'):9.2f}   (n={len(t)}/{len(g)})"
        )
    print(
        "preferred:",
        pref,
        "- small, single-rater samples are anecdotes, not evidence of improvement",
    )


def listening_summary(path: str) -> None:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    by: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in rows:
        v = _num(r["score"])
        if v is not None:
            by[(r["mode_key"], r["criterion"])].append(v)
    if not by:
        print("PENDING: no scores in this file")
        return
    modes = ["legacy", "organic", "composed"]
    crit = sorted({c for _, c in by})
    print(f"{'criterion':16s}" + "".join(f"{m:>10s}" for m in modes))
    for c in crit:
        print(
            f"{c:16s}"
            + "".join(f"{mean(by[(m, c)]) if by[(m, c)] else float('nan'):10.2f}" for m in modes)
        )
    print("n per cell:", {k: len(v) for k, v in sorted(by.items())})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "gemma-sheet":
        make_sheet()
    elif cmd == "gemma-summary":
        gemma_summary()
    elif cmd == "listening-summary" and len(sys.argv) > 2:
        listening_summary(sys.argv[2])
    else:
        print(__doc__)
