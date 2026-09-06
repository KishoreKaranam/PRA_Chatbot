# Central configuration for the whole backend.
# All scripts import values from here instead of hardcoding paths/keys.

import os
from dotenv import load_dotenv

# Load variables from .env file if present.
# override=True ensures .env always wins over stale environment variables
# that may already be set in the shell (e.g. injected by VS Code's
# python.terminal.useEnvFile at terminal creation time).
load_dotenv(override=True)

# --- Folders ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "storage", "uploads")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Make sure folders exist at import time.
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# --- Supported file formats: extension -> allowed MIME types ---
SUPPORTED_FORMATS = {
    "xls": ["application/vnd.ms-excel"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    "csv": ["text/csv", "application/csv", "text/plain"],
    "doc": ["application/msword"],
    "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "rtf": ["application/rtf", "text/rtf"],
    "txt": ["text/plain"],
    "pdf": ["application/pdf"],
}

# --- Anthropic Claude on Azure AI Foundry settings ---
# Base URL of the Foundry resource, e.g. https://<resource-name>.services.ai.azure.com/anthropic
AZURE_FOUNDRY_BASE_URL = os.getenv("AZURE_FOUNDRY_BASE_URL", "")
AZURE_FOUNDRY_API_KEY = os.getenv("AZURE_FOUNDRY_API_KEY", "")
# Deployment name chosen when the model was deployed in Foundry (not necessarily the raw model id).
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
# Safety limit on how many tool-call round trips the agent may perform.
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "20"))

# --- Neo4j settings ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- API server settings ---
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "5000"))
