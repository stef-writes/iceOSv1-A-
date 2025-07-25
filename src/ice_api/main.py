"""
FastAPI application entry point
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, List

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ice_api.redis_client import get_redis

# NEW MCP router import
# Service registration (orchestrator runtime) ------------------------------
from ice_orchestrator.services.workflow_service import WorkflowService
from ice_sdk.services import ServiceLocator as _SvcLoc  # avoid name clash later

# Register once at import time so routers can resolve it
if "workflow_service" not in _SvcLoc._services:  # type: ignore[attr-defined]
    _SvcLoc.register("workflow_service", WorkflowService())

# Router imports (can now resolve service)
from ice_api.api.builder import router as builder_router
from ice_api.api.mcp import router as mcp_router
from ice_api.ws_gateway import router as ws_router
from ice_core.utils.logging import setup_logger
from ice_sdk import ToolService
from ice_sdk.context import GraphContextManager

# kb_router removed - focusing on core patterns
from ice_sdk.providers.llm_service import LLMService
from ice_sdk.services import ChainService  # Proper service boundary
from ice_sdk.services import ServiceLocator
from ice_sdk.utils.errors import add_exception_handlers

# Setup logging
logger = setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager"""
    # Startup
    # Get the project root directory (where .env should be)
    project_root = Path(__file__).parent.parent.parent

    # Load environment variables from the first existing candidate file.
    # Priority: .env.local (developer-specific) > .env (default) > .env.example (template)
    for candidate in (".env.local", ".env", ".env.example"):
        env_path = project_root / candidate
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            break

    # Create singleton services and attach to app state so they can be injected elsewhere.
    tool_service = ToolService()
    # Expose for tests
    app.state.tool_service = tool_service
    ctx_manager = GraphContextManager()

    # Initialize Redis -----------------------------------------------------
    redis = get_redis()
    try:
        await redis.ping()
    except Exception as exc:
        logger.warning("Redis connection failed: %s", exc)

    app.state.redis = redis  # type: ignore[attr-defined]

    # Register in global ServiceLocator ------------------------------------
    ServiceLocator.register("tool_service", tool_service)
    ServiceLocator.register("context_manager", ctx_manager)
    ServiceLocator.register("llm_service", LLMService())

    # Register built-in tools (best-effort) -----------------------------
    for tool_name in tool_service.available_tools():
        try:
            tool_obj = tool_service.get(tool_name)
            ctx_manager.register_tool(tool_obj)
            logger.info("Tool '%s' registered with context manager", tool_name)
        except Exception as exc:  # pragma: no cover – missing deps etc.
            logger.warning("Tool '%s' could not be registered: %s", tool_name, exc)

    # Auto-discover additional `*.tool.py` modules in the repository ---------
    try:
        tool_service.discover_and_register(project_root)
    except Exception as exc:  # – best-effort discovery
        logger.warning("Tool auto-discovery failed: %s", exc)

    app.state.context_manager = ctx_manager  # type: ignore[attr-defined]

    # Load all relevant API keys from environment and make them available if needed by SDKs
    # The actual key used by an LLM call will be the one specified in the Node's LLMConfig.
    # This step ensures that if SDKs implicitly look for env vars, they might be found.

    # Track presence of optional API keys.  Use explicit ``bool`` values so
    # static type checkers understand what the dictionary will hold.
    api_keys_to_load: dict[str, bool] = {
        "OPENAI_API_KEY": False,
        "ANTHROPIC_API_KEY": False,
        "GOOGLE_API_KEY": False,  # For Gemini
        "DEEPSEEK_API_KEY": False,
    }

    for key_name in api_keys_to_load:
        key_value = os.getenv(key_name)
        if key_value is not None and key_value.strip():  # Check for non-empty string
            os.environ[key_name] = (
                key_value  # Make it available to any SDK that might look for it
            )
            api_keys_to_load[key_name] = True  # Mark as found
            logger.info(f"{key_name} loaded from environment.")
        else:
            api_keys_to_load[key_name] = False
            logger.warning(f"{key_name} not found in environment or .env file.")

    # Example: If you still want to ensure at least one key is present for a default provider
    # if not api_keys_to_load["OPENAI_API_KEY"] and not api_keys_to_load["ANTHROPIC_API_KEY"] etc.:
    #     logger.error("No API keys found for any supported providers. Application might not function correctly.")

    logger.info("Starting up the application...")

    # Register standard exception handlers (must happen *after* app creation).
    add_exception_handlers(app)

    yield

    # Shutdown
    # Add any cleanup code here
    pass


# Create FastAPI app
app = FastAPI(title="iceOS API")

# Expose globally for immediate availability in tests (before lifespan)
tool_service_global = ToolService()
app.state.tool_service = tool_service_global  # type: ignore[attr-defined]
app.state.context_manager = GraphContextManager()  # type: ignore[attr-defined]
app.state.redis = get_redis()  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# CORS – allow any origin for demo/testing so smoke tests pass --------------
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include MCP & builder routers -----------------------------------
app.include_router(mcp_router)
app.include_router(builder_router)
# kb_router removed - focusing on core patterns
app.include_router(ws_router)
# Canvas workflow endpoints
from ice_api.api.workflows import router as workflows_router  # – after FastAPI init

app.include_router(workflows_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Simple welcome endpoint."""
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to iceOS"}


# Add minimal health-check and tools listing endpoints -----------------------


@app.get("/health", tags=["utils"])
async def health_check() -> dict[str, str]:
    """Return simple health status so external monitors can probe the API."""
    return {"status": "ok"}


@app.get("/v1/tools", response_model=List[str], tags=["utils"])
async def list_tools_v1(request: Request) -> List[str]:
    """Return all registered tool names (legacy alias without /api prefix)."""
    tool_service = request.app.state.tool_service  # type: ignore[attr-defined]
    return sorted(tool_service.available_tools())


# ---------------------------------------------------------------------------
# Capability catalog endpoint ------------------------------------------------
# ---------------------------------------------------------------------------


router = APIRouter()


@router.post("/run-chain/{chain_id}")
async def run_chain(chain_id: str, input_data: dict):
    """Generic endpoint that could execute any registered chain"""
    result = await ChainService.execute(chain_id, input_data)
    return {"result": result}
