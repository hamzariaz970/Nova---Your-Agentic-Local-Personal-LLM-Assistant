import os

# -----------------------------
# Configuration
# -----------------------------

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
CHAT_ENDPOINT = f"{OLLAMA_BASE_URL}/api/chat"
EMBED_ENDPOINT = f"{OLLAMA_BASE_URL}/api/embed"

LLM_MODEL = os.environ.get("ASSISTANT_LLM_MODEL", "qwen3:4b")        # ollama pull qwen3-4b
EMBED_MODEL = os.environ.get("ASSISTANT_EMBED_MODEL", "mxbai-embed-large")

STORAGE_DIR = os.environ.get("ASSISTANT_STORAGE_DIR", "./storage")
DOCS_DIR = os.environ.get("ASSISTANT_DOCS_DIR", "./docs")

# Persistent chat history storage file
CHAT_HISTORY_FILE = os.path.join(STORAGE_DIR, "chat_history.json")

# How much context to feed to the model (approx user turns, not disk storage)
MAX_HISTORY_TURNS = 20  # number of user turns to retain in *model* context

# How many full conversations to persist on disk
MAX_CONVERSATIONS = 20  # keep last 20 full chats (for future UI)

# Simple notes storage (for "remember this" / "note to self")
NOTES_FILE = os.path.join(STORAGE_DIR, "notes.jsonl")

os.makedirs(STORAGE_DIR, exist_ok=True)

SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".pdf",
    ".pptx",
    ".docx",
    ".csv",
    ".py",
    ".html",
}
