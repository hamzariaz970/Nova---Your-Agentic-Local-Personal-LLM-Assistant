# LocalAssistant

LocalAssistant is a fully **local** personal AI assistant:

* 💬 Chat with a **local LLM** (via [Ollama](https://ollama.com))
* 📄 Ask questions about your **local documents** using a simple RAG (Retrieval-Augmented Generation) pipeline
* ✅ Manage **tasks** and **notes**
* 🧠 **Everything runs on your own machine** by default — no remote API calls unless you explicitly enable them
* 🔌 (Optional) Use **web search**, **Gmail**, and **Google Calendar** tools, all controlled via Settings so you decide exactly what information goes in and out
* 🧩 The model **understands context**, decides whether it needs tools, and then chooses the appropriate tool(s) automatically

Tech stack:

* Backend: **FastAPI**
* Frontend: **Vanilla HTML/CSS/JS** (served by FastAPI)
* LLM & embeddings: **Ollama**

---

## 1. Prerequisites

You’ll need:

1. **Python** ≥ 3.10

2. **Ollama** installed and running

   * Download from: [https://ollama.com](https://ollama.com)
   * After installation, confirm it works:

     ```bash
     ollama --version
     ```

3. (Optional but recommended) **Git** to clone the repository

---

## 2. Get the Code

### 2.1 Clone via Git

```bash
git clone <YOUR_REPO_URL> local-assistant
cd local-assistant
```

### 2.2 Or download as ZIP

* Download the repo as a ZIP from your hosting platform (e.g., GitHub).
* Extract it.
* Open the extracted `local-assistant` folder in your terminal / PowerShell.

---

## 3. Create & Activate a Virtual Environment

> Run these commands **inside** the `local-assistant` folder.

### 3.1 macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3.2 Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

If activation succeeds, your prompt should start with `(.venv)`.

---

## 4. Install Python Dependencies

With the virtual environment **activated**:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Your `requirements.txt` should include entries like (adjust to match your project):

```text
fastapi
uvicorn[standard]
jinja2
httpx
python-multipart
python-dotenv
numpy
pandas
pdfplumber
pypdf
tqdm
requests
```

…and any other libraries used in your tools / RAG pipeline.

---

## 5. Set Up Ollama (LLM + Embeddings)

### 5.1 Make sure the Ollama server is running

On **macOS** / **Windows**, opening the Ollama app usually starts the background server.
On **Linux**, follow the Ollama installation instructions.

Check that it’s running:

```bash
ollama list
```

If this runs without error, the server is up.

### 5.2 Pull the main LLM model

Pick a small, fast model (or use the one referenced in your `config.py`):

Example:

```bash
ollama pull qwen3:4b
```

Then, in your `config.py` or `.env`, set:

```python
LLM_MODEL = "qwen3:4b"
```

(or whatever model name you are actually using).

### 5.3 Pull the embedding model

For RAG (document search), pull a text embedding model, e.g.:

```bash
ollama pull mxbai-embed-large
```

And configure it in your code:

```python
EMBEDDING_MODEL = "mxbai-embed-large"
```

If your project uses different names (e.g., `"mxbai-embed-large"`), run `ollama pull` for that exact name instead.

### 5.4 (Optional) Custom Ollama URL

If your Ollama server is not on the default `http://127.0.0.1:11434`:

* Set `OLLAMA_BASE_URL` in `.env` and/or `config.py`.
* Ensure `llm_client.py` reads this value when creating the HTTP client.

---

## 6. Configuration

You may have a `.env` file and/or a `config.py` file, for example:

```bash
# .env (example)
LLM_MODEL=qwen3:4b
EMBEDDING_MODEL=mxbai-embed-large
```

```python
# config.py (example)
LLM_MODEL = "qwen3:4b"
EMBEDDING_MODEL = "mxbai-embed-large"

MAX_HISTORY_TURNS = 20            # Max turns shown per chat
MAX_CONVERSATIONS = 20            # Max chats stored in history
CHAT_HISTORY_FILE = "static/storage/chat_history.json"
FEATURE_FLAGS_FILE = "static/storage/feature_flags.json"
TASKS_FILE = "static/storage/tasks.json"
NOTES_FILE = "static/storage/notes.jsonl"
EMBEDDINGS_FILE = "static/storage/embeddings.npy"
METADATA_FILE = "static/storage/metadata.json"
```

Adjust:

* Model names (`LLM_MODEL`, `EMBEDDING_MODEL`)
* Paths (storage files under `static/storage/`)
* Limits (`MAX_HISTORY_TURNS`, `MAX_CONVERSATIONS`)

to fit your needs.

---

## 7. (Optional) Ingest Documents for RAG

If your project includes `rag_ingest.py` and a vector store (`store.py` / `SimpleVectorStore`), you can index your own documents.

1. Create a folder for your docs, e.g.:

   ```text
   local-assistant/
   ├─ docs/
   │  ├─ file1.pdf
   │  ├─ notes.txt
   │  └─ ...
   ```

2. Run the ingestion script:

   ```bash
   python rag_ingest.py ./docs
   ```

This will:

* Read all supported documents under `./docs`
* Use `EMBEDDING_MODEL` (via Ollama) to create embeddings
* Store them in your local vector store (typically as `static/storage/embeddings.npy` + `static/storage/metadata.json`)

After this, the `search_documents` tool can answer questions using your own files as context.

---

## 8. Run the App

With the virtual environment activated **and** Ollama running:

```bash
uvicorn web_app:app --reload
```

* `web_app` is the file that defines `app = FastAPI(...)`.
* `--reload` restarts the server automatically when you edit Python files (useful during development).

By default, the app runs at:
👉 [http://127.0.0.1:8000](http://127.0.0.1:8000)

Open this URL in your browser.

---

## 9. Using LocalAssistant

### 9.1 Chat (Main Panel)

* Type your message and click **Send**.
* A **loading / thinking animation** appears while the backend:

  * Sends your message (plus the recent conversation history) to the Agent
  * Lets the Agent interpret the context and decide whether tools are needed
  * If necessary, calls one or more tools, then calls the local LLM via Ollama

The model uses the **full conversation context** (within your configured history limits) to:

* Understand what you’re asking
* Decide if it should stay as a pure chat
* Or call tools like RAG search, tasks, notes, web search, Gmail, or Google Calendar

Each full multi-turn back-and-forth with the assistant is treated as **one chat**.

### 9.2 Conversation History (Left Sidebar)

* Each full conversation (many turns) = **one chat**.
* After your **first** user message in a new conversation, the LLM generates a **title** for that chat.
* Up to the **20 most recent** chats are stored in `static/storage/chat_history.json` and shown in the left sidebar.
* Click a chat in the sidebar to load its full history back into the main panel.

### 9.3 Tasks & Notes (Workspace Sidebar)

Depending on your `tools.py`, the Agent can:

* Create, list, update, and complete tasks
* Save and list notes
* Persist tasks and notes to local storage (e.g., `static/storage/tasks.json`, `static/storage/notes.jsonl`)

Typical flow:

1. You ask something like:

   > “Create a task to review my networking slides tomorrow.”

2. The Agent:

   * Converts this into a structured tool call (JSON arguments)
   * Calls the appropriate task tool
   * Returns a natural language confirmation, e.g.:

     > “I’ve added a task: *Review networking slides* for tomorrow.”

Tasks and notes are visible in the **Tasks** and **Notes** views of the workspace sidebar in the UI.

### 9.4 Local Document Q&A (RAG)

When you ask something like:

> “Summarize the main points from the networking slides.”

The Agent can:

1. Call a `search_documents` tool with your query.
2. Retrieve the top-k chunks from your vector store.
3. Include those chunks as context in the next LLM call.
4. Return a grounded answer that references your local files.

All of this runs **locally**:

* Embeddings are generated with the local Ollama embedding model.
* Vector search uses your `SimpleVectorStore`.
* No remote servers are contacted unless you explicitly enable them.

### 9.5 Optional Tools & Settings (Web Search, Gmail, Google Calendar, Shell)

LocalAssistant supports optional tools like:

* **Web search** (via a configured search API)
* **Gmail** (read-only access to your emails via `gmail_client.py`)
* **Google Calendar** (read-only access to your events via `calendar_client.py`)
* **HTTP GET** requests
* **Shell commands** (for simple local automation)

These are controlled by a **Settings** system (via `settings.py` and `static/storage/feature_flags.json`), exposed in the UI:

* You can enable/disable flags such as:

  * `use_web_search`
  * `use_gmail`
  * `use_gcal`
  * `use_http`
  * `use_shell`
  * and any other flags you define

This lets you control **exactly** what information is allowed to leave your machine:

* With all these toggles **off**, the assistant is fully local.
* When you turn a feature **on**, only the necessary information for that specific tool is sent:

  * Web search: your search query
  * Gmail: the specific search terms and messages being retrieved
  * Google Calendar: time ranges and query terms for events

Gmail and Calendar use OAuth credentials stored in:

* `static/storage/google_oauth_client.json` – your Google client credentials
* `static/storage/google_token.json` – the OAuth token generated after you sign in

The Agent always uses the **current context** plus your **Settings** to decide whether using these tools is appropriate before sending any request.

You can keep everything strictly offline by leaving web search, Gmail, Google Calendar, and HTTP tools disabled.

---

## 10. Project Structure

Current repository layout:

```text
local-assistant/
├─ docs/                          # Source documents for RAG (you add these)
├─ static/
│  ├─ css/
│  │  └─ style.css                # Dark theme, responsive 3-column layout
│  ├─ js/
│  │  └─ app.js                   # Frontend logic (chat, sidebar, loading spinner, API calls, settings UI)
│  └─ storage/                    # Local storage (all JSON/NPY files)
│     ├─ chat_history.json        # Multi-chat history (up to MAX_CONVERSATIONS)
│     ├─ embeddings.npy           # Vector store embeddings
│     ├─ feature_flags.json       # Settings toggles (web search, Gmail, GCal, shell, etc.)
│     ├─ google_oauth_client.json # Gmail/Calendar OAuth client credentials
│     ├─ google_token.json        # Gmail/Calendar OAuth token
│     ├─ metadata.json            # Vector store metadata for documents
│     ├─ notes.jsonl              # Saved notes
│     └─ tasks.json               # Saved tasks
├─ templates/
│  └─ index.html                  # Main HTML template (Jinja2) rendered by FastAPI
├─ agent.py                       # Agent: tool-calling, chat history handling, multi-conversation logic
├─ assistant.py                   # Main assistant orchestration (current version)
├─ assistant_og.py                # Older / reference assistant implementation
├─ calendar_client.py             # Google Calendar client (read-only events)
├─ config.py                      # Configuration (models, storage paths, history & conversation limits)
├─ gmail_client.py                # Gmail client (read-only email access)
├─ google_auth_helper.py          # Helper functions for Google OAuth flows
├─ llm_client.py                  # Ollama client wrapper (chat + embeddings)
├─ prompts.py                     # System prompt and template strings for the Agent
├─ rag_ingest.py                  # Script to index docs into the vector store
├─ README.md                      # This file
├─ requirements.txt               # Python dependencies
├─ settings.py                    # SettingsManager & feature flag handling
├─ store.py                       # SimpleVectorStore implementation (search, save, load)
├─ tasks_notes.py                 # TaskManager + low-level note storage helpers
├─ test.py                        # Simple test / playground script (optional)
├─ tools.py                       # Tool registry (RAG search, tasks, notes, HTTP, shell, Gmail, GCal, web search, etc.)
└─ web_app.py                     # FastAPI entrypoint (app = FastAPI(...))
```

---

## 11. Troubleshooting

### 11.1 Cannot connect to Ollama (`connection refused` / `ECONNREFUSED`)

* Make sure the Ollama app / service is running.

* Confirm with:

  ```bash
  ollama list
  ```

* If this fails, reinstall or restart Ollama.

* If you use a non-default URL, verify `OLLAMA_BASE_URL` in `.env` / `config.py` and in `llm_client.py`.

### 11.2 `model not found` from Ollama

If your config says:

```python
LLM_MODEL = "qwen2.5:3b"
```

then you must run:

```bash
ollama pull qwen2.5:3b
```

Similarly, if:

```python
EMBEDDING_MODEL = "mxbai-embed-large"
```

then:

```bash
ollama pull mxbai-embed-large
```

> The model name in code and the one you `ollama pull` **must match exactly**.

### 11.3 `ModuleNotFoundError` (missing Python packages)

* Ensure the virtualenv is activated (`(.venv)` in your prompt).

* Run:

  ```bash
  pip install -r requirements.txt
  ```

* If you add new imports later, add them to `requirements.txt` and reinstall.

### 11.4 UI Not Updating / No Response

* Check the terminal where `uvicorn` is running for error traces.
* Common issues:

  * JSON serialization errors in tools
  * Exceptions inside tool functions in `tools.py`
* Fix the error, save the file, and `uvicorn --reload` will restart the server automatically.

---

## 12. Stopping the App

* Stop the server: press `CTRL + C` in the terminal / PowerShell where `uvicorn` is running.
* Deactivate the virtual environment:

  * macOS / Linux:

    ```bash
    deactivate
    ```

  * Windows (PowerShell/CMD):

    ```powershell
    deactivate
    ```

---

## 13. Security & Privacy

* All **LLM calls**, **embeddings**, and **document processing** run **locally** through Ollama.
* Your chat history, tasks, notes, and vector store are stored under the local storage folder (by default `static/storage/`).
* By default (with web search / Gmail / Google Calendar / HTTP tools disabled), **no data leaves your machine**.
* When you choose to enable web search, Gmail, or Google Calendar:

  * Only the **minimal necessary context** for that tool is sent (e.g., query text, time window, search terms).
  * You control this via Settings, and you can disable any remote feature at any time.
* The Agent always:

  * Reads the current conversation context
  * Respects your Settings
  * Decides whether a tool is needed **before** sending any external request

This gives you fine-grained control over what information goes in and out of your system.

---

## 14. Authors

Created by:

* **Hamza Riaz (414577)**
* **Qurratulain Zafar (412655)**

**National University of Sciences and Technology (NUST)**
School of Electrical Engineering and Computer Science (SEECS), Pakistan
