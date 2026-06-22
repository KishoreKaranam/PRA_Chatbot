"""
Agent instructions config store.

Persists the current agent instructions to a JSON file so they survive
server restarts.  Kept simple (file-based) to avoid an extra database
dependency.  Swap with a Redis / DB store in production.
"""
from __future__ import annotations

import json
import pathlib
from app.models.schemas import AgentInstructions
from app.core.log_config import get_logger

logger = get_logger(__name__)

CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "agent_instructions.json"


class ConfigService:
    """CRUD for agent instructions."""

    def __init__(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._instructions: AgentInstructions = self._load()

    def get(self) -> AgentInstructions:
        return self._instructions

    def update(self, instructions: AgentInstructions) -> AgentInstructions:
        self._instructions = instructions
        self._save(instructions)
        logger.info("agent_instructions_updated")
        return self._instructions

    def reset(self) -> AgentInstructions:
        self._instructions = AgentInstructions()
        self._save(self._instructions)
        return self._instructions

    def _load(self) -> AgentInstructions:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return AgentInstructions(**data)
            except Exception as exc:
                logger.warning("config_load_failed", error=str(exc))
        return AgentInstructions()

    def _save(self, instructions: AgentInstructions) -> None:
        try:
            CONFIG_PATH.write_text(
                instructions.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("config_save_failed", error=str(exc))


# Singleton
_config_service: ConfigService | None = None


def get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service
