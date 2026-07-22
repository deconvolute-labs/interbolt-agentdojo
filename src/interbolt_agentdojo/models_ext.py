"""Injects current model ids into AgentDojo without touching its source.

AgentDojo's `ModelsEnum` is a `StrEnum`, which cannot be extended at runtime,
and it's stale (tops out around Claude 3.7 / GPT-4o-mini-2024-07-18). Rather
than patch the enum or fork AgentDojo, `PipelineConfig(llm=...)` already
accepts a constructed `BasePipelineElement` directly (see
`AgentPipeline.from_config`'s `isinstance(config.llm, str)` branch) -- so
`make_llm` builds the provider client ourselves and bypasses the enum
entirely. This keeps AgentDojo pinnable and unmodified; see the README's
"Design choice: model registry patching" section.

Gemini ids are a second, different reason to bypass: Gemini flash models
and friends are already `ModelsEnum` members, so the enum isn't the problem
-- but AgentDojo's own `get_llm()` "google" branch hardcodes Vertex AI auth
(`GCP_PROJECT`/`GCP_LOCATION` + `gcloud auth application-default login`)
instead of a plain API key. `GoogleLLM` itself accepts any `genai.Client`,
so `make_llm` builds one with `api_key=os.getenv("GOOGLE_API_KEY")` (Gemini
Developer API / AI Studio) and the caller (`run_benchmark._resolve_model`)
routes every `gemini-` id here unconditionally, regardless of `ModelsEnum`
membership, to skip AgentDojo's Vertex wiring entirely.

OpenAI ids have no such auth-mode problem -- AgentDojo's `get_llm("openai", ...)`
already builds a plain `openai.OpenAI()` client, reading `OPENAI_API_KEY` via
the SDK's own default, same as this file's Anthropic branch. So already-
enumerated GPT ids (e.g. `gpt-3.5-turbo-0125`) work today with no bypass at
all. The `gpt-`/`o1`/`o3` branch below exists only so that a *newer, not yet
enumerated* OpenAI id doesn't silently fall through to the Anthropic `else`
branch and get sent to the wrong provider.

`MODEL_NAMES` (`agentdojo.models`) is a different kind of extension point:
a plain module-level `dict`, not tied to the enum, that some attacks (e.g.
`important_instructions`) read at call time via
`agentdojo.attacks.base_attacks.get_model_name_from_pipeline` to look up a
prose model name by substring-matching `pipeline.name`. Since it's mutable,
`make_llm` registers the id there too -- the dict-extension route the spec
calls for, applied where it's actually mutable.
"""

from __future__ import annotations

import os

import anthropic
import openai
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.llms.anthropic_llm import AnthropicLLM
from agentdojo.agent_pipeline.llms.google_llm import GoogleLLM
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES
from google import genai


def make_llm(model: str) -> BasePipelineElement:
    """Construct an LLM pipeline element for `model`, bypassing `ModelsEnum`'s provider wiring."""
    if model.startswith("gemini-"):
        MODEL_NAMES.setdefault(model, "Gemini")
        llm = GoogleLLM(model, genai.Client(api_key=os.getenv("GOOGLE_API_KEY")))
    elif model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        MODEL_NAMES.setdefault(model, "GPT")
        llm = OpenAILLM(openai.OpenAI(), model)
    else:
        MODEL_NAMES.setdefault(model, "Claude")
        llm = AnthropicLLM(anthropic.Anthropic(), model)
    llm.name = model
    return llm


def register_current_models() -> None:
    """No-op: `ModelsEnum` (a StrEnum) cannot be extended at runtime.

    `MODEL_NAMES` registration happens lazily in `make_llm`, per model id
    actually used, rather than a hardcoded snapshot list here that would
    itself go stale. Kept as a callable for the documented import-time
    hook, even though there is nothing to do eagerly.
    """
