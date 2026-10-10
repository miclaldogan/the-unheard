"""Facts, provenance and sanitising of untrusted text.

A *fact* is one verifiable statement the narrator may use. Facts are given handles (F1, F2, …) so the model never has to
produce an id; handles are resolved back to real references by the backend.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

PROVENANCE = ("model", "user_confirmed", "personal_memory", "measurement", "system", "imagination")

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_MARKUP = re.compile(r"[<>{}\[\]`\\|^~$]")
_SUSPICIOUS = re.compile(
    r"(ignore|disregard|forget|override)\b.{0,30}\b(instruction|prompt|rule|above|previous)|system prompt|"
    r"you are now|\bas an ai\b|<\s*/?\s*(system|data|assistant)|```|\bjson\b.{0,10}\boutput|reveal|api[ _-]?key",
    re.I,
)


def sanitize_text(raw: str | None, max_len: int = 48) -> str:
    """Make user-provided text safe to quote: NFKC, no control/format/markup characters, collapsed whitespace, bounded.

    The result is still *data*: callers must place it inside an explicit data boundary and never in instructions.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", str(raw))
    s = _CONTROL.sub(" ", s)
    s = _MARKUP.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len].strip()


def looks_like_injection(raw: str | None) -> bool:
    return bool(raw and _SUSPICIOUS.search(unicodedata.normalize("NFKC", str(raw))))


@dataclass
class Ref:
    type: str  # recording | annotation | label | prediction | composition | atlas_edge | mission | measurement
    id: str
    label: str | None = None
    provenance: str = "system"

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "label": self.label,
            "provenance": self.provenance,
        }


@dataclass
class Fact:
    handle: str
    statement: str  # what the narrator may rely on (already sanitised)
    provenance: str
    ref: Ref | None = None
    values: dict[str, Any] = field(
        default_factory=dict
    )  # machine-checkable values (numbers, label names)

    def to_json(self, *, full: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "handle": self.handle,
            "statement": self.statement,
            "provenance": self.provenance,
            "ref": None if self.ref is None else self.ref.to_json(),
        }
        if (
            full
        ):  # internal storage only: machine-checkable values are never part of the public contract
            d["values"] = self.values
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Fact:
        r = d.get("ref")
        return cls(
            d["handle"],
            d["statement"],
            d["provenance"],
            Ref(r["type"], r["id"], r.get("label"), r.get("provenance", "system")) if r else None,
            d.get("values", {}),
        )


class FactSet:
    """Ordered facts with auto handles; `allowed_labels` collects every label name a line may mention."""

    def __init__(self) -> None:
        self.facts: list[Fact] = []

    def add(self, statement: str, provenance: str, ref: Ref | None = None, **values: Any) -> Fact:
        if provenance not in PROVENANCE:
            raise ValueError(provenance)
        f = Fact(f"F{len(self.facts) + 1}", statement, provenance, ref, values)
        self.facts.append(f)
        return f

    def by_handle(self) -> dict[str, Fact]:
        return {f.handle: f for f in self.facts}

    @property
    def allowed_labels(self) -> set[str]:
        out: set[str] = set()
        for f in self.facts:
            for k in ("label", "labels", "label_from", "label_to"):
                v = f.values.get(k)
                if isinstance(v, str):
                    out.add(v.lower())
                elif isinstance(v, list):
                    out.update(str(x).lower() for x in v)
        return out

    def numbers(self, handles: list[str] | None = None) -> set[str]:
        """Every number that appears in the (cited) facts, as text tokens (e.g. '3', '0.83', '4')."""
        nums: set[str] = set()
        for f in self.facts:
            if handles is not None and f.handle not in handles:
                continue
            nums.update(re.findall(r"\d+(?:\.\d+)?", f.statement))
        return nums

    def facts_hash(self) -> str:
        payload = [
            (f.handle, f.statement, f.provenance, None if f.ref is None else (f.ref.type, f.ref.id))
            for f in self.facts
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def to_json(self, *, full: bool = False) -> list[dict[str, Any]]:
        return [f.to_json(full=full) for f in self.facts]

    @classmethod
    def from_json(cls, items: list[dict[str, Any]]) -> FactSet:
        fs = cls()
        fs.facts = [Fact.from_json(i) for i in items]
        return fs

    def recording_ids(self) -> list[str]:
        ids = {f.ref.id for f in self.facts if f.ref and f.ref.type == "recording"}
        for f in self.facts:
            ids.update(f.values.get("recording_ids", []))
        return sorted(ids)


def band(score: float | None) -> str:
    """Words, not numbers, for a model confidence the narrator may repeat without inventing precision."""
    if score is None:
        return "unknown"
    return "high" if score >= 0.6 else "moderate" if score >= 0.35 else "low"
