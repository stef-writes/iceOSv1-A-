"""Base classes for the tooling system."""

import inspect
from functools import wraps
from typing import Any, Callable, ClassVar, Dict, Optional, TypeVar, cast

from pydantic import BaseModel

T = TypeVar("T")


class ToolError(Exception):
    """Base exception for tool errors."""

    pass


class ToolContext(BaseModel):
    """Context passed to tools during execution."""

    agent_id: str
    session_id: str
    metadata: Dict[str, Any] = {}


class BaseTool(BaseModel):
    """Base class for all tools.

    ``name``/``description``/``parameters_schema``/``output_schema`` are defined
    as *class variables* so subclasses can simply override them without Pydantic
    treating them as model fields (fixes the field-override error we hit during
    testing).
    """

    # Tool metadata ----------------------------------------------------------------
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters_schema: ClassVar[Dict[str, Any] | None] = None
    output_schema: ClassVar[Dict[str, Any] | None] = None

    # Extended metadata for discovery / copilot --------------------------------
    # ``purpose``   – one-sentence natural language summary of *why* to use the
    #                 tool (search-friendly, displayed in UIs).
    # ``examples``  – list of small input/output pairs or prompt snippets that
    #                 demonstrate typical usage.
    purpose: ClassVar[str | None] = None
    examples: ClassVar[list[dict[str, Any]] | None] = None

    async def run(self, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments."""
        raise NotImplementedError

    def as_dict(self) -> Dict[str, Any]:
        """Convert tool to dictionary format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
            "output": self.output_schema,
        }

    def validate_params(self, params: Dict[str, Any] | None = None) -> None:
        """Validate *params* against ``parameters_schema`` when defined.

        The method is idempotent – calling it multiple times with the same
        arguments has no side-effects – and raises :class:`ToolError` when the
        supplied *params* violate the declared ``parameters_schema``.
        """
        if self.parameters_schema is None or params is None:
            return

        # Defer heavy import to call-time to avoid penalising start-up
        try:
            import jsonschema  # type: ignore

            jsonschema.validate(instance=params, schema=self.parameters_schema)  # type: ignore[arg-type]
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            raise ToolError(f"Invalid tool parameters: {exc.message}") from exc

    # ------------------------------------------------------------------
    # Rule-compliance: idempotent validate() hook -----------------------
    # ------------------------------------------------------------------

    def runtime_validate(self) -> None:  # noqa: D401
        """Runtime validation stub (idempotent).

        By default delegates to :py:meth:`validate_params` with *None*, which is
        a no-op when the tool defines no parameter schema.  Subclasses may
        override to check external resources, licenses, etc.
        """

        self.validate_params(None)


def function_tool(
    name_override: Optional[str] = None,
    description_override: Optional[str] = None,
    docstring_style: str = "google",
    use_docstring_info: bool = True,
    failure_error_function: Optional[Callable[[ToolContext, Exception], str]] = None,
    strict_mode: bool = True,
) -> Callable[[Callable[..., Any]], BaseTool]:
    """Decorator to convert a function into a tool.

    Args:
        name_override: Custom name for the tool
        description_override: Custom description
        docstring_style: Style of docstring parsing
        use_docstring_info: Whether to use docstring for description
        failure_error_function: Function to handle errors
        strict_mode: Enable strict JSON schema validation
    """

    def decorator(func: Callable[..., Any]) -> BaseTool:
        # Get function metadata
        name = name_override or func.__name__
        doc = func.__doc__ or ""

        # Parse docstring
        if use_docstring_info:
            description = description_override or doc.split("\n")[0].strip()
        else:
            description = description_override or ""

        # Get parameter schema
        sig = inspect.signature(func)
        parameters = {}
        for param_name, param in sig.parameters.items():
            if param_name == "ctx" and param.annotation == ToolContext:
                continue

            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                param_type = Any

            parameters[param_name] = (param_type, ...)

        # Dynamically build subclass where metadata are *class* attributes ------
        attrs: Dict[str, Any] = {
            "name": name,
            "description": description,
            "parameters_schema": parameters,
            "output_schema": {"type": "object"},
        }

        @wraps(func)
        async def wrapper(self: BaseTool, **kwargs: Any) -> Any:  # type: ignore[override]
            try:
                # Handle context if present
                if "ctx" in sig.parameters:
                    ctx = kwargs.pop("ctx")
                    result = (
                        await func(ctx, **kwargs)
                        if inspect.iscoroutinefunction(func)
                        else func(ctx, **kwargs)
                    )
                else:
                    result = (
                        await func(**kwargs)
                        if inspect.iscoroutinefunction(func)
                        else func(**kwargs)
                    )

                return result
            except Exception as e:
                if failure_error_function:
                    return failure_error_function(
                        ToolContext(agent_id="", session_id=""), e
                    )
                raise ToolError(f"Tool execution failed: {str(e)}")

        # Build the concrete subclass + bind run implementation ----------------
        ToolCls = type(f"{name.title()}Tool", (BaseTool,), {**attrs, "run": wrapper})

        # Return an *instance* – cast so mypy sees BaseTool subtype
        return cast(BaseTool, ToolCls())

    return decorator
