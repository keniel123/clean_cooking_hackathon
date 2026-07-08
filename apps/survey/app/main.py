import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .config import get_settings
from .db import init_db
from .routes import api, demo, webhooks

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Minigrid SMS Survey",
    description="Two-way SMS surveys for rural electric minigrid customers",
    version="0.1.0",
    lifespan=lifespan,
)

# read-only cross-origin access for the monitoring dashboard (apps/dashboard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(webhooks.router)
app.include_router(api.router)
app.include_router(demo.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    target = "/demo" if get_settings().enable_simulator else "/docs"
    return RedirectResponse(url=target)
