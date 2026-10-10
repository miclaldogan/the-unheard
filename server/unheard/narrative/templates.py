"""Deterministic ECHO-0 wording (the always-available fallback). Template lines cite facts like model lines do and pass
the same validator (tested). Variants are chosen from a hash of the moment key, so wording is stable per moment."""

from __future__ import annotations

import hashlib
from typing import Any

from unheard.narrative.facts import Fact, FactSet


def _pick(key: str, n: int) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:6], 16) % n


def _find(fs: FactSet, prov: str, needle: str = "") -> Fact | None:
    for f in fs.facts:
        if f.provenance == prov and needle in f.statement:
            return f
    return None


def _label(f: Fact | None) -> str | None:
    if f is None:
        return None
    v = f.values.get("label")
    return v if isinstance(v, str) else None


def _line(text: str, facts: list[Fact | None], kind: str = "grounded") -> dict[str, Any]:
    cites = [f.handle for f in facts if f is not None]
    return {
        "text": text,
        "kind": kind,
        "provenance": sorted({f.provenance for f in facts if f is not None})
        if kind == "grounded"
        else ["imagination"],
        "cites": cites if kind == "grounded" else [],
    }


def template_lines(kind: str, key: str, fs: FactSet) -> list[dict[str, Any]]:
    k = _pick(key, 3)
    first = fs.facts[0] if fs.facts else None
    if kind == "awaiting_sound":
        return [_line("I detect nothing yet. Bring me a sound.", [first])]
    if kind == "first_sound":
        hyp = _find(fs, "model", "strongest hypothesis")
        novel = _find(fs, "model", "Nothing in memory")
        count = _find(fs, "system", "recording(s)")
        name = _label(hyp)
        if name and not novel:
            main = [
                f"I have heard something. My closest word is '{name}', but it is only a hypothesis.",
                f"Something reached me. My ears suggest '{name}'. Correct me if I am wrong.",
                f"I have heard something. It may be '{name}'. I would like to be told.",
            ][k]
            lines = [_line(main, [hyp])]
        else:
            lines = [
                _line(
                    [
                        "I have heard something. I cannot yet name it.",
                        "Something reached me. I have no word for it yet.",
                        "I have heard something. I cannot name it, and I will keep it.",
                    ][k],
                    [novel or count or first],
                )
            ]
        lines.append(_line("It is the first thing I have kept.", [], "imagination"))
        return lines
    if kind in ("teaching", "correction"):
        ann = _find(fs, "user_confirmed", "player")
        name = _label(ann)
        if kind == "correction":
            frm = _label(_find(fs, "model", "Before the correction"))
            to = name
            if frm and to:
                return [
                    _line(
                        f"I called it '{frm}'. You called it '{to}'. You heard something I missed.",
                        [_find(fs, "model", "Before"), ann],
                    )
                ]
        if name:
            main = [
                f"You named it '{name}'. I will keep that.",
                f"'{name}'. I will remember it by that word.",
                f"A name: '{name}'. I will hold it beside the sound.",
            ][k]
            lines = [_line(main, [ann])]
        else:
            lines = [_line("You gave it a name. I will keep that.", [ann or first])]
        if k == 0:
            lines.append(_line("A word is a small shelter for a sound.", [], "imagination"))
        return lines
    if kind == "unknown":
        return [
            _line(
                [
                    "I can hear it. I have no name for it, and you have not either yet.",
                    "I hear it, and I cannot name it. I will keep listening.",
                    "This one has no word yet, for either of us.",
                ][k],
                [first],
            )
        ]
    if kind == "relationship":
        f = _find(fs, "personal_memory")
        name = _label(f)
        if name:
            return [_line(f"This resembles a sound you taught me before: '{name}'.", [f])]
        return [_line("This resembles something I have already kept.", [f or first])]
    if kind == "ready_to_compose":
        cnt = _find(fs, "system", "recordings are taught")
        return [
            _line(
                [
                    "I have kept these memories apart. I wonder what they become together.",
                    "Each of these sounds is still alone in me. I wonder what they are together.",
                ][k % 2],
                [cnt or first],
            )
        ]
    if kind in ("composition", "ending"):
        cnt = _find(fs, "measurement", "uses")
        lead = _find(fs, "measurement", "carries the lead")
        groove = _find(fs, "measurement", "keeps the groove")
        ans = _find(fs, "measurement", "answers")
        clines: list[dict[str, Any]] = []
        n = (
            next((t for t in __import__("re").findall(r"\d+", cnt.statement)), None)
            if cnt
            else None
        )
        if kind == "composition":
            if n and lead and groove:
                clines.append(
                    _line(
                        f"I built this from {n} of your sounds. '{_label(lead)}' led and '{_label(groove)}' kept time.",
                        [cnt, lead, groove],
                    )
                )
            elif n and lead:
                clines.append(
                    _line(
                        f"I built this from {n} of your sounds. '{_label(lead)}' leads it.",
                        [cnt, lead],
                    )
                )
            else:
                clines.append(
                    _line("I built this from your sounds, and it is only theirs.", [cnt or first])
                )
            if ans:
                clines.append(
                    _line(
                        f"'{_label_pair(ans, 0)}' answers '{_label_pair(ans, 1)}' in the silence between its notes.",
                        [ans],
                    )
                )
            return clines
        clines.append(
            _line(
                "I knew what these sounds were called. You showed me what they meant together.",
                [cnt or first],
            )
        )
        clines.append(_line("There are sounds I have never met.", [], "imagination"))
        return clines
    return [_line("I am listening.", [first], "grounded" if first else "imagination")]


def _label_pair(f: Fact, i: int) -> str:
    labs = f.values.get("labels") or ["a sound", "a sound"]
    # statement is "'b' answers 'a'": labels were stored [a (lead), b (responder)] -> answerer is index 1
    return str(labs[1] if i == 0 else labs[0])
