"""The contract document and the code must agree: examples in docs/contracts/M5-NARRATIVE-API.md validate against the real
response models, and the exported JSON Schema file is generated from them."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from unheard.api import schemas_m5 as m

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "contracts" / "M5-NARRATIVE-API.md").read_text()


def json_blocks() -> list[dict]:  # type: ignore[type-arg]
    out = []
    for raw in re.findall(r"```json\n(.*?)```", DOC, flags=re.S):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return out


def find(pred) -> dict:  # type: ignore[no-untyped-def, type-arg]
    return next(b for b in json_blocks() if pred(b))


def test_utterance_example_validates() -> None:
    m.UtteranceOut.model_validate(find(lambda b: "moment" in b and "lines" in b))


def test_mission_example_validates() -> None:
    mission = find(lambda b: "objective" in b and "safe_fallback" in b)
    m.MissionOut.model_validate(mission)
    assert mission["type"] in m.MissionOut.model_fields["type"].annotation.__args__  # type: ignore[union-attr]


def test_state_example_validates() -> None:
    m.StateOut.model_validate(find(lambda b: "acts" in b and "milestones" in b))


def test_model_status_example_validates() -> None:
    m.ModelStatusOut.model_validate(find(lambda b: "limits" in b and "stats" in b))


def test_every_documented_endpoint_exists_in_the_app() -> None:
    from unheard.app import create_app

    spec = create_app().openapi()["paths"]
    paths = {(meth.upper(), p) for p, ops in spec.items() for meth in ops}
    found = re.findall(r"^### 4\.\d `(GET|POST|PATCH) (/api/narrative[^`\[\s]*)", DOC, flags=re.M)
    assert len(found) >= 9
    for meth, path in found:
        norm = re.sub(r"\{[^}]+\}", "{}", path)
        assert any(me == meth and re.sub(r"\{[^}]+\}", "{}", pp) == norm for me, pp in paths), (
            meth,
            path,
        )


def test_exported_schema_file_is_in_sync() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "m5_export_schemas.py"), "--check"],
        capture_output=True,
    )
    assert r.returncode == 0, "run `cd server && uv run python ../scripts/m5_export_schemas.py`"


def test_contract_version_is_stamped_everywhere() -> None:
    assert '"contract_version": "m5.1"' in DOC
    from unheard.narrative import CONTRACT_VERSION

    assert CONTRACT_VERSION == "m5.1"


@pytest.mark.parametrize("word", ["retrained", "fine-tuned"])
def test_contract_forbids_retraining_claims_in_ui_copy(word: str) -> None:
    assert re.search(rf"not.*{word}|Do not word the UI as.*{word}", DOC, flags=re.S | re.I)
