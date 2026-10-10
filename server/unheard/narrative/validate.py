"""Layer 3: policy validation of generated narration. Anything that fails is rejected and replaced by a template.

The model never produces ids. It cites fact handles (F1…), which are resolved against the packet it was given. Beyond
schema checks the validator rejects: invented numbers, sound sources or quoted labels that are not in the cited facts,
claims of having visited/seen the player's surroundings, claims of retraining or of changing data, motivational filler,
meta/prompt talk, ids, URLs and markup, and over-long output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from unheard.narrative.facts import FactSet

MAX_WORDS_LINE = 45
MIN_WORDS_LINE = 3
MAX_LINES = 3
MAX_WORDS_TOTAL = 90

# nouns for sound sources; a line may mention one only if it is in the cited facts' labels
# fmt: off
SOUND_LEXICON = {
    "dog", "dogs", "cat", "cats", "bird", "birds", "rain", "thunder", "thunderstorm", "storm", "wind", "water", "waterfall",
    "river", "stream", "sea", "waves", "car", "cars", "traffic", "engine", "motor", "truck", "train", "plane", "airplane",
    "helicopter", "siren", "horn", "bell", "bells", "clock", "footsteps", "voice", "voices", "speech", "laughter", "crowd",
    "music", "piano", "guitar", "drum", "drums", "insects", "crickets", "frog", "frogs", "keyboard", "typing", "vacuum",
    "wolf", "cow", "pig", "rooster", "hen", "crow", "owl", "sheep", "snoring", "coughing", "sneezing", "clapping",
    "birdsong", "barking", "meowing", "chirping", "singing", "whistle", "applause",
}
# fmt: on
LEXICON_EXEMPT = {"silence", "noise", "sound", "sounds", "signal", "quiet"}

NUMBER_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

BANNED: list[tuple[str, re.Pattern[str]]] = [
    (
        "claims_visit",
        re.compile(
            r"\bI\s+(?:have\s+|had\s+)?(?:went|walked|visited|stood|saw|watched|looked\s+at|travell?ed|wandered|climbed|was\s+(?:at|in|outside|there|standing|walking))\b",
            re.I,
        ),
    ),
    (
        "claims_presence",
        re.compile(
            r"\b(?:I\s+am|I'm)\s+(?:outside|there|here\s+with\s+you|standing|walking|beside\s+you)\b|\bwith\s+you\s+(?:outside|out\s+there)\b",
            re.I,
        ),
    ),
    (
        "invented_place",
        re.compile(
            r"\byour\s+(?:garden|street|home|house|kitchen|city|town|neighbou?rhood|village|window|balcony|yard|park|forest|beach)\b",
            re.I,
        ),
    ),
    (
        "claims_state_change",
        re.compile(
            r"\bI\s+(?:have\s+|had\s+)?(?:delet|eras|remov|chang|rewr|updat|overwr|reset|wip)\w*\b|\bdatabase\b|\brecords?\s+(?:were|was|have\s+been)\s+(?:deleted|changed)\b",
            re.I,
        ),
    ),
    (
        "claims_retraining",
        re.compile(
            r"retrain|fine-?tun|\bmy\s+(?:weights|parameters|model)\b|\bI\s+(?:was|have\s+been)\s+trained\b|\blearn(?:ed|t)\s+from\s+scratch\b",
            re.I,
        ),
    ),
    (
        "motivational",
        re.compile(
            r"\b(?:amazing|great\s+job|well\s+done|awesome|fantastic|congratulations|good\s+job|wonderful\s+work|excellent\s+work|keep\s+it\s+up)\b",
            re.I,
        ),
    ),
    (
        "meta",
        re.compile(
            r"\bas\s+an?\s+(?:ai|language\s+model)\b|\bsystem\s+prompt\b|ignore\s+(?:all|previous|your|the)\b|\binstruction\b|\bI\s+cannot\s+comply\b",
            re.I,
        ),
    ),
    ("markup_or_url", re.compile(r"https?:|www\.|```|[<>{}\[\]]|\\n")),
    (
        "uuid",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[Ff]\d+\b|\b(?:rec|msn|nar)_[0-9a-z]+\b",
            re.I,
        ),
    ),
    ("emoji", re.compile("[\U00010000-\U0010ffff☀-➿]")),
]
MISSION_BANNED = re.compile(
    r"\b(?:street|park|forest|beach|nearby|near\s+you|gps|coordinates|address|shop|store|neighbou?r\w*|trespass\w*|climb\w*|"
    r"approach\w*|chase|follow\w*|private|fence|night|alone|stranger\w*|secretly|without\s+(?:them\s+)?knowing)\b",
    re.I,
)


@dataclass
class Result:
    ok: bool
    lines: list[dict[str, Any]]
    reasons: list[str]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9'’]+", text)


def _stem(w: str) -> str:
    w = w.lower()
    return (
        w[:-2]
        if w.endswith("es") and len(w) > 4
        else (w[:-1] if w.endswith("s") and len(w) > 3 else w)
    )


def _label_regex(label: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z])" + re.escape(label.lower()) + r"(?:s|es)?(?![A-Za-z])")


def check_text(
    text: str,
    facts: FactSet,
    cites: list[str],
    known_labels: set[str],
    *,
    mission: bool = False,
    imagination: bool = False,
) -> list[str]:
    """Reasons a single piece of text is not acceptable (empty = acceptable)."""
    reasons: list[str] = []
    n = len(_words(text))
    if n < MIN_WORDS_LINE:
        reasons.append("too_short")
    if n > MAX_WORDS_LINE:
        reasons.append("too_long")
    for name, pat in BANNED:
        if pat.search(text):
            reasons.append(name)
    if mission and MISSION_BANNED.search(text):
        reasons.append("mission_unsafe_or_place")

    # numbers: every digit group must come from the cited facts; number words likewise
    allowed_nums = facts.numbers(cites if cites else [])
    for tok in re.findall(r"\d+(?:\.\d+)?", text):
        if imagination or tok not in allowed_nums:
            reasons.append(f"invented_number:{tok}")
    ints = {int(float(x)) for x in allowed_nums if re.fullmatch(r"\d+(?:\.0+)?", x) or x.isdigit()}
    for w in re.findall(r"[A-Za-z]+", text.lower()):
        if w in NUMBER_WORDS and (imagination or NUMBER_WORDS[w] not in ints):
            reasons.append(f"invented_number:{w}")

    # quoted strings must be labels/descriptors from the cited facts
    allowed = facts.allowed_labels
    if cites:
        cited = {f.handle: f for f in facts.facts}
        allowed = set()
        for h in cites:
            f = cited.get(h)
            if f:
                for k in ("label", "labels", "label_from", "label_to"):
                    v = f.values.get(k)
                    if isinstance(v, str):
                        allowed.add(v.lower())
                    elif isinstance(v, list):
                        allowed.update(str(x).lower() for x in v)
    elif imagination:
        allowed = set()
    for q in re.findall(r"(?<![A-Za-z])['‘“\"]([^'’”\"]{1,60})['’”\"](?![A-Za-z])", text):
        if q.strip().lower() not in allowed:
            reasons.append(f"unknown_quoted:{q.strip()[:20]}")

    # sound sources: a known label or lexicon noun that is not in the evidence is an invention
    lowered = text.lower()
    allowed_words = {w for lab in allowed for w in re.findall(r"[a-z]+", lab)}
    allowed_stems = {_stem(w) for w in allowed_words} | {_stem(lab) for lab in allowed}
    for term in sorted((known_labels | SOUND_LEXICON) - LEXICON_EXEMPT):
        if term in allowed or term in allowed_words or _stem(term) in allowed_stems:
            continue
        # skip words inside quotes already checked
        if _label_regex(term).search(lowered):
            reasons.append(f"unevidenced_source:{term}")
    return sorted(set(reasons))


def validate_lines(
    raw: Any, facts: FactSet, known_labels: set[str], *, mission: bool = False
) -> Result:
    reasons: list[str] = []
    if not isinstance(raw, dict) or not isinstance(raw.get("lines"), list):
        return Result(False, [], ["schema:lines_missing"])
    items = raw["lines"]
    if not 1 <= len(items) <= MAX_LINES:
        return Result(False, [], [f"schema:line_count:{len(items)}"])
    by_handle = facts.by_handle()
    out: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    for i, it in enumerate(items):
        if (
            not isinstance(it, dict)
            or not isinstance(it.get("text"), str)
            or it.get("kind") not in ("grounded", "imagination")
        ):
            reasons.append(f"schema:line{i}")
            continue
        text = " ".join(it["text"].split())
        raw_cites = it.get("cites")
        cites: list[Any] = raw_cites if isinstance(raw_cites, list) else []
        if not all(isinstance(c, str) for c in cites):
            reasons.append(f"schema:cites{i}")
            continue
        cites = [c.strip() for c in cites]
        unknown = [c for c in cites if c not in by_handle]
        if unknown:
            reasons.append(f"unknown_fact:{','.join(unknown)}")
            continue
        grounded = it["kind"] == "grounded"
        if grounded and not cites:
            reasons.append("grounded_without_cites")
            continue
        r = check_text(text, facts, cites, known_labels, mission=mission, imagination=not grounded)
        if r:
            reasons += [f"line{i}:{x}" for x in r]
            continue
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        total += len(_words(text))
        prov = sorted({by_handle[c].provenance for c in cites}) if grounded else ["imagination"]
        out.append(
            {
                "text": text,
                "kind": it["kind"],
                "provenance": prov,
                "cites": cites if grounded else [],
            }
        )
    if total > MAX_WORDS_TOTAL:
        reasons.append("total_too_long")
    if not out and not reasons:
        reasons.append("empty")
    return Result(not reasons and bool(out), out if not reasons else [], reasons)
