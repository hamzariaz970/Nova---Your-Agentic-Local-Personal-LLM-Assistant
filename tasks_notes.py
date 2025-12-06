import os
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import STORAGE_DIR, NOTES_FILE


# -----------------------------
# Task management
# -----------------------------
class TaskManager:
    def __init__(self, storage_dir: str = STORAGE_DIR):
        self.path = os.path.join(storage_dir, "tasks.json")
        self.tasks: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.tasks = json.load(f)
        else:
            self.tasks = []

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

    def add_task(self, title: str, due_date: Optional[str], priority: str, tags: List[str], source: Optional[str] = None) -> Dict[str, Any]:
        task = {
            "id": str(uuid.uuid4()),
            "title": title,
            "due_date": due_date,  # ISO string or None
            "priority": priority,
            "tags": tags,
            "created_at": datetime.utcnow().isoformat(),
            "completed": False,
            "source": source,
        }
        self.tasks.append(task)
        self._save()
        return task

    def list_tasks(self, status: str = "open", time_window_days: Optional[int] = None) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        result = []
        for t in self.tasks:
            if status == "open" and t.get("completed"):
                continue
            if status == "completed" and not t.get("completed"):
                continue
            if status == "all":
                pass
            if time_window_days is not None and t.get("due_date"):
                try:
                    due = datetime.fromisoformat(t["due_date"])
                    delta = (due - now).days
                    if delta > time_window_days:
                        continue
                except Exception:
                    pass
            result.append(t)
        return result

    def complete_task(self, task_id: str) -> bool:
        for t in self.tasks:
            if t["id"] == task_id:
                t["completed"] = True
                self._save()
                return True
        return False

    

    def delete_task(self, task_id: str) -> bool:
        """ Remove a task entirely from storage. Returns True if something was deleted, False if the id was not found. """
        new_tasks = [t for t in self.tasks if t.get("id") != task_id]
        if len(new_tasks) == len(self.tasks):
            return False
        self.tasks = new_tasks
        self._save()
        return True

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[List[str]] = None,
        completed: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Patch fields on a task. Fields that are None are left unchanged.
        Use due_date=None explicitly to clear the due date.
        Returns the updated task dict, or None if not found.
        """
        for t in self.tasks:
            if t.get("id") == task_id:
                if title is not None:
                    t["title"] = title
                if due_date is not None:
                    t["due_date"] = due_date  # allow setting to None to clear
                if priority is not None:
                    t["priority"] = priority
                if tags is not None:
                    t["tags"] = tags
                if completed is not None:
                    t["completed"] = bool(completed)
                self._save()
                return t
        return None

# -----------------------------
# Notes management
# -----------------------------

def _append_note_raw(note: Dict[str, Any]) -> None:
    os.makedirs(STORAGE_DIR, exist_ok=True)
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")


def _load_notes_raw(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(NOTES_FILE):
        return []
    notes: List[Dict[str, Any]] = []
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except Exception:
                continue
    if limit is not None:
        return notes[-limit:]
    return notes
