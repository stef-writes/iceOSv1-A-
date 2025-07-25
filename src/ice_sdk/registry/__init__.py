"""Unified public import surface for runtime registries.

External code should import registry helpers exclusively from this module to
avoid hard-coding disparate file paths.  All legacy modules continue to work
via thin shim re-exports (see individual sub-modules).

Example
-------
>>> from ice_sdk.registry import SkillRegistry
>>> SkillRegistry.register(...)
"""

from __future__ import annotations

from ice_sdk.capabilities.registry import CapabilityRegistry

from .node import NODE_REGISTRY as NodeRegistry  # – re-export
from .processor import global_processor_registry as ProcessorRegistry
from .skill import SkillRegistry as SkillRegistry  # – re-export class
from .skill import (
    global_skill_registry as global_skill_registry,  # – convenience instance
)

__all__: list[str] = [
    "NodeRegistry",
    "SkillRegistry",
    "ProcessorRegistry",
    "global_skill_registry",
    "CapabilityRegistry",
]
