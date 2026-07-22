"""models_ext.py tests. No network calls."""

from __future__ import annotations

from agentdojo.agent_pipeline.llms.anthropic_llm import AnthropicLLM
from agentdojo.agent_pipeline.llms.google_llm import GoogleLLM
from agentdojo.models import MODEL_NAMES

from interbolt_agentdojo.models_ext import make_llm
from interbolt_agentdojo.run_benchmark import _resolve_model


def test_make_llm_gemini_uses_api_key_client_not_vertex(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")
    llm = make_llm("gemini-1.5-flash-001")
    assert isinstance(llm, GoogleLLM)
    assert llm.name == "gemini-1.5-flash-001"
    assert llm.client.vertexai is False
    # setdefault: upstream agentdojo.models.MODEL_NAMES already has this id
    # registered, so make_llm's "Gemini" default is intentionally not used here.
    assert "gemini-1.5-flash-001" in MODEL_NAMES


def test_make_llm_gemini_registers_default_model_name_when_unknown(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")
    make_llm("gemini-99.9-future-preview")
    assert MODEL_NAMES["gemini-99.9-future-preview"] == "Gemini"


def test_make_llm_anthropic_still_builds_anthropic_llm():
    llm = make_llm("claude-haiku-4-5-20251001")
    assert isinstance(llm, AnthropicLLM)
    assert llm.name == "claude-haiku-4-5-20251001"
    assert MODEL_NAMES["claude-haiku-4-5-20251001"] == "Claude"


def test_resolve_model_forces_gemini_through_bypass_despite_enum_membership(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")
    # gemini-1.5-flash-001 is already a ModelsEnum member, but should still
    # be resolved to a constructed pipeline element (API-key auth), not the
    # bare string (which would otherwise route through AgentDojo's Vertex path).
    resolved = _resolve_model("gemini-1.5-flash-001")
    assert isinstance(resolved, GoogleLLM)
    assert resolved.client.vertexai is False


def test_resolve_model_leaves_known_anthropic_id_as_string():
    resolved = _resolve_model("claude-3-haiku-20240307")
    assert resolved == "claude-3-haiku-20240307"
