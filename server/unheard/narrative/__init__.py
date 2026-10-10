"""ECHO-0's narrative layer (M5).

Three layers, strictly separated:
1. ``state``/``moments``/``missions`` derive authoritative game state from the existing database (deterministic).
2. ``gemma`` receives a minimal, labelled fact packet and may only write words (or choose among backend mission
   candidates). It never sees or produces ids.
3. ``validate`` checks every generated line against the facts; anything that fails falls back to ``templates``.
"""

CONTRACT_VERSION = "m5.1"
