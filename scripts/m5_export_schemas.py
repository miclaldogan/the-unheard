# ruff: noqa: E501
"""Export the M5 narrative response schemas (generated from the Pydantic models the API actually uses).

cd server && uv run python ../scripts/m5_export_schemas.py          # rewrite docs/contracts/M5-NARRATIVE-SCHEMAS.json
cd server && uv run python ../scripts/m5_export_schemas.py --check  # exit 1 if the file is stale (also run by a test)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from unheard.api import schemas_m5 as m
from unheard.narrative import CONTRACT_VERSION

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "contracts" / "M5-NARRATIVE-SCHEMAS.json"
MODELS = [
    "StateOut",
    "CurrentOut",
    "UtteranceOut",
    "MissionOut",
    "MissionsOut",
    "TimelineOut",
    "EchoOut",
    "ModelStatusOut",
    "SettingsIn",
    "SettingsOut",
]


def build() -> str:
    schemas = {n: getattr(m, n).model_json_schema() for n in MODELS}
    return (
        json.dumps(
            {"contract_version": CONTRACT_VERSION, "schemas": schemas}, indent=1, sort_keys=True
        )
        + "\n"
    )


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text() == text else 1)
    TARGET.write_text(text)
    print("wrote", TARGET)
