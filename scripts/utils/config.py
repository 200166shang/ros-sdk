"""Project-wide constants."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE_DIR = Path("/workspace")
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yaml"
COMPOSE_PROJECT_NAME = "rosbridge"
