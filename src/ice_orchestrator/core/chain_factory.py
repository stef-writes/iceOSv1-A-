"""Factory for creating ScriptChain instances from JSON payloads.

Extracted from `ScriptChain.from_dict` to improve separation of concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:  # pragma: no cover
    from ice_orchestrator.script_chain import ScriptChain


class ChainFactory:  # noqa: D101 – internal utility
    """Factory for creating ScriptChain instances from JSON-compatible payloads."""

    @classmethod
    async def from_dict(
        cls,
        payload: Dict[str, Any],
        *,
        target_version: str = "1.0.0",
        **kwargs: Any,
    ) -> "ScriptChain":
        """Create a ScriptChain from JSON-compatible *payload*.

        The helper calls :pyclass:`ice_orchestrator.chain_migrator.ChainMigrator`
        to upgrade older workflow specs before instantiation.
        """

        # Import lazily to avoid cycles ----------------------------------
        from ice_orchestrator.chain_migrator import ChainMigrator

        # 1. Run migration (no-op when already up-to-date) ---------------
        try:
            payload = await ChainMigrator.migrate(payload, target_version)
        except NotImplementedError as exc:
            # Bubble-up – caller decides whether to abort or run legacy
            raise RuntimeError(str(exc)) from exc

        # 2. Parse nodes --------------------------------------------------
        nodes_raw = payload.get("nodes", [])
        if not nodes_raw:
            raise ValueError("Workflow payload must contain 'nodes' key")

        # Discriminated union parsing (manual to avoid Annotated typing issues)
        from ice_sdk.models.node_models import (
            AiNodeConfig,
            ConditionNodeConfig,
            ToolNodeConfig,
        )

        _parser_map = {
            "ai": AiNodeConfig,
            "tool": ToolNodeConfig,
            "condition": ConditionNodeConfig,
        }

        nodes = []
        for nd in nodes_raw:
            node_type = nd.get("type")
            parser_cls = _parser_map.get(node_type)
            if parser_cls is None:
                raise ValueError(f"Unknown node type '{node_type}' in workflow spec")
            nodes.append(parser_cls.model_validate(nd))

        # 3. Instantiate chain -------------------------------------------
        import hashlib
        import json

        from ice_orchestrator.script_chain import ScriptChain
        from ice_sdk.models.node_models import ChainMetadata

        # Compute basic DAG statistics & topology hash ------------------
        node_count = len(nodes)
        edge_count = sum(len(getattr(n, "dependencies", [])) for n in nodes)

        # Deterministic hash of adjacency list (node id -> sorted deps)
        adjacency = {n.id: sorted(getattr(n, "dependencies", [])) for n in nodes}
        topology_hash = hashlib.sha256(
            json.dumps(adjacency, sort_keys=True).encode()
        ).hexdigest()

        chain_meta = ChainMetadata(
            chain_id=payload.get("chain_id", f"chain_{topology_hash[:8]}"),
            name=payload.get("name", "unnamed-chain"),
            version=payload.get("version", target_version),
            description=payload.get("description", ""),
            node_count=node_count,
            edge_count=edge_count,
            topology_hash=topology_hash,
            tags=payload.get("tags", []),
        )

        chain = ScriptChain(
            nodes=nodes,
            name=payload.get("name"),
            version=payload.get("version", target_version),
            **kwargs,
        )

        # Attach metadata for later dashboards / side-car emission
        setattr(chain, "metadata", chain_meta)

        return chain
