"""Step 1: point DSPy at a model (classify experiment).

Same setup as the extract experiment. Defaults to gpt-4o-mini so the baseline
matches the live classify node, JSONAdapter so closed-set fields decode cleanly.
Override the model without a code edit:

    CLASSIFY_LM=gemini/gemini-2.0-flash uv run python -m experiments.dspy_classify.baseline
"""

import os
from pathlib import Path

import dspy
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL = "openai/gpt-4o-mini"


def configure_lm() -> dspy.LM:
    load_dotenv(_REPO_ROOT / ".env")
    lm = dspy.LM(os.getenv("CLASSIFY_LM", _DEFAULT_MODEL), temperature=0)
    # JSONAdapter parses the response as one JSON object, so Optional and list
    # fields decode to real None / lists instead of literal JSON strings (the bug
    # that broke extract's union fields under the default adapter).
    dspy.configure(lm=lm, adapter=dspy.JSONAdapter())
    return lm
