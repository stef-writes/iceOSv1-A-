# ruff: noqa: E402
from __future__ import annotations

"""Built-in node executors for *ice_orchestrator*.

Moved from :pymod:`ice_sdk.executors.builtin` to keep runtime code inside the
orchestrator layer.
"""

# Standard library imports -----------------------------------------------------
import re
from datetime import datetime
from typing import Any, Dict, TypeAlias

from ice_core.models import (
    LLMOperatorConfig,
    NodeConfig,
    NodeExecutionResult,
    SkillNodeConfig,
)
from ice_core.models.node_models import NestedChainConfig, NodeMetadata

# NOTE: use AgentNode from ice_sdk and WorkflowLike alias
from ice_sdk import AgentNode
from ice_sdk.interfaces.chain import WorkflowLike as _WorkflowLike
from ice_sdk.models.agent_models import AgentConfig, ModelSettings
from ice_sdk.registry.node import register_node
from ice_sdk.skills import SkillBase
from ice_sdk.utils.prompt_renderer import render_prompt

# Alias used in annotations locally ------------------------------------------
ScriptChain: TypeAlias = _WorkflowLike

# ---------------------------------------------------------------------------
# Helper – build AgentNode from LLMOperatorConfig (duplicated from ScriptChain._make_agent)
# ---------------------------------------------------------------------------


def _build_agent(chain: ScriptChain, node: LLMOperatorConfig) -> AgentNode:
    """Build or fetch a cached AgentNode instance for *node*."""
    agent_cache: Dict[str, AgentNode] = getattr(chain, "_agent_cache")
    existing = agent_cache.get(node.id)
    if existing is not None:
        return existing

    # Build precedence-aware tool map ------------------------------------
    tool_map: Dict[str, SkillBase] = {}

    # 1. Globally registered tools (lowest precedence) -------------------
    for name, tool in chain.context_manager.get_all_tools().items():
        tool_map[name] = tool

    # 2. Chain-level tools — override when name clashes ------------------
    for t in getattr(chain, "_chain_skills", []):
        tool_map[t.name] = t

    # 3. Node-specific tool references — highest precedence -------------
    if node.tools:
        for cfg in node.tools:  # type: ignore[attr-defined]
            t_obj = chain.context_manager.get_tool(cfg.name)
            if t_obj is not None:
                tool_map[t_obj.name] = t_obj

    # -----------------------------------------------------------------------
    # 4. Apply explicit *allowed_tools* whitelist on the node config ---------
    # -----------------------------------------------------------------------

    if node.allowed_tools is not None:
        allowed_set = set(node.allowed_tools)
        tool_map = {name: t for name, t in tool_map.items() if name in allowed_set}

    tools: list[SkillBase] = list(tool_map.values())

    model_settings = ModelSettings(
        model=node.model,
        temperature=getattr(node, "temperature", 0.7),
        max_tokens=getattr(node, "max_tokens", None),
        provider=str(getattr(node.provider, "value", node.provider)),
    )

    agent_cfg = AgentConfig(
        name=node.name or node.id,
        instructions=node.prompt,
        model=node.model,
        model_settings=model_settings,
        tools=tools,
    )  # type: ignore[call-arg]

    agent = AgentNode(config=agent_cfg, context_manager=chain.context_manager)
    agent.tools = tools

    # Register with context manager
    try:
        chain.context_manager.register_agent(agent)
    except ValueError:
        pass

    for tool in tools:
        try:
            chain.context_manager.register_tool(tool)
        except ValueError:
            continue

    agent_cache[node.id] = agent
    return agent


# ---------------------------------------------------------------------------
# "ai" executor ------------------------------------------------------------
# ---------------------------------------------------------------------------


@register_node("ai")  # legacy discriminator  # type: ignore[type-var]
@register_node("llm")  # new discriminator  # type: ignore[type-var]
async def ai_executor(  # type: ignore[type-var]
    chain: ScriptChain, cfg: NodeConfig, ctx: Dict[str, Any]
) -> NodeExecutionResult:
    """Executor for LLM-powered *ai* nodes."""

    if not isinstance(cfg, LLMOperatorConfig):
        raise TypeError("ai_executor received incompatible cfg type")

    # ------------------------------------------------------------------
    # Dynamic prompt templating ----------------------------------------
    # ------------------------------------------------------------------
    # *render_prompt* substitutes any placeholder expressions in the
    # ``cfg.prompt`` string using the *ctx* dict prepared by ScriptChain.
    # The helper falls back to the original string if rendering fails so
    # we never break node execution due to missing keys.

    # Render template ---------------------------------------------------
    rendered_prompt: str
    try:
        rendered_prompt = await render_prompt(cfg.prompt, ctx)
    except Exception:
        # Keep original prompt on rendering failure but still check leftovers
        rendered_prompt = cfg.prompt

    # After rendering, ensure no unresolved placeholders remain ---------
    _LEFTOVER_RE = re.compile(r"\{\s*[a-zA-Z0-9_\.]+\s*\}")
    if _LEFTOVER_RE.search(rendered_prompt):
        raise ValueError(
            f"Prompt for node '{cfg.id}' contains unresolved placeholders after rendering: {rendered_prompt}"
        )

    cfg.prompt = rendered_prompt  # type: ignore[assignment]

    agent = _build_agent(chain, cfg)
    ai_output = await agent.execute(ctx)

    return NodeExecutionResult(  # type: ignore[call-arg]
        success=True,
        output=ai_output,
        metadata=NodeMetadata(
            node_id=cfg.id,
            node_type="llm",
            name=cfg.name,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        ),
        execution_time=0.0,
    )


# ---------------------------------------------------------------------------
# "tool" executor ----------------------------------------------------------
# ---------------------------------------------------------------------------


@register_node("tool")  # legacy discriminator  # type: ignore[type-var]
@register_node("skill")  # new discriminator  # type: ignore[type-var]
async def tool_executor(  # type: ignore[type-var]
    chain: ScriptChain, cfg: NodeConfig, ctx: Dict[str, Any]
) -> NodeExecutionResult:
    """Executor for deterministic tool nodes with context-aware `tool_args`."""

    if not isinstance(cfg, SkillNodeConfig):
        raise TypeError("tool_executor received incompatible cfg type")

    def _apply_ctx(value: Any) -> Any:  # – helper
        """Recursively substitute `{key}` placeholders using *ctx*."""
        if isinstance(value, str):
            try:
                return value.format(**ctx)
            except Exception:
                return value  # leave unchanged if placeholder missing
        if isinstance(value, dict):
            return {k: _apply_ctx(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_apply_ctx(v) for v in value]
        return value

    tool_name = cfg.tool_name  # type: ignore[attr-defined]
    raw_args = getattr(cfg, "tool_args", {}) or {}
    tool_args = _apply_ctx(raw_args)

    output = await chain.context_manager.execute_tool(tool_name, **tool_args)

    result = NodeExecutionResult(  # type: ignore[call-arg]
        success=True,
        output=output,
        metadata=NodeMetadata(  # type: ignore[call-arg]
            node_id=cfg.id,
            node_type="tool",
            name=cfg.name,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        ),
        execution_time=0.0,
    )
    return result


# ---------------------------------------------------------------------------
# "nested_chain" executor ----------------------------------------------------
# ---------------------------------------------------------------------------


@register_node("nested_chain")  # type: ignore[misc,type-var]  # decorator preserves signature
async def nested_chain_executor(
    chain: ScriptChain, cfg: NodeConfig, ctx: Dict[str, Any]
) -> NodeExecutionResult:
    """Executor that runs a *nested* ScriptChain.

    The nested chain instance (or a zero-argument factory) is provided via
    :class:`~ice_sdk.models.node_models.NestedChainConfig.chain`.
    Input mappings are handled upstream by :class:`ScriptChain`; *ctx* is
    therefore the fully-rendered input for the child chain.
    """

    if not isinstance(cfg, NestedChainConfig):
        raise TypeError("nested_chain_executor received incompatible cfg type")

    # Resolve child chain instance ------------------------------------------------
    child = cfg.chain  # could be ScriptChain or factory

    try:
        child_chain: ScriptChain = child() if callable(child) else child  # type: ignore[operator]
    except Exception as exc:  # pragma: no cover – defensive
        raise RuntimeError(
            f"Failed to instantiate nested chain for node '{cfg.id}': {exc}"
        ) from exc

    # Best-effort: update child context with *ctx* --------------------------------
    try:
        from ice_sdk.context import (  # imported here to avoid heavy deps at module import
            GraphContextManager,
        )
        from ice_sdk.context.manager import GraphContext

        cm = GraphContextManager()
        cm.set_context(
            GraphContext(
                session_id=f"nested_{cfg.id}",
                metadata=ctx,
                execution_id=f"nested_{cfg.id}_{datetime.utcnow().isoformat()}",
            )
        )
        child_chain.context_manager = cm  # type: ignore[assignment]
    except (
        Exception
    ):  # pragma: no cover – never abort parent chain due to context issues
        pass

    # Execute child chain ---------------------------------------------------------
    child_result = await child_chain.execute()  # type: ignore[attr-defined]

    # Apply *exposed_outputs* mapping when present ---------------------------------
    output_payload: Any = child_result.output
    if cfg.exposed_outputs and isinstance(output_payload, dict):
        try:
            import jmespath  # optional dependency – only used when mapping requested

            mapped: Dict[str, Any] = {}
            for public_key, query in cfg.exposed_outputs.items():
                mapped[public_key] = jmespath.search(query, output_payload)
            output_payload = mapped
        except Exception:
            # Silently ignore mapping errors – propagate raw output
            pass

    # Wrap into parent-level result ------------------------------------------------
    result = NodeExecutionResult(  # type: ignore[call-arg]
        success=child_result.success,
        error=child_result.error,
        output=output_payload,
        metadata=NodeMetadata(  # type: ignore[call-arg]
            node_id=cfg.id,
            node_type="nested_chain",
            name=cfg.name,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        ),
        execution_time=child_result.execution_time,
    )
    return result
