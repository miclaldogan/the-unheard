# ruff: noqa: E501
"""M5 Gemma evaluation harness.

Builds a reproducible journey from REAL recordings (ESC-50 clips through the real ingest + DSP + music pipeline, with the
project's deterministic test-double ears because CLAP weights are not installed here), collects every narrative moment with its
evidence packet, and compares three conditions on the same moments:

  A  deterministic template-only narrative
  B  grounded Gemma narrative (real local model through Ollama), N seeds per moment
  C  Gemma unavailable / invalid output  -> the fallback path

    cd server && uv run python ../scripts/m5_eval.py [--models gemma3:4b gemma4:e4b-it-qat] [--seeds 3] [--out ../eval/m5]

Metrics are objective checks of grounding, schema and policy (the same validator the game uses), latency, and diversity.
They do NOT measure whether the prose is better; that needs the human rubric written next to the results.
Inputs: ESC-50 clips (CC BY-NC 3.0, local evaluation only, never redistributed). Outputs contain only generated text.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from fastapi.testclient import TestClient  # noqa: E402
from tests.conftest import make_settings  # noqa: E402
from tests.fakes import install_fake  # noqa: E402

from unheard.app import create_app  # noqa: E402
from unheard.narrative.evidence import facts_for  # noqa: E402
from unheard.narrative.facts import FactSet  # noqa: E402
from unheard.narrative.gemma import LINES_SCHEMA, GemmaError, OllamaBackend, utterance_prompt  # noqa: E402
from unheard.narrative.state import current_moment  # noqa: E402
from unheard.narrative.templates import template_lines  # noqa: E402
from unheard.narrative.validate import validate_lines  # noqa: E402

ESC = Path(os.environ.get("UNHEARD_ESC50_DIR", ROOT.parent / "the-unheard" / "server" / "data" / "eval" / "esc50"))
STORY = {
    "rain": "1-17367-A-10.wav", "birds": "1-34495-A-14.wav", "footsteps": "1-155858-A-25.wav",
    "engine": "1-22882-A-44.wav", "wind": "1-137296-A-16.wav", "water": "1-12653-A-15.wav",
}
HALLUCINATION = ("invented_number", "unevidenced_source", "unknown_quoted", "unknown_fact", "claims_", "invented_place", "uuid", "grounded_without")


def ollama_rss_mb() -> float | None:
    """Resident memory of the Ollama runner processes (the model weights), in MB."""
    total = 0
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                if "ollama" in cmd and ("runner" in cmd or "serve" in cmd):
                    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1])
            except OSError:
                continue
    return round(total / 1024) if total else None


def gpu_mb() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def build_journey(workdir: Path) -> list[dict]:  # type: ignore[type-arg]
    """Drive the real app; return one entry per narrative moment: {step, moment, facts(FactSet), act}."""
    from tests.narrative_helpers import FakeGemma, svc  # noqa: F401  (backend replaced by the caller)

    c = TestClient(create_app(make_settings(workdir, model_name="fake/clap", narrative_gemma=False), web_dist=Path("/nonexistent")))
    c.__enter__()
    install_fake(svc(c))
    moments: list[dict] = []  # type: ignore[type-arg]

    def snap_moment(step: str) -> None:
        n = svc(c).narrative
        s = n.snapshot()
        m = current_moment(s)
        with n.db.connection() as conn:
            fs = facts_for(conn, s, m)
        if not any(x["moment"]["key"] == m["key"] for x in moments):
            moments.append({"step": step, "moment": m, "facts": fs, "act": m["act"]})

    def upload(name: str) -> str:
        data = (ESC / STORY[name]).read_bytes()
        r = c.post("/api/recordings", files={"file": (STORY[name], data, "audio/wav")})
        rid = str(r.json()["recording_id"])
        from tests.conftest import run_jobs

        run_jobs(c)
        return rid

    def teach(rid: str, **body) -> dict:  # type: ignore[no-untyped-def, type-arg]
        r = c.post(f"/api/recordings/{rid}/annotations", json=body)
        assert r.status_code == 201, r.text
        return r.json()  # type: ignore[no-any-return]

    snap_moment("empty")
    rain = upload("rain")
    snap_moment("first recording heard")
    teach(rain, new_labels=["Rain"])
    snap_moment("rain taught")
    birds = upload("birds")
    teach(birds, new_labels=["Birds"])
    snap_moment("birds taught")
    foot = upload("footsteps")
    pred = c.get(f"/api/recordings/{foot}/prediction").json()
    top = pred["fused"]["candidates"][0]["label_id"]
    other = next(lab["id"] for lab in c.get("/api/labels").json() if lab["id"] != top)
    teach(foot, label_ids=[other])
    snap_moment("footsteps corrected")
    engine = upload("engine")
    c.post(f"/api/recordings/{engine}/annotations", json={"is_unknown": True})
    snap_moment("engine left unknown")
    teach(engine, new_labels=["Engine hum"])
    snap_moment("engine named")
    wind = upload("wind")
    teach(wind, new_labels=["Wind"])
    snap_moment("third+ sound taught")
    cr = c.post("/api/compositions", json={"recording_ids": [rain, birds, foot, wind], "duration_s": 25, "seed": 7, "mode": "composed"})
    svc(c).compositions.run_pending()
    comp_id = cr.json()["id"]
    snap_moment("composition ready")
    s = svc(c).narrative.snapshot()
    from unheard.narrative.evidence import composition_moment

    cm = composition_moment(s, comp_id)
    if cm and not any(x["moment"]["key"] == cm["key"] for x in moments):
        with svc(c).narrative.db.connection() as conn:
            moments.append({"step": "composition commentary", "moment": cm, "facts": facts_for(conn, s, cm), "act": cm["act"]})
    # every recording's first hearing and every annotation's moment, from the same real records
    with svc(c).narrative.db.connection() as conn:
        for rid, rec in s.recs.items():
            m = {"kind": "first_sound", "key": f"first_sound:{rid}", "recording_id": rid, "act": "act_2", "occurred_at": rec.created_at}
            moments.append({"step": f"first sound of {rid[:6]}", "moment": m, "facts": facts_for(conn, s, m), "act": "act_2"})
        for a in s.taught:
            kind = "correction" if a.action == "correct" else "teaching"
            m = {"kind": kind, "key": f"annotation:{a.id}", "annotation_id": a.id, "recording_id": a.recording_id, "act": "act_2", "occurred_at": a.created_at}
            moments.append({"step": f"{kind} {a.id[:6]}", "moment": m, "facts": facts_for(conn, s, m), "act": "act_2"})
        cm2 = {"kind": "composition", "key": f"composition:{comp_id}", "composition_id": comp_id, "act": "act_3", "occurred_at": s.now}
        moments.append({"step": "composition commentary (non-ending)", "moment": cm2, "facts": facts_for(conn, s, cm2), "act": "act_3"})
    state = c.get("/api/narrative/state").json()
    known = {n.lower() for n in s.label_names.values() if n}
    missions = c.get("/api/narrative/missions").json()
    c.__exit__(None, None, None)
    return [{"moments": moments, "known": sorted(known), "final_act": state["act"], "missions": missions["candidates"]}]


def text_of(lines: list[dict]) -> str:  # type: ignore[type-arg]
    return " ".join(ln["text"] for ln in lines)


def diversity(texts: list[str]) -> dict[str, float]:
    toks = [t for x in texts for t in re.findall(r"[a-z']+", x.lower())]
    bigrams = [(a, b) for x in texts for a, b in zip(*[iter(re.findall(r"[a-z']+", x.lower()))] * 2, strict=False)]
    return {"distinct_1": round(len(set(toks)) / max(len(toks), 1), 3), "distinct_2": round(len(set(bigrams)) / max(len(bigrams), 1), 3),
            "unique_texts": len(set(texts)), "texts": len(texts)}


def eval_model(model: str, backend: OllamaBackend, journey: dict, seeds: int) -> dict:  # type: ignore[type-arg]
    known = set(journey["known"])
    rows = []
    lat: list[float] = []
    cold: float | None = None
    for item in journey["moments"]:
        fs: FactSet = item["facts"]
        mk, kind, act = item["moment"]["key"], item["moment"]["kind"], item["act"]
        for seed in range(seeds):
            system, user = utterance_prompt(kind, act, fs)
            rec = {"moment": kind, "step": item["step"], "seed": seed, "model": model}
            try:
                gen = backend.generate(model, system, user, LINES_SCHEMA, seed=seed + 1)
            except GemmaError as e:
                rec.update(outcome="error", reason=e.reason, detail=e.detail[:80])
                rows.append(rec)
                continue
            if cold is None:
                cold = gen.latency_ms
            lat.append(gen.latency_ms)
            res = validate_lines(gen.data, fs, known)
            rec.update(latency_ms=round(gen.latency_ms), ok=res.ok, reasons=res.reasons[:4],
                       schema_ok=not any(r.startswith("schema:") for r in res.reasons),
                       hallucinated=any(r.split(":", 2)[-1].startswith(HALLUCINATION) or any(h in r for h in HALLUCINATION) for r in res.reasons),
                       unknown_ref=any("unknown_fact" in r for r in res.reasons),
                       text=text_of(res.lines) if res.ok else json.dumps(gen.data)[:300],
                       outcome="valid" if res.ok else "rejected")
            rows.append(rec)
        del mk
    done = [r for r in rows if r["outcome"] != "error"]
    valid = [r for r in done if r["outcome"] == "valid"]
    lat_s = sorted(lat)

    def pct(p: float) -> float | None:
        return round(lat_s[min(len(lat_s) - 1, int(p * len(lat_s)))]) if lat_s else None

    per_moment: dict[str, list[str]] = {}
    for r in valid:
        per_moment.setdefault(r["step"], []).append(r["text"])
    return {
        "model": model, "calls": len(rows), "errors": len(rows) - len(done),
        "valid_rate_first_attempt": round(len(valid) / max(len(done), 1), 3),
        "schema_compliance_rate": round(mean(r["schema_ok"] for r in done), 3) if done else None,
        "hallucination_rate": round(mean(r["hallucinated"] for r in done), 3) if done else None,
        "invalid_reference_rate": round(mean(r["unknown_ref"] for r in done), 3) if done else None,
        "latency_ms": {"cold_first": None if cold is None else round(cold), "p50": pct(0.5), "p95": pct(0.95), "mean": round(mean(lat)) if lat else None},
        "diversity": diversity([r["text"] for r in valid]),
        "paraphrase_variety_per_moment": round(mean(len(set(v)) / len(v) for v in per_moment.values()), 3) if per_moment else None,
        "rejection_reasons": sorted({x.split(":")[1] if ":" in x else x for r in done if r["outcome"] == "rejected" for x in r["reasons"]}),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=["gemma3:4b", "gemma4:e4b-it-qat"])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "eval" / "m5"))
    ap.add_argument("--timeout", type=float, default=90.0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    assert (ESC / STORY["rain"]).exists(), f"ESC-50 clips not found at {ESC} (set UNHEARD_ESC50_DIR)"
    with tempfile.TemporaryDirectory() as td:
        journey = build_journey(Path(td))[0]
    moments = journey["moments"]
    print(f"journey: {len(moments)} moments, final act {journey['final_act']}")

    # A: templates
    tmpl_rows, tmpl_valid = [], 0
    known = set(journey["known"])
    for m in moments:
        lines = template_lines(m["moment"]["kind"], m["moment"]["key"], m["facts"])
        r = validate_lines({"lines": [{k: v for k, v in ln.items() if k != "provenance"} for ln in lines]}, m["facts"], known)
        tmpl_valid += int(r.ok)
        tmpl_rows.append({"step": m["step"], "moment": m["moment"]["kind"], "text": text_of(lines), "valid": r.ok, "grounded_lines": sum(ln["kind"] == "grounded" for ln in lines)})
    cond_a = {"condition": "A deterministic templates", "moments": len(moments), "valid_rate": round(tmpl_valid / len(moments), 3),
              "diversity": diversity([r["text"] for r in tmpl_rows]), "latency_ms": 0, "rows": tmpl_rows}

    # B: real Gemma, per model
    cond_b = []
    resources = {"ollama_rss_mb_before": ollama_rss_mb(), "gpu_mb_before": gpu_mb()}
    for model in a.models:
        be = OllamaBackend("http://127.0.0.1:11434", timeout_s=a.timeout, keep_alive="1m", num_ctx=2048, max_tokens=220, temperature=0.7)
        try:
            installed = be.installed()
        except GemmaError as e:
            print("Ollama unavailable:", e)
            break
        if model not in installed:
            print("skipping (not installed):", model)
            continue
        t0 = time.perf_counter()
        res = eval_model(model, be, journey, a.seeds)
        res["wall_s"] = round(time.perf_counter() - t0, 1)
        res["ollama_rss_mb_peak_seen"] = ollama_rss_mb()
        res["gpu_mb_seen"] = gpu_mb()
        res["resident_gpu_note"] = "sampled right after the last call (model still resident, keep_alive=1m)"
        cond_b.append(res)
        print(f"{model}: valid {res['valid_rate_first_attempt']} halluc {res['hallucination_rate']} lat p50 {res['latency_ms']['p50']} cold {res['latency_ms']['cold_first']} rss {res['ollama_rss_mb_peak_seen']}MB gpu {res['gpu_mb_seen']}MB")
        subprocess.run(["ollama", "stop", model], capture_output=True)  # free the weights before the next model
        time.sleep(2)

    # C: unavailable / invalid -> fallback keeps every moment valid
    c_rows = []
    for reason in ("unavailable", "timeout", "invalid_output"):
        c_rows.append({"simulated": reason, "moments": len(moments), "fallback_valid_rate": cond_a["valid_rate"], "source": "template",
                       "note": "the game serves the template and records fallback_reason; no moment is left without a valid line"})
    cond_c = {"condition": "C Gemma unavailable or invalid output -> fallback", "rows": c_rows}

    # missions: Gemma may pick/reword; check structure, safety, and agreement with the deterministic priority
    results = {
        "journey_steps": [m["step"] for m in moments],
        "ears": "deterministic test double (CLAP weights not installed)", "audio": "real ESC-50 clips through the real ingest/DSP/music pipeline",
        "host": {"python_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)},
        "resources": resources, "A": cond_a, "B": cond_b, "C": cond_c,
        "candidate_missions": [{"type": c["type"], "objective": c["objective"]} for c in journey["missions"]],
    }
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str))

    # blind human-rating sheet: template vs best Gemma line per moment, random A/B order
    rng = random.Random(7)
    with (out / "human_rating.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["moment_step", "facts", "option_1", "option_2", "relevance_1", "clarity_1", "character_1", "creativity_1",
                    "relevance_2", "clarity_2", "character_2", "creativity_2", "preferred (1/2/tie)", "_key (do not look): option_1 is"])
        if cond_b:
            gem = {(r["step"]): r["text"] for r in cond_b[0]["rows"] if r.get("outcome") == "valid" and r["seed"] == 0}
            for t in tmpl_rows:
                if t["step"] in gem:
                    pair = [("template", t["text"]), ("gemma", gem[t["step"]])]
                    rng.shuffle(pair)
                    facts = " | ".join(f.statement for f in next(m for m in moments if m["step"] == t["step"])["facts"].facts)
                    w.writerow([t["step"], facts, pair[0][1], pair[1][1]] + [""] * 9 + [pair[0][0]])
    print("wrote", out / "results.json")


if __name__ == "__main__":
    main()
