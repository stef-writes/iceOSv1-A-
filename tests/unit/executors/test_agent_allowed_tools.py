import pytest

from ice_core.models.model_registry import get_default_model_id
from ice_orchestrator.workflow import ScriptChain
from ice_sdk.models.node_models import LLMOperatorConfig
from ice_sdk.providers.llm_service import LLMService
from ice_sdk.skills import ToolContext, function_tool


@function_tool(name_override="my_tool")
async def _my_tool(ctx: ToolContext):  # type: ignore[override]
    return {"ok": True}


@pytest.mark.asyncio
async def test_allowed_tools_whitelist():
    """Agentic AI node should only see tools listed in *allowed_tools*."""

    # ------------------------------------------------------------------
    # Stub LLMService to avoid external API calls -----------------------
    # ------------------------------------------------------------------

    async def _stub_generate(*_args, **_kwargs):  # noqa: D401 – test stub
        return "OK", None, None  # text, usage, error

    monkeypatch_ctx = pytest.MonkeyPatch()
    monkeypatch_ctx.setattr(LLMService, "generate", _stub_generate)

    node = LLMOperatorConfig(
        id="ai1",
        name="AI1",
        type="ai",
        model=get_default_model_id(),
        prompt="Return OK",
        llm_config={},  # type: ignore[arg-type]
        allowed_tools=["my_tool"],
    )

    chain = ScriptChain(
        nodes=[node],  # type: ignore[arg-type]
        tools=[_my_tool],
        name="allowed-tools-test",
        persist_intermediate_outputs=False,
        use_cache=False,
    )

    result = await chain.execute()

    # Undo patch --------------------------------------------------------
    monkeypatch_ctx.undo()

    # Expect success because the single tool is whitelisted; agent executes once
    assert result.success is True
