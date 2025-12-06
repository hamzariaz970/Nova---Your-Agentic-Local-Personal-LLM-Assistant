from typing import List, Dict, Any, Optional

import requests
import numpy as np

from config import OLLAMA_BASE_URL, CHAT_ENDPOINT, LLM_MODEL, EMBED_MODEL


class OllamaClient:
    def __init__(self, model: str = LLM_MODEL, system_prompt: Optional[str] = None):
        # Import inside to always see the latest DEFAULT_SYSTEM_PROMPT value
        from prompts import DEFAULT_SYSTEM_PROMPT

        self.model = model
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    def _messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Convert chat-style messages into a single prompt string for /api/generate.
        We keep roles as simple labels so the model can infer the dialogue.
        """
        lines = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                prefix = "System"
            elif role == "assistant":
                prefix = "Assistant"
            else:
                prefix = "User"
            lines.append(f"{prefix}: {m.get('content', '')}")
        # Encourage the model to respond as the assistant
        lines.append("Assistant:")
        return "\n".join(lines)

    def _post_chat(self, messages: List[Dict[str, str]], temperature: float = 0.25) -> str:
        """
        Try Ollama /api/chat first.
        If that endpoint doesn't exist (HTTP 404), fall back to /api/generate.
        """
        # --- Try /api/chat ---
        chat_payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            resp = requests.post(CHAT_ENDPOINT, json=chat_payload, timeout=600)
        except Exception:
            # If something weird happens (e.g., connection error), fall back to /api/generate
            resp = None

        if resp is not None and resp.status_code == 404:
            # This Ollama does not support /api/chat → use /api/generate instead
            resp = None

        if resp is not None:
            # /api/chat exists → normal flow
            resp.raise_for_status()
            data = resp.json()
            if "message" in data:
                return data["message"]["content"]
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            return str(data)

        # --- Fallback: /api/generate ---
        # Separate system messages from user/assistant messages
        system_texts = []
        non_system_msgs: List[Dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                system_texts.append(m.get("content", ""))
            else:
                non_system_msgs.append(m)

        prompt = self._messages_to_prompt(non_system_msgs)
        system_text = "\n".join(system_texts).strip()

        gen_payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if system_text:
            # Newer Ollama supports a separate `system` field; older versions
            # will just ignore unknown keys.
            gen_payload["system"] = system_text

        gen_resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=gen_payload, timeout=600)
        gen_resp.raise_for_status()
        data = gen_resp.json()

        # /api/generate returns `response` as a single string
        if "response" in data:
            return data["response"]
        return str(data)

    def chat(self, history: List[Dict[str, str]], user_message: str, temperature: float = 0.2) -> str:
        # Build messages: system + history + new user
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return self._post_chat(messages, temperature=temperature)


# -----------------------------
# Embeddings via Ollama
# -----------------------------

def embed_texts(texts: List[str], model: str = EMBED_MODEL) -> np.ndarray:
    """
    Generate embeddings for a list of texts using Ollama.

    - For `nomic-embed-text*` we use the legacy /api/embeddings endpoint with "prompt".
    - For all other embedding models we use /api/embed with "input".
    - We surface clear error messages if Ollama returns an error or 4xx/5xx.
    """
    vectors: List[np.ndarray] = []

    for t in texts:
        # Choose endpoint + payload format based on model
        if model.startswith("nomic-embed-text"):
            url = f"{OLLAMA_BASE_URL}/api/embeddings"
            payload = {
                "model": model,
                "prompt": t,  # documented for nomic-embed-text
            }
        else:
            url = f"{OLLAMA_BASE_URL}/api/embed"
            payload = {
                "model": model,
                "input": t,   # documented for /api/embed
            }

        resp = requests.post(url, json=payload, timeout=600)

        # If HTTP error, show body so you can see what Ollama said
        if resp.status_code != 200:
            raise RuntimeError(
                f"Ollama embedding HTTP {resp.status_code} from {url}:\n"
                f"{resp.text[:500]}"
            )

        data = resp.json()

        # Explicit error key from Ollama
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"Ollama embedding error: {data['error']}")

        # /api/embed: {"model": ..., "embeddings": [[...]]}
        if "embeddings" in data:
            emb = data["embeddings"]
            if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                emb_vec = emb[0]
            else:
                emb_vec = emb

        # /api/embeddings (legacy): {"embedding": [...]}
        elif "embedding" in data:
            emb_vec = data["embedding"]

        else:
            raise RuntimeError(f"Unexpected embedding response from Ollama: {data}")

        vectors.append(np.array(emb_vec, dtype=np.float32))

    if not vectors:
        return np.zeros((0, 0), dtype=np.float32)

    return np.vstack(vectors)
