"""Agent instructions configuration endpoint."""
from fastapi import APIRouter
from app.models.schemas import AgentInstructions
from app.infrastructure.configuration.config_service import get_config_service

router = APIRouter()


@router.get("/config/instructions", response_model=AgentInstructions)
async def get_instructions() -> AgentInstructions:
    """Return the current agent instructions."""
    return get_config_service().get()


@router.put("/config/instructions", response_model=AgentInstructions)
async def update_instructions(instructions: AgentInstructions) -> AgentInstructions:
    """Update agent instructions and persist to disk."""
    return get_config_service().update(instructions)


@router.post("/config/instructions/reset", response_model=AgentInstructions)
async def reset_instructions() -> AgentInstructions:
    """Reset agent instructions to defaults."""
    return get_config_service().reset()
