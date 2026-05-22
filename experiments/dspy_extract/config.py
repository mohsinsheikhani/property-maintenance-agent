"""Step 1: point DSPy at a model.

Defaults to gpt-4o-mini to match the live node, so the baseline matches prod.
Override with EXTRACT_LM to try another model without a code edit, e.g.:

    EXTRACT_LM=gemini/gemini-2.0-flash uv run python -m experiments.dspy_extract.baseline

dspy.LM goes through litellm, which reads the provider key from the environment
(GEMINI_API_KEY, OPENAI_API_KEY); we load .env explicitly.
"""

import os
from pathlib import Path

import dspy
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL = "openai/gpt-4o-mini"


def configure_lm() -> dspy.LM:
    load_dotenv(_REPO_ROOT / ".env")
    lm = dspy.LM(os.getenv("EXTRACT_LM", _DEFAULT_MODEL), temperature=0)
    # JSONAdapter parses the response as one JSON object, so Optional fields decode
    # to real None / unquoted strings. The default ChatAdapter left union-typed
    # values as literal JSON ('"13A"', the string 'null'), which broke unit_number
    # and callback_phone, a real parse bug not just a metric artifact.
    dspy.configure(lm=lm, adapter=dspy.JSONAdapter())
    return lm
