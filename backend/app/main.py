from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .services.market_hub import MarketHub

settings = get_settings()
hub = MarketHub(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(Path(settings.static_dir) / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/system/status")
async def system_status() -> dict:
    return hub.get_system_status()


@app.get("/api/matches")
async def matches() -> list[dict]:
    return hub.get_matches()


@app.get("/api/market/{market_id}/snapshot")
async def market_snapshot(market_id: str) -> dict:
    snapshot = hub.get_snapshot(market_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="market not found")
    return snapshot


@app.get("/api/market/{market_id}/timeseries")
async def market_timeseries(market_id: str, limit: int = 120) -> list[dict]:
    snapshot = hub.get_snapshot(market_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="market not found")
    return hub.get_timeseries(market_id, limit=limit)


@app.get("/api/market/{market_id}/recommendation")
async def market_recommendation(market_id: str) -> dict:
    recommendation = hub.get_recommendation(market_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return recommendation


@app.websocket("/ws/market-stream")
async def market_stream(websocket: WebSocket) -> None:
    await hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.unregister(websocket)
