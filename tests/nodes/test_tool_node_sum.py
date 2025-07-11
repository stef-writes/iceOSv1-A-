import pytest

from ice_orchestrator.script_chain import ScriptChain
from ice_sdk.models.node_models import ToolNodeConfig
from ice_sdk.services import ServiceLocator
from ice_sdk.tools.system import SumTool


@pytest.mark.asyncio
async def test_tool_node_sum_execution() -> None:
    """ScriptChain should execute a ToolNode backed by SumTool and return correct sum."""

    # Ensure clean registry ------------------------------------------------------
    ServiceLocator.clear()

    # Register deterministic tool ------------------------------------------------
    sum_tool = SumTool()

    # Create single ToolNodeConfig ---------------------------------------------
    node_cfg = ToolNodeConfig(
        id="sum1",
        type="tool",
        name="Sum Numbers",
        tool_name="sum",
        tool_args={"numbers": [4, 5, 6]},
    )

    chain = ScriptChain(nodes=[node_cfg], tools=[sum_tool], name="sum-chain")

    result = await chain.execute()

    assert result.success is True
    assert result.output is not None

    node_result = result.output["sum1"]  # type: ignore[index]
    assert node_result.success is True
    assert node_result.output == {"sum": 15}
