import os
import uuid
import zipfile
import xml.etree.ElementTree as ET
import re
from typing import List, Dict, Any

from config import SUPPORTED_TEXT_EXTENSIONS
from store import SimpleVectorStore

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    import docx
except ImportError:
    docx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


# -----------------------------
# Document ingestion (RAG)
# -----------------------------

def load_text_from_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    # Hard gate: only process known "text-like" file types
    if ext not in SUPPORTED_TEXT_EXTENSIONS:
        raise RuntimeError(f"Unsupported file type for RAG: {ext}")

    # --- Plain text & markdown ---
    if ext in {".txt", ".md", ".markdown"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # --- PDF ---
    if ext == ".pdf":
        if PdfReader is None:
            raise RuntimeError("PyPDF2 is not installed. Install with `pip install PyPDF2`.")
        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    # --- Word (.docx) via zipfile ---
    if ext == ".docx":
        texts: List[str] = []
        try:
            with zipfile.ZipFile(path) as z:
                xml_bytes = z.read("word/document.xml")
        except Exception as e:
            raise RuntimeError(f"Failed to read DOCX XML: {e}")

        xml_str = xml_bytes.decode("utf-8", errors="ignore")
        try:
            root = ET.fromstring(xml_str)
        except Exception:
            # fallback: strip tags crudely
            return re.sub(r"<[^>]+>", " ", xml_str)

        # In DOCX, text is mostly in <w:t> tags
        for node in root.iter():
            if node.tag.endswith("}t") and node.text:
                texts.append(node.text)
        return "\n".join(texts)

    # --- PowerPoint (.pptx) via zipfile ---
    if ext == ".pptx":
        all_texts: List[str] = []
        try:
            with zipfile.ZipFile(path) as z:
                slide_names = sorted(
                    name
                    for name in z.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
                for slide_name in slide_names:
                    xml_bytes = z.read(slide_name)
                    xml_str = xml_bytes.decode("utf-8", errors="ignore")
                    try:
                        root = ET.fromstring(xml_str)
                        # In PPTX slides, text is often in <a:t> tags
                        for node in root.iter():
                            if node.tag.endswith("}t") and node.text:
                                all_texts.append(node.text)
                    except Exception:
                        # Fallback: crude tag-strip on this slide
                        all_texts.append(re.sub(r"<[^>]+>", " ", xml_str))
        except Exception as e:
            raise RuntimeError(f"Failed to read PPTX: {e}")

        return "\n".join(all_texts)

    # --- CSV ---
    if ext == ".csv":
        import csv
        rows: List[str] = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                # Join columns with tabs for readability
                rows.append("\t".join(row))
        return "\n".join(rows)

    # --- HTML / HTM ---
    if ext in {".html", ".htm"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        # Simple, dependency-free stripping of tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # --- Python source (.py) ---
    if ext == ".py":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # Safety net (should not be hit if SUPPORTED_TEXT_EXTENSIONS stays in sync)
    raise RuntimeError(f"File type {ext} is in SUPPORTED_TEXT_EXTENSIONS but not handled.")


# Sentence splitter regex (rough, but good enough for our chunker)
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')


def split_text(
    text: str,
    max_words: int = 220,
    overlap_words: int = 40,
) -> List[str]:
    """
    Sentence-aware chunking:
    - First splits text into sentences (rough regex, no external libs).
    - Then groups sentences into chunks of ~max_words, with overlap_words
      from the previous chunk to keep context.
    """
    # Normalize whitespace a bit
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    # 1) Split into sentences
    sentences = SENTENCE_SPLIT_RE.split(text)

    chunks: List[str] = []
    current_words: List[str] = []

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_words = sent.split()
        if not sent_words:
            continue

        # If adding this sentence would exceed max_words, flush current chunk
        if current_words and len(current_words) + len(sent_words) > max_words:
            # finalize current chunk
            chunks.append(" ".join(current_words))

            # start next chunk with overlap from the end of previous
            if overlap_words > 0:
                current_words = current_words[-overlap_words:]
            else:
                current_words = []

        # Add sentence words
        current_words.extend(sent_words)

    # Flush any remaining words
    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def ingest_folder_to_store(
    folder: str,
    store: SimpleVectorStore,
    chunk_size: int = 500,
    overlap: int = 100,
    force_reindex: bool = False,
):
    folder_abs = os.path.abspath(folder)

    if force_reindex:
        print(f"[INFO] Force reindex enabled. Removing any existing chunks from: {folder_abs}")
        store.remove_by_source_prefix(folder_abs)

    # 1) Build a set of already-indexed file paths from existing metadata
    already_indexed_paths = set()
    for m in store.metadata:
        src = m.get("source_path")
        if isinstance(src, str):
            already_indexed_paths.add(os.path.abspath(src))

    docs_texts: List[str] = []
    docs_meta: List[Dict[str, Any]] = []

    for root, _, files in os.walk(folder_abs):
        for fname in files:
            if fname.startswith("."):
                continue

            path = os.path.join(root, fname)
            path_abs = os.path.abspath(path)

            # 2) Skip if this file was already indexed before (unless forcing)
            if not force_reindex and path_abs in already_indexed_paths:
                print(f"[SKIP] Already indexed: {path_abs}")
                continue

            try:
                text = load_text_from_file(path_abs)
            except Exception as e:
                print(f"[WARN] Skipping {path_abs}: {e}")
                continue

            chunks = split_text(text, max_words=chunk_size, overlap_words=overlap)
            mtime = os.path.getmtime(path_abs)

            for i, chunk in enumerate(chunks):
                docs_texts.append(chunk)
                docs_meta.append({
                    "id": str(uuid.uuid4()),
                    "source_path": path_abs,
                    "chunk_index": i,
                    "file_mtime": mtime,
                    "text": chunk,
                })

    if docs_texts:
        print(f"[INFO] Ingesting {len(docs_texts)} new chunks from {folder_abs}...")
        store.add_documents(docs_texts, docs_meta)
        print("[INFO] Done.")
    else:
        print("[INFO] No new documents found to ingest.")
