import os

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_USERS = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
]
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "$")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_OPTIONS = {
    "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.6")),
    "top_p": float(os.getenv("OLLAMA_TOP_P", "0.95")),
}

DATA_DIR = os.getenv("DATA_DIR", "./data")
THINGS_DIR = os.path.join(DATA_DIR, "things")
DB_DIR = os.path.join(DATA_DIR, "db")

HANDLER_TIMEOUT = float(os.getenv("HANDLER_TIMEOUT", "60"))
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "40"))


OLLAMA_TIMEOUT = 300
VERSION_HISTORY_LIMIT = 3
FETCH_MAX_CHARS = 8192
THING_ERROR_HISTORY = 2
