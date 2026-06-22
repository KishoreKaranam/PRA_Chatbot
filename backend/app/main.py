"""
PRA Chatbot – backend application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, config, health
from app.core.log_config import configure_logging
from app.core.settings import get_settings

configure_logging()

# Clear the settings cache so every (re)start picks up the latest .env
get_settings.cache_clear()

app = FastAPI(
    title="PRA Chatbot API",
    description="Chatbot for the Payment Reference Architecture GraphDB repository",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(config.router, prefix="/api", tags=["config"])
