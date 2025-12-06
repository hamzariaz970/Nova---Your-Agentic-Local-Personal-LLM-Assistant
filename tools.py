import os
import json
import uuid
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Any, Callable, Optional
from datetime import datetime

import requests

import subprocess
import shlex
from llm_client import OllamaClient  # for type hints in AgentContext
from store import SimpleVectorStore
from tasks_notes import TaskManager, _append_note_raw, _load_notes_raw
from settings import SettingsManager


@dataclass
class AgentContext:
    llm: OllamaClient
    store: SimpleVectorStore
    tasks: TaskManager
    settings: SettingsManager



ToolFunc = Callable[[Dict[str, Any], AgentContext], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: ToolFunc


# -------------------------------------------------
# RAG / document search
# -------------------------------------------------

def tool_search_documents(args: Dict[str, Any], ctx: AgentContext):
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    results = ctx.store.search(query, top_k=top_k)
    # Return minimal context for LLM
    return {
        "query": query,
        "results": [
            {
                "source_path": r["source_path"],
                "chunk_index": r["chunk_index"],
                "score": r["score"],
                "text": r["text"],
            }
            for r in results
        ],
    }


# -------------------------------------------------
# Tasks
# -------------------------------------------------

def tool_create_tasks_from_text(args: Dict[str, Any], ctx: AgentContext):
    """
    Flexible task-creation tool.

    Supports TWO calling patterns:

    1) Simple natural-language (what your model is doing now):

       {
         "task_description": "Complete ToA project by today",
         "due_date": "2025-12-06T23:59",
         "priority": "high",
         "tags": ["university", "ToA"]
       }

       => creates ONE task with that description.

    2) Structured list (your original design):

       {
         "tasks": [
           {
             "title": "Finish ToA report",
             "due_date": "2025-12-06",
             "priority": "high",
             "tags": ["university", "ToA"]
           },
           {
             "title": "Email ToA slides to group",
             "due_date": null,
             "priority": "medium",
             "tags": []
           }
         ]
       }

       => creates multiple tasks at once.
    """
    created: List[Dict[str, Any]] = []

    tasks_spec = args.get("tasks")

    # -------------------------
    # Pattern 1: structured list
    # -------------------------
    if isinstance(tasks_spec, list) and tasks_spec:
        for t in tasks_spec:
            title = (t.get("title") or "").strip()
            if not title:
                continue
            due = t.get("due_date")
            priority = t.get("priority", "medium")
            tags = t.get("tags") or []
            created.append(ctx.tasks.add_task(title, due, priority, tags))

        return {"created_tasks": created}

    # -------------------------
    # Pattern 2: single description
    # -------------------------
    description = (args.get("task_description") or "").strip()
    if not description:
        # Nothing useful provided
        return {"created_tasks": []}

    due = args.get("due_date")
    priority = args.get("priority", "medium")
    tags = args.get("tags") or []

    created.append(ctx.tasks.add_task(description, due, priority, tags))
    return {"created_tasks": created}


def tool_list_tasks(args: Dict[str, Any], ctx: AgentContext):
    status = args.get("status", "open")
    time_window_days = args.get("time_window_days")
    if time_window_days is not None:
        try:
            time_window_days = int(time_window_days)
        except ValueError:
            time_window_days = None
    tasks = ctx.tasks.list_tasks(status=status, time_window_days=time_window_days)
    return {"tasks": tasks}


# -------------------------------------------------
# Task update / delete tools
# -------------------------------------------------

def tool_update_task(args: Dict[str, Any], ctx: AgentContext):
    """
    Update a single task's fields given its id.
    Any field omitted from args is left unchanged.
    """
    task_id = args.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    # Only pass through fields that were actually provided
    fields: Dict[str, Any] = {}
    for key in ["title", "due_date", "priority", "tags", "completed"]:
        if key in args:
            fields[key] = args[key]

    updated = ctx.tasks.update_task(task_id, **fields)
    if not updated:
        return {"error": f"Task {task_id} not found"}
    return {"updated_task": updated}


def tool_delete_task(args: Dict[str, Any], ctx: AgentContext):
    """
    Delete a task by id. The LLM MUST only call this
    after confirming with the user in natural language.
    """
    task_id = args.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    # Capture the task before deletion so the LLM can reference what was removed
    all_tasks = ctx.tasks.list_tasks(status="all")
    before = next((t for t in all_tasks if t.get("id") == task_id), None)

    ok = ctx.tasks.delete_task(task_id)
    return {
        "deleted": bool(ok),
        "task_id": task_id,
        "task": before,
    }



# -------------------------------------------------
# File tools
# -------------------------------------------------

def tool_list_files(args: Dict[str, Any], ctx: AgentContext):
    folder = args.get("folder", ".")
    pattern = args.get("pattern", None)
    if not os.path.isdir(folder):
        return {"error": f"{folder} is not a directory"}
    files = []
    for fname in os.listdir(folder):
        path = os.path.join(folder, fname)
        if os.path.isfile(path):
            if pattern and pattern not in fname:
                continue
            files.append({"name": fname, "path": path})
    return {"files": files}


def tool_rename_files_with_prefix(args: Dict[str, Any], ctx: AgentContext):
    folder = args.get("folder", ".")
    prefix = args.get("prefix", "file")
    if not os.path.isdir(folder):
        return {"error": f"{folder} is not a directory"}
    files = sorted(
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f))
    )
    mapping = []
    for i, fname in enumerate(files, start=1):
        ext = os.path.splitext(fname)[1]
        new_name = f"{prefix}_{i:03d}{ext}"
        old_path = os.path.join(folder, fname)
        new_path = os.path.join(folder, new_name)
        os.rename(old_path, new_path)
        mapping.append({"old": fname, "new": new_name})
    return {"renamed": mapping}


# -------------------------------------------------
# PDF tables
# -------------------------------------------------

def tool_extract_tables_from_pdf(args: Dict[str, Any], ctx: AgentContext):
    path = args.get("pdf_path")
    output_csv = args.get("output_csv", None)
    if not path or not os.path.isfile(path):
        return {"error": f"File {path} not found"}
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return {
            "error": "pdfplumber is not installed. Install with `pip install pdfplumber`."
        }
    tables_all = []
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for t in tables:
                tables_all.append({"page": page_num, "table": t})
    if output_csv and tables_all:
        # Save first table to CSV
        import csv
        first = tables_all[0]["table"]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in first:
                writer.writerow(row)
    return {"tables_found": len(tables_all), "sample": tables_all[:1]}


# -------------------------------------------------
# HTTP / shell
# -------------------------------------------------

def tool_http_get(args: Dict[str, Any], ctx: AgentContext):
    """
    Fetch a web page (http/https) and return a truncated text snippet.

    This is only allowed if 'use_web_search' is True in settings.
    """
    import textwrap
    from urllib.parse import urlparse

    # Check toggle
    flags = ctx.settings.get_settings() if hasattr(ctx, "settings") else {}
    if not flags.get("use_web_search", False):
        return {
            "error": "Web access is disabled in settings (use_web_search=false). "
                     "Enable it in the Settings panel if you want to use http_get."
        }

    url = (args.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}

    if len(url) > 512:
        return {"error": "URL is too long; refusing to fetch."}

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"error": "Only absolute http(s) URLs are allowed."}

    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        text = resp.text or ""
        snippet = textwrap.shorten(text, width=4000, placeholder="...")
        return {
            "url": url,
            "status_code": resp.status_code,
            "content_snippet": snippet,
        }
    except Exception as e:
        return {"error": f"Request failed: {e}"}




# -------------------------------------------------
# Notes
# -------------------------------------------------

def tool_save_note(args: Dict[str, Any], ctx: AgentContext):
    """
    Save a free-form note, optionally tagged. Also index it into the vector store
    so it shows up in search_documents.
    """
    title = args.get("title") or "Untitled"
    content = args.get("content") or ""
    tags = args.get("tags") or []

    note = {
        "id": str(uuid.uuid4()),
        "title": title,
        "content": content,
        "tags": tags,
        "created_at": datetime.utcnow().isoformat(),
    }

    # Persist the note
    _append_note_raw(note)

    # Also index into the vector store so RAG can find it
    meta = {
        "id": note["id"],
        "source_path": "note://local",   # synthetic path
        "chunk_index": 0,
        "title": title,
        "tags": tags,
        "text": content,
        "kind": "note",
    }
    try:
        ctx.store.add_documents([content], [meta])
    except ValueError as e:
        # Don't crash the whole app if embeddings are messed up
        return {
            "saved_note": note,
            "warning": f"Note saved, but indexing into the search store failed: {e}"
        }

    return {"saved_note": note}


def tool_list_notes(args: Dict[str, Any], ctx: AgentContext):
    """
    List recent notes so the LLM can summarize or reference them.
    """
    limit = int(args.get("limit", 20))
    notes = _load_notes_raw(limit=limit)
    return {"notes": notes}



def tool_run_shell_command(args: Dict[str, Any], ctx: AgentContext) -> Dict[str, Any]:
    """
    Run a shell command on the local machine.

    - Only allowed if 'use_shell' is True in settings.
    - Refuses obviously dangerous commands (rm, sudo, shutdown, etc.).
    - Truncates stdout/stderr to avoid flooding context.
    """
    flags = ctx.settings.get_settings() if hasattr(ctx, "settings") else {}
    if not flags.get("use_shell", False):
        return {
            "error": "Shell commands are disabled in settings (use_shell=false). "
                     "Enable them in the Settings panel if you really want this."
        }

    cmd = (args.get("command") or "").strip()
    if not cmd:
        return {"error": "command is required"}

    # Very basic guardrail: refuse obviously destructive commands
    lower_cmd = cmd.lower()
    forbidden_substrings = [
        " rm ", " rm-", " rm/",
        "sudo ", " shutdown", " reboot",
        " mkfs", " fdisk", " mount ", " umount",
        ":(){:|:&};:"  # fork bomb
    ]
    if any(bad in lower_cmd for bad in forbidden_substrings):
        return {"error": "Refusing to run potentially destructive command."}

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=os.getcwd(),  # or set to a safer specific directory if you want
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as e:
        return {"error": f"Command failed to execute: {e}"}

    out = (proc.stdout or "")[-4000:]
    err = (proc.stderr or "")[-2000:]
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": out,
        "stderr": err,
    }

# -------------------------------------------------
# Gmail tools
# -------------------------------------------------

def tool_gmail_list_messages(args: Dict[str, Any], ctx: AgentContext) -> Dict[str, Any]:
    """
    List recent Gmail messages (subject, sender, snippet).

    Only works if 'use_gmail' is True in settings.
    """
    flags = ctx.settings.get_settings() if hasattr(ctx, "settings") else {}
    if not flags.get("use_gmail", False):
        return {
            "error": "Gmail integration is disabled in settings (use_gmail=false). "
                     "Enable it in the Settings panel to use this tool."
        }

    max_results_raw = args.get("max_results", 10)
    try:
        max_results = int(max_results_raw)
    except (TypeError, ValueError):
        max_results = 10

    try:
        from gmail_client import list_recent_messages
    except ImportError as e:
        return {
            "error": f"Gmail client not available: {e}. "
                     "Did you install google-api-python-client and google-auth-oauthlib?"
        }

    try:
        messages = list_recent_messages(max_results=max_results)
        return {"messages": messages}
    except Exception as e:
        return {"error": f"Gmail error: {e}"}


def tool_gmail_search_messages(args: Dict[str, Any], ctx: AgentContext) -> Dict[str, Any]:
    """
    Search Gmail using a Gmail-style query string.
    """
    flags = ctx.settings.get_settings() if hasattr(ctx, "settings") else {}
    if not flags.get("use_gmail", False):
        return {
            "error": "Gmail integration is disabled in settings (use_gmail=false). "
                     "Enable it in the Settings panel to use this tool."
        }

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    max_results_raw = args.get("max_results", 10)
    try:
        max_results = int(max_results_raw)
    except (TypeError, ValueError):
        max_results = 10

    try:
        from gmail_client import search_messages
    except ImportError as e:
        return {
            "error": f"Gmail client not available: {e}. "
                     "Did you install google-api-python-client and google-auth-oauthlib?"
        }

    try:
        messages = search_messages(query=query, max_results=max_results)
        return {"messages": messages}
    except Exception as e:
        return {"error": f"Gmail error: {e}"}


# -------------------------------------------------
# Calendar tools
# -------------------------------------------------
def tool_calendar_upcoming_events(args: Dict[str, Any], ctx: AgentContext) -> Dict[str, Any]:
    """
    List upcoming Calendar events from the user's primary calendar.

    Only works if 'use_calendar' is True in settings.
    """
    flags = ctx.settings.get_settings() if hasattr(ctx, "settings") else {}
    if not flags.get("use_calendar", False):
        return {
            "error": "Calendar integration is disabled in settings (use_calendar=false). "
                     "Enable it in the Settings panel to use this tool."
        }

    days_raw = args.get("days", 7)
    max_results_raw = args.get("max_results", 10)
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = 7
    try:
        max_results = int(max_results_raw)
    except (TypeError, ValueError):
        max_results = 10

    try:
        from calendar_client import list_upcoming_events
    except ImportError as e:
        return {
            "error": f"Calendar client not available: {e}. "
                     "Did you install google-api-python-client and google-auth-oauthlib?"
        }

    try:
        events = list_upcoming_events(max_days=days, max_results=max_results)
        return {"events": events}
    except Exception as e:
        return {"error": f"Calendar error: {e}"}


# -------------------------------------------------
# Registry
# -------------------------------------------------
TOOLS: Dict[str, Tool] = {}


def register_tools():
    """
    Populate the global TOOLS dict in-place so that any modules that did

        from tools import TOOLS

    still see the updated contents.
    """
    # Important: mutate, don't rebind
    TOOLS.clear()

    TOOLS.update({
        "search_documents": Tool(
            name="search_documents",
            description="Search over the user's indexed local documents and notes.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Semantic search query.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "How many results to return.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            func=tool_search_documents,
        ),
        "create_tasks_from_text": Tool(
            name="create_tasks_from_text",
            description=(
                "Turn natural-language instructions into concrete todo items "
                "and save them. Use this after reading chats, emails, or when "
                "the user says things like 'remind me to ...' or "
                "'add a task to ...'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": (
                            "Short natural-language description of the task. "
                            "Example: 'Complete ToA project by today'."
                        ),
                    },
                    "due_date": {
                        "type": ["string", "null"],
                        "description": (
                            "Optional ISO date or datetime for when the task "
                            "is due, e.g. '2025-12-06' or '2025-12-06T18:00'."
                        ),
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "default": "medium",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags like ['university', 'ToA'].",
                    },
                    "tasks": {
                        "type": "array",
                        "description": (
                            "Optional explicit list of tasks. Use this if you "
                            "want to create several distinct tasks at once."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "due_date": {"type": ["string", "null"]},
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": [],
            },
            func=tool_create_tasks_from_text,
        ),
        "list_tasks": Tool(
            name="list_tasks",
            description=(
                "List saved tasks for reviews. Use this for daily/weekly task "
                "reviews or when the user asks 'what do I need to do?'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "completed", "all"],
                        "default": "open",
                    },
                    "time_window_days": {
                        "type": ["integer", "null"],
                        "description": (
                            "If provided, only return tasks due within this "
                            "many days from now."
                        ),
                    },
                },
                "required": [],
            },
            func=tool_list_tasks,
        ),
        "update_task": Tool(
            name="update_task",
            description=(
                "Update an existing task by id. "
                "Use this when the user wants to rename a task, change its due date, "
                "priority, tags, or mark it completed/open without creating a new one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The id of the task to update.",
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "New title for the task.",
                    },
                    "due_date": {
                        "type": ["string", "null"],
                        "description": (
                            "New ISO date/datetime for when the task is due, "
                            "or null to clear it."
                        ),
                    },
                    "priority": {
                        "type": ["string", "null"],
                        "enum": ["low", "medium", "high", None],
                        "description": "Updated priority level.",
                    },
                    "tags": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "Replace the task's tags with this list.",
                    },
                    "completed": {
                        "type": ["boolean", "null"],
                        "description": "Whether the task is completed.",
                    },
                },
                "required": ["task_id"],
            },
            func=tool_update_task,
        ),
        "delete_task": Tool(
            name="delete_task",
            description=(
                "Delete a task by id. "
                "For safety, the assistant should first show the candidate task "
                "and ask for an explicit yes/no confirmation in a previous turn."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The id of the task to delete.",
                    },
                },
                "required": ["task_id"],
            },
            func=tool_delete_task,
        ),
        "list_files": Tool(
            name="list_files",
            description="List files within a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "pattern": {
                        "type": ["string", "null"],
                        "description": "Optional substring to filter filenames.",
                    },
                },
                "required": ["folder"],
            },
            func=tool_list_files,
        ),
        "rename_files_with_prefix": Tool(
            name="rename_files_with_prefix",
            description=(
                "Rename all files in a folder to "
                "prefix_001.ext, prefix_002.ext, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "prefix": {"type": "string"},
                },
                "required": ["folder", "prefix"],
            },
            func=tool_rename_files_with_prefix,
        ),
        "extract_tables_from_pdf": Tool(
            name="extract_tables_from_pdf",
            description=(
                "Extract tables from a PDF and optionally save the first "
                "table to CSV."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string"},
                    "output_csv": {
                        "type": ["string", "null"],
                        "description": (
                            "Optional CSV output path for the first table."
                        ),
                    },
                },
                "required": ["pdf_path"],
            },
            func=tool_extract_tables_from_pdf,
        ),
        "http_get": Tool(
            name="http_get",
            description=(
                "Fetch a web page to check for updates or summarize content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
            func=tool_http_get,
        ),
        "run_shell_command": Tool(
            name="run_shell_command",
            description=(
                "Run a shell command on the local machine. Use sparingly and "
                "never for dangerous operations."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
            func=tool_run_shell_command,
        ),
        "save_note": Tool(
            name="save_note",
            description=(
                "Save a short note or memory the user wants to keep for later. "
                "Use this for 'remember that...' or 'note to self ...'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["content"],
            },
            func=tool_save_note,
        ),
        "list_notes": Tool(
            name="list_notes",
            description=(
                "List recent saved notes so you can summarize or reference them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent notes to return.",
                        "default": 20,
                    },
                },
                "required": [],
            },
            func=tool_list_notes,
        ),
                "gmail_list_messages": Tool(
            name="gmail_list_messages",
            description=(
                "List recent emails from the user's Gmail inbox (subject, sender, date, snippet). "
                "Only works if Gmail integration is enabled in settings."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of messages to return.",
                        "default": 10,
                    },
                },
                "required": [],
            },
            func=tool_gmail_list_messages,
        ),
        "gmail_search_messages": Tool(
            name="gmail_search_messages",
            description=(
                "Search Gmail using a query like 'from:someone subject:report'. "
                "Returns matching messages with subject, sender, date, and snippet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query string.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of messages to return.",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            func=tool_gmail_search_messages,
        ),
        "calendar_upcoming_events": Tool(
        name="calendar_upcoming_events",
        description=(
            "List upcoming events from the user's primary Google Calendar "
            "within the next N days. Only works if Calendar integration "
            "is enabled in settings."
        ),
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days ahead to look for events.",
                    "default": 7,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return.",
                    "default": 10,
                },
            },
            "required": [],
        },
        func=tool_calendar_upcoming_events,
    ),

})

def build_tools_description() -> str:
    lines: List[str] = []
    for name, tool in TOOLS.items():
        lines.append(f"- {name}: {tool.description}")
        lines.append(
            f"  Parameters JSON schema: {json.dumps(tool.parameters)}"
        )
    return "\n".join(lines)
