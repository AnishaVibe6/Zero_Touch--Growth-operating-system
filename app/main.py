from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import audit, health

logger = structlog.get_logger()

_FRONTEND_HTML = Path(__file__).parent.parent / "frontend" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ztgos.startup")
    yield
    logger.info("ztgos.shutdown")


app = FastAPI(
    title="Zero Touch Growth OS",
    description="Automated digital audit engine for Indian MSMEs",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    """Serve the SPA with no-cache headers so stale JS never gets stuck."""
    content = _FRONTEND_HTML.read_text(encoding="utf-8")
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


# Static assets (CSS, JS files if any) — mounted after explicit routes
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
