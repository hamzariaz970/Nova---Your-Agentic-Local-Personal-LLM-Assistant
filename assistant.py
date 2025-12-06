import sys

from config import DOCS_DIR, STORAGE_DIR, LLM_MODEL
from llm_client import OllamaClient
from store import SimpleVectorStore
from tasks_notes import TaskManager
from tools import register_tools, AgentContext, build_tools_description
from rag_ingest import ingest_folder_to_store
from agent import Agent
import prompts


def print_usage():
    print("Usage:")
    print("  python assistant.py index <folder> [--force]  # ingest (optionally reindex) documents into the RAG index")
    print("  python assistant.py chat                     # start interactive chat")


def main():
    # Register tools first so we can build their description
    register_tools()

    # Update system prompt with tools description
    prompts.DEFAULT_SYSTEM_PROMPT = prompts.DEFAULT_SYSTEM_PROMPT.format(
        tools_description=build_tools_description()
    )

    if len(sys.argv) < 2:
        print_usage()
        return

    mode = sys.argv[1]

    if mode == "index":
        # default values
        folder = DOCS_DIR
        force = False

        # parse extra args: folder and/or --force
        extra_args = sys.argv[2:]
        for arg in extra_args:
            if arg == "--force":
                force = True
            else:
                folder = arg

        print(f"[INFO] Using folder: {folder}")
        if force:
            print("[INFO] Force reindex requested.")

        store = SimpleVectorStore(STORAGE_DIR)
        ingest_folder_to_store(folder, store, force_reindex=force)
        return

    if mode == "chat":
        llm = OllamaClient(model=LLM_MODEL, system_prompt=prompts.DEFAULT_SYSTEM_PROMPT)
        store = SimpleVectorStore(STORAGE_DIR)
        tasks = TaskManager(STORAGE_DIR)
        ctx = AgentContext(llm=llm, store=store, tasks=tasks)
        agent = Agent(ctx)

        print("LocalAssistant (Qwen via Ollama). Type 'exit' to quit.")
        while True:
            try:
                user_message = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break
            if not user_message:
                continue
            if user_message.lower() in {"exit", "quit"}:
                print("Goodbye.")
                break
            try:
                reply = agent.handle_user_message(user_message)
                print(f"\nAssistant: {reply}")
            except Exception as e:
                print(f"[ERROR] {e}")
        return

    print_usage()


if __name__ == "__main__":
    main()
