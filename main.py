from fastapi import FastAPI
from app.routers import auth_router, games_router, scenarios_router

app = FastAPI(title="civgame", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(games_router.router)
app.include_router(scenarios_router.router)