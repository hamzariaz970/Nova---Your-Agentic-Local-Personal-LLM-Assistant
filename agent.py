import os
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import CHAT_HISTORY_FILE, MAX_HISTORY_TURNS, MAX_CONVERSATIONS
from tools import AgentContext, TOOLS


def try_parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to parse a tool call of the form:
      {"tool": "...", "arguments": {...}}
    from the model's raw text output.
    """
    text = text.strip()
    if not text:
        return None

    # Must start with { and end with }, otherwise try to extract first {...} block
    if not (text.startswith("{") and text.endswith("}")):
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        text = text[first:last + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and "tool" in data and "arguments" in data:
        return data
    return None


class Agent:
    """
    Agent wrapper around the LLM + tools, with support for:

    - Multiple conversations stored in a single JSON file.
    - Full history persisted on disk.
    - Trimmed history window used as model context.
    """

    def __init__(self, context: AgentContext):
        self.ctx = context

        # All conversations loaded from disk
        self._conversations: List[Dict[str, Any]] = self._load_conversations()

        # Active conversation state
        self.conversation_id: str
        self.created_at: str
        self.full_history: List[Dict[str, str]] = []   # all messages
        self.history: List[Dict[str, str]] = []        # trimmed for model

        # Fresh conversation
        self.conversation_id = str(uuid.uuid4())
        self.created_at = datetime.utcnow().isoformat()
        self.full_history = []

        # Build trimmed view for the model
        self._update_runtime_history()

    # ------------------------------------------------------------------
    # Conversation persistence helpers
    # ------------------------------------------------------------------

    def _load_conversations(self) -> List[Dict[str, Any]]:
        """
        Load conversations from CHAT_HISTORY_FILE.

        New format:
        {
          "conversations": [
            {
              "id": ...,
              "created_at": ...,
              "updated_at": ...,
              "title": ...,
              "messages": [ {role, content}, ... ]
            },
            ...
          ]
        }

        If a legacy flat list of messages is detected, wrap it into
        a single conversation.
        """
        if not os.path.exists(CHAT_HISTORY_FILE):
            return []

        try:
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        # New format
        if isinstance(data, dict) and isinstance(data.get("conversations"), list):
            return data["conversations"]

        # Legacy format: list of messages
        if isinstance(data, list):
            now = datetime.utcnow().isoformat()
            return [{
                "id": str(uuid.uuid4()),
                "created_at": now,
                "updated_at": now,
                "title": "Legacy conversation",
                "messages": data,
            }]

        return []

    @staticmethod
    def _get_latest_conversation(conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Return the conversation with the latest updated_at (or created_at).
        """
        def sort_key(c: Dict[str, Any]):
            return c.get("updated_at") or c.get("created_at") or ""
        conversations_sorted = sorted(conversations, key=sort_key)
        return conversations_sorted[-1]

    def _update_runtime_history(self) -> None:
        """
        Trim full_history to a smaller window for sending to the model.
        We keep the full conversation on disk but only pass a bounded
        context window to the LLM.
        """
        max_msgs = MAX_HISTORY_TURNS * 4  # heuristic: ~4 messages per turn
        if max_msgs <= 0:
            self.history = list(self.full_history)
        else:
            self.history = self.full_history[-max_msgs:]

    def _save_history(self) -> None:
        """
        Persist the current conversation into the conversations file,
        keeping at most MAX_CONVERSATIONS conversations (by updated_at).
        """
        now = datetime.utcnow().isoformat()

        # Find existing conversation or create a new one
        conv = None
        for c in self._conversations:
            if c.get("id") == self.conversation_id:
                conv = c
                break

        if conv is None:
            conv = {
                "id": self.conversation_id,
                "created_at": self.created_at,
                "updated_at": now,
                "title": "",
                "messages": self.full_history,
            }
            self._conversations.append(conv)
        else:
            conv["messages"] = self.full_history
            conv.setdefault("created_at", self.created_at)
            conv["updated_at"] = now

        # Generate a title once we have enough context
        if not conv.get("title"):
            new_title = self._maybe_generate_title()
            if new_title:
                conv["title"] = new_title

        # Enforce MAX_CONVERSATIONS (keep only the most recent N conversations).
        def sort_key(c: Dict[str, Any]):
            return c.get("updated_at") or c.get("created_at") or ""

        conversations_sorted = sorted(self._conversations, key=sort_key)

        # If MAX_CONVERSATIONS <= 0, keep everything (no trimming)
        if MAX_CONVERSATIONS and MAX_CONVERSATIONS > 0:
            self._conversations = conversations_sorted[-MAX_CONVERSATIONS:]
        else:
            self._conversations = conversations_sorted
        
        # Save to disk
        try:
            with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"conversations": self._conversations}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass


    def _maybe_generate_title(self) -> Optional[str]:
        """
        Use the LLM to generate a short, human-friendly title for the
        active conversation based on the first few user messages.

        Called from _save_history once per conversation (while the title is empty).
        Returns None if there's not enough information yet or if the LLM call fails.
        """
        # Collect first few user messages
        user_msgs = [m.get("content", "") for m in self.full_history if m.get("role") == "user"]
        if not user_msgs:
            return None

        # Avoid titling a chat that's just "hi" etc.
        joined = "\n".join(user_msgs[:3]).strip()
        if len(joined) < 20 and len(user_msgs) < 2:
            # Too little signal; wait for more conversation
            return None

        preview = joined[:400]

        system = (
            "You are naming chats in a personal assistant UI.\n"
            "Based on the user's initial messages, generate a very short, specific title.\n"
            "- Maximum 6–7 words.\n"
            "- No quotation marks, no emojis.\n"
            "- Start with a capital letter.\n"
            "- Return ONLY the title text."
        )
        user = f"User's initial messages:\n{preview}\n\nChat title:"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            raw = self.ctx.llm._post_chat(messages, temperature=0.2)
        except Exception:
            return None

        title = (raw or "").strip().split("\n")[0]

        # Strip wrapping quotes if the model added them
        if (title.startswith('"') and title.endswith('"')) or (title.startswith("'") and title.endswith("'")):
            title = title[1:-1].strip()

        if not title:
            return None
        if len(title) > 80:
            title = title[:77] + "..."
        return title


    # ------------------------------------------------------------------
    # Public conversation management API (for your future UI)
    # ------------------------------------------------------------------

    def list_conversations(self) -> List[Dict[str, Any]]:
        """
        Return a lightweight list of conversations (without full messages),
        suitable for showing in a sidebar UI.
        """
        out: List[Dict[str, Any]] = []
        for c in self._conversations:
            out.append({
                "id": c.get("id"),
                "title": c.get("title") or "",
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "num_messages": len(c.get("messages", [])),
            })
        return out

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Return the full conversation dict (including messages) by id.
        """
        for c in self._conversations:
            if c.get("id") == conversation_id:
                return c
        return None
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation by id.

        - Removes it from self._conversations.
        - If the deleted one was active:
            * If others exist, switch to the most recently updated conversation.
            * If none exist, create a brand-new empty conversation.
        - Persists the updated conversation list to disk.
        """
        # Find conversation index
        idx_to_delete = None
        for idx, c in enumerate(self._conversations):
            if c.get("id") == conversation_id:
                idx_to_delete = idx
                break

        if idx_to_delete is None:
            return False

        # Remove it
        del self._conversations[idx_to_delete]

        # If we just deleted the active conversation, choose a new one
        if self.conversation_id == conversation_id:
            if self._conversations:
                # Pick most recently updated or created
                new_conv = self._get_latest_conversation(self._conversations)
                self.conversation_id = new_conv.get("id", str(uuid.uuid4()))
                self.created_at = new_conv.get("created_at", datetime.utcnow().isoformat())
                self.full_history = new_conv.get("messages", [])
                self._update_runtime_history()
            else:
                # No conversations left → create a fresh one in memory
                now = datetime.utcnow().isoformat()
                new_id = str(uuid.uuid4())
                new_conv = {
                    "id": new_id,
                    "created_at": now,
                    "updated_at": now,
                    "title": "",
                    "messages": [],
                }
                self._conversations.append(new_conv)
                self.conversation_id = new_id
                self.created_at = now
                self.full_history = []
                self._update_runtime_history()

        # Persist everything
        self._save_history()
        return True


    def set_active_conversation(self, conversation_id: str) -> bool:
        """
        Switch the agent to another existing conversation.
        Returns True if the id was found and switched.
        """
        conv = self.get_conversation(conversation_id)
        if conv is None:
            return False

        self.conversation_id = conv.get("id", conversation_id)
        self.created_at = conv.get("created_at", datetime.utcnow().isoformat())
        self.full_history = conv.get("messages", [])
        self._update_runtime_history()
        return True

    def new_conversation(self, title: str = "") -> str:
        """
        Start a brand-new conversation and set it as active.
        Returns the new conversation id.
        """
        now = datetime.utcnow().isoformat()
        conv_id = str(uuid.uuid4())
        new_conv = {
            "id": conv_id,
            "created_at": now,
            "updated_at": now,
            "title": title or "",
            "messages": [],
        }
        self._conversations.append(new_conv)

        # Switch state
        self.conversation_id = conv_id
        self.created_at = now
        self.full_history = []
        self._update_runtime_history()
        self._save_history()
        return conv_id

    # ------------------------------------------------------------------
    # Main chat logic
    # ------------------------------------------------------------------

    def handle_user_message(self, user_message: str) -> str:
        """
        Single-step agent:
        1. Ask LLM whether to call a tool or answer directly.
        2. If a tool is called, execute it and then ask the LLM again
           for a final answer, with the tool result included.
        """
        # 1) Ask LLM for either tool call JSON or direct answer
        reply = self.ctx.llm.chat(self.history, user_message)
        tool_call = try_parse_tool_call(reply)

        # ------------------ Direct answer path ------------------
        if tool_call is None:
            # Log full conversation
            self.full_history.append({"role": "user", "content": user_message})
            self.full_history.append({"role": "assistant", "content": reply})

            # Update trimmed history + save
            self._update_runtime_history()
            self._save_history()
            return reply

        # ------------------ Tool call path ------------------
        tool_name = tool_call.get("tool")
        args = tool_call.get("arguments", {})
        tool = TOOLS.get(tool_name)

        if tool is None:
            # Unknown tool -> treat as plain text answer
            self.full_history.append({"role": "user", "content": user_message})
            self.full_history.append({"role": "assistant", "content": reply})
            self._update_runtime_history()
            self._save_history()
            return reply

        # 2) Execute tool
        tool_result = tool.func(args, self.ctx)

        # 3) Log the tool call itself into the conversation
        # (so your future UI can see that a tool was invoked)
        self.full_history.append({"role": "user", "content": user_message})
        self.full_history.append({"role": "assistant", "content": reply})  # JSON tool-call
        self._update_runtime_history()

        # 4) Ask LLM for final answer with tool result in context
        messages_for_final = [
            {"role": "system", "content": self.ctx.llm.system_prompt}
        ] + self.history + [
            {
                "role": "system",
                "content": (
                    "The previous assistant message was a tool call. "
                    "The tool has finished running.\n"
                    f"Here is the TOOL RESULT:\n"
                    f"{json.dumps(tool_result, ensure_ascii=False, indent=2)}\n\n"
                    "Now write a helpful answer to the user's last question, "
                    "using this tool result."
                ),
            }
        ]

        final_text = self.ctx.llm._post_chat(messages_for_final)

        # 5) Log the final natural-language answer
        self.full_history.append({"role": "assistant", "content": final_text})
        self._update_runtime_history()
        self._save_history()

        return final_text
