from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import audit, health

logger = structlog.get_logger()


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

# Serve frontend — must be mounted last so API routes take priority
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
