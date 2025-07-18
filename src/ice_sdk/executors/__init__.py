"""Executors package.

Importing :pymod:`ice_sdk.executors` has the side-effect of registering all
built-in node executors (``ai`` and ``tool``).  Third-party packages can add
more executors by simply calling

```python
from ice_sdk.node_registry import register_node

@register_node("my_mode")
async def my_executor(chain, cfg, ctx):
    ...
```

This design keeps *ScriptChain* agnostic of concrete node types.
"""

# Register built-ins ---------------------------------------------------------
from importlib import import_module

# Importing the module triggers decorator registration.
import_module("ice_sdk.executors.builtin")

# Register *condition* node executor ----------------------------------------
try:
    import_module("ice_sdk.executors.condition")
except (
    ModuleNotFoundError
):  # pragma: no cover – defender when file missing in older envs
    pass

# Register *loop* node executor -------------------------------------------
try:
    import_module("ice_sdk.executors.loop")
except ModuleNotFoundError:  # pragma: no cover
    pass

# Register *prebuilt* node executor -----------------------------------------
try:
    import_module("ice_sdk.executors.prebuilt")
except ModuleNotFoundError:  # pragma: no cover
    pass

# Knowledge node executor removed - focusing on core patterns
