import os
from typing import List, Dict, Any, Optional
import shutil
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Body, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import STORAGE_DIR, DOCS_DIR
from llm_client import OllamaClient
from store import SimpleVectorStore
from rag_ingest import ingest_folder_to_store
from tasks_notes import TaskManager, _load_notes_raw
from tools import AgentContext, register_tools, tool_save_note
from agent import Agent
from settings import SettingsManager

from prompts import DEFAULT_SYSTEM_PROMPT
from tools import AgentContext, register_tools, build_tools_description, tool_save_note

# -----------------------------
# System prompt (static for web app)
# -----------------------------

# Build a unified system prompt with tool descriptions
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT.format(
    tools_description=build_tools_description()
)


# -----------------------------
# FastAPI app setup
# -----------------------------

app = FastAPI(title="LocalAssistant Web UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # you can tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


# -----------------------------
# Global runtime objects
# -----------------------------

# Register tools once at startup
register_tools()

# LLM + vector store + task manager + settings
_llm = OllamaClient(system_prompt=SYSTEM_PROMPT)
_store = SimpleVectorStore(STORAGE_DIR)
_tasks = TaskManager(STORAGE_DIR)
_settings = SettingsManager(STORAGE_DIR)

ctx = AgentContext(llm=_llm, store=_store, tasks=_tasks, settings=_settings)
agent = Agent(ctx)  # this manages conversations and full history

def _collect_rag_indexed_files() -> List[Dict[str, Any]]:
    """
    Group chunks in the vector store by source_path to show
    a list of 'files' in the UI.
    """
    metadata = getattr(_store, "metadata", []) or []
    files_map: Dict[str, int] = {}

    for m in metadata:
        src = m.get("source_path")
        if not isinstance(src, str):
            continue
        src_abs = os.path.abspath(src)
        files_map[src_abs] = files_map.get(src_abs, 0) + 1

    docs_dir_abs = os.path.abspath(DOCS_DIR)
    result: List[Dict[str, Any]] = []

    for idx, (src_abs, num_chunks) in enumerate(sorted(files_map.items(), key=lambda x: x[0])):
        # Nice display name
        if src_abs.startswith(docs_dir_abs):
            name = os.path.relpath(src_abs, docs_dir_abs)
        else:
            name = os.path.basename(src_abs)

        result.append(
            {
                "id": idx,
                "source_path": src_abs,
                "name": name,
                "num_chunks": num_chunks,
            }
        )

    return result


# -----------------------------
# Pydantic models
# -----------------------------

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None  # currently agent always uses its active conversation


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    conversation_title: Optional[str] = None
    messages: List[Dict[str, Any]]

class NewConversationRequest(BaseModel):
    title: Optional[str] = None


class NewConversationResponse(BaseModel):
    id: str
    title: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    due_date: Optional[str] = None
    priority: Optional[str] = "medium"
    tags: Optional[List[str]] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    completed: Optional[bool] = None



class NoteCreate(BaseModel):
    title: Optional[str] = None
    content: str
    tags: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    use_web_search: Optional[bool] = None
    use_gmail: Optional[bool] = None
    use_calendar: Optional[bool] = None
    use_shell: Optional[bool] = None


# -----------------------------
# Routes: HTML
# -----------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Serve the main HTML UI.
    """
    return templates.TemplateResponse("index.html", {"request": request})


# -----------------------------
# Routes: Chat & conversations
# -----------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    """
    Send a message to the agent and get a reply.

    - If conversation_id is provided, the message is appended to that conversation.
    - If omitted, the agent's currently active conversation is used.
    """
    # Switch active conversation if needed
    if req.conversation_id and req.conversation_id != agent.conversation_id:
        ok = agent.set_active_conversation(req.conversation_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Conversation not found")

    reply = agent.handle_user_message(req.message)

    conv = agent.get_conversation(agent.conversation_id)
    title = conv.get("title") if conv else ""

    return ChatResponse(
        reply=reply,
        conversation_id=agent.conversation_id,
        conversation_title=title,
        messages=agent.full_history,
    )

@app.post("/api/conversations", response_model=NewConversationResponse)
async def create_conversation(
    body: Optional[NewConversationRequest] = Body(default=None)
):
    """
    Create a brand-new conversation and set it as active.
    The body is optional; if omitted, we create an untitled chat.
    """
    title = ""
    if body and body.title:
        title = body.title

    conv_id = agent.new_conversation(title=title)
    conv = agent.get_conversation(conv_id)

    conv_title = (conv.get("title") or title) if conv else title

    return NewConversationResponse(
        id=conv_id,
        title=conv_title,
    )



@app.get("/api/conversations")
async def list_conversations():
    """
    Return a summary list of saved conversations.
    """
    convs = sorted(
        agent._conversations,
        key=lambda c: c.get("updated_at") or c.get("created_at") or "",
        reverse=True,  # newest first
    )
    result = [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
        }
        for c in convs
    ]
    return {"conversations": result}



@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """
    Get full messages for a single conversation (for display in the UI).
    """
    for c in agent._conversations:
        if c.get("id") == conversation_id:
            return {
                "id": c.get("id"),
                "title": c.get("title"),
                "messages": c.get("messages", []),
            }
    raise HTTPException(status_code=404, detail="Conversation not found")

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_route(conversation_id: str):
    """
    Delete a conversation.

    - If the active conversation is deleted, the Agent will:
        * switch to the most recently updated conversation, or
        * create a fresh empty one if none remain.
    """
    deleted = agent.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # After deletion, there is always an active conversation
    conv = agent.get_conversation(agent.conversation_id)
    title = conv.get("title") if conv else ""

    return {
        "ok": True,
        "active_conversation_id": agent.conversation_id,
        "active_conversation_title": title,
    }


# -----------------------------
# Routes: Tasks
# -----------------------------

@app.get("/api/tasks")
async def api_list_tasks(status: str = "open"):
    """
    List tasks. status can be 'open', 'completed', or 'all'.
    """
    tasks = _tasks.list_tasks(status=status)
    return {"tasks": tasks}


@app.get("/api/tasks/completed")
async def api_list_completed_tasks():
    """
    List completed tasks.
    """
    tasks = _tasks.list_tasks(status="completed")
    return {"tasks": tasks}


@app.post("/api/tasks")
async def api_create_task(task: TaskCreate):
    """
    Create a new task (used by the Tasks overlay UI).
    """
    created = _tasks.add_task(
        title=task.title,
        due_date=task.due_date,
        priority=task.priority or "medium",
        tags=task.tags or [],
    )
    return {"task": created, "tasks": _tasks.list_tasks(status="all")}


@app.patch("/api/tasks/{task_id}")
async def api_update_task(task_id: str, update: TaskUpdate):
    """
    Update a task — supports changing title, due_date, priority, tags,
    and completion status.
    """
    patch = {k: v for k, v in update.dict().items() if v is not None}
    if not patch:
        return {"ok": True, "task": None, "tasks": _tasks.list_tasks(status="all")}

    updated = _tasks.update_task(task_id, **patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"ok": True, "task": updated, "tasks": _tasks.list_tasks(status="all")}


@app.delete("/api/tasks/{task_id}")
async def api_delete_task(task_id: str):
    """
    Delete a task completely.
    """
    ok = _tasks.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True, "tasks": _tasks.list_tasks(status="all")}


# -----------------------------
# Routes: Notes
# -----------------------------

@app.get("/api/notes")
async def api_list_notes(limit: int = 50):
    """
    List recent saved notes.
    """
    notes = _load_notes_raw(limit=limit)
    return {"notes": notes}


@app.post("/api/notes")
async def api_create_note(note: NoteCreate):
    """
    Create a new note (and index it into the vector store).
    """
    res = tool_save_note(
        {
            "title": note.title,
            "content": note.content,
            "tags": note.tags or [],
        },
        ctx,
    )
    return res

@app.get("/api/history")
async def api_history():
    """
    Return the full message history for the active conversation.
    Used by the UI to load past messages on page load.
    """
    conv = agent.get_conversation(agent.conversation_id)
    title = conv.get("title") if conv else ""
    return {
        "conversation_id": agent.conversation_id,
        "title": title,
        "messages": agent.full_history,
    }


# -----------------------------
# Routes: RAG files (upload / list / delete)
# -----------------------------

@app.get("/api/rag/files")
async def api_rag_list_files():
    """
    Return a summary of currently indexed RAG files,
    grouped by source_path.
    """
    files = _collect_rag_indexed_files()
    return {"files": files}

@app.post("/api/rag/upload")
async def api_rag_upload_files(files: List[UploadFile] = File(...)):
    """
    Upload new files into DOCS_DIR and index them into the vector store
    using the existing rag_ingest pipeline.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    docs_dir = Path(DOCS_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: List[str] = []

    for uploaded in files:
        if not uploaded.filename:
            continue

        dest = docs_dir / uploaded.filename

        # Save file to disk in chunks
        with dest.open("wb") as out_f:
            while True:
                chunk = await uploaded.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)

        await uploaded.close()
        saved_paths.append(os.path.abspath(str(dest)))

    if not saved_paths:
        raise HTTPException(status_code=400, detail="No valid files uploaded")

    # Use your existing ingestion pipeline:
    # - respects SUPPORTED_TEXT_EXTENSIONS
    # - uses load_text_from_file / sentence-aware split_text
    # - uses store.add_documents(...) and store.metadata
    ingest_folder_to_store(
        folder=DOCS_DIR,
        store=_store,
        chunk_size=500,
        overlap=100,
        force_reindex=False,  # only index new or changed files
    )

    return {"status": "ok", "saved": saved_paths, "files": _collect_rag_indexed_files()}


@app.delete("/api/rag/files/{file_id}")
async def api_rag_delete_file(file_id: int):
    """
    Delete a single file from:
    - the vector store (all chunks with that source_path)
    - the docs directory on disk (if present)
    """
    files = _collect_rag_indexed_files()

    if file_id < 0 or file_id >= len(files):
        raise HTTPException(status_code=404, detail="File not found")

    entry = files[file_id]
    src_abs = entry["source_path"]

    # Remove chunks from the vector store using the same prefix method
    if hasattr(_store, "remove_by_source_prefix"):
        _store.remove_by_source_prefix(src_abs)
    else:
        raise HTTPException(
            status_code=500,
            detail="Vector store does not support removal by source prefix",
        )

    # Also try to remove the physical file from disk
    try:
        p = Path(src_abs)
        if p.is_file():
            p.unlink()
    except Exception:
        # Don't crash if file is locked / already gone
        pass

    return {
        "status": "ok",
        "deleted": src_abs,
        "files": _collect_rag_indexed_files(),
    }



# -----------------------------
# Routes: Settings / API toggles
# -----------------------------

@app.get("/api/settings")
async def get_settings():
    """
    Return current feature/API toggles.
    """
    return {"settings": _settings.get_settings()}


@app.post("/api/settings")
async def update_settings(update: SettingsUpdate):
    """
    Update feature/API toggles (e.g., whether http/web, Gmail, calendar, shell are allowed).
    """
    new_settings = _settings.update_settings(
        {k: v for k, v in update.dict().items() if v is not None}
    )
    return {"settings": new_settings}
