import os
import json
from typing import List, Dict, Any, Optional

import numpy as np

from config import STORAGE_DIR
from llm_client import embed_texts


class SimpleVectorStore:
    """
    Very light-weight vector store that keeps:

    - embeddings in a single .npy file
    - metadata in a parallel JSON file

    It is tolerant to:
    - changing embedding dimensions (will reset the index automatically)
    - length mismatches between embeddings and metadata (will truncate)
    """

    def __init__(self, storage_dir: str = STORAGE_DIR):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

        self.index_path = os.path.join(self.storage_dir, "embeddings.npy")
        self.meta_path = os.path.join(self.storage_dir, "metadata.json")

        self.embeddings: Optional[np.ndarray] = None
        self.metadata: List[Dict[str, Any]] = []

        self._load()

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _load(self) -> None:
        """
        Load embeddings + metadata if present.
        If shapes/lengths are inconsistent, truncate to the smaller length.
        """
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            # Load embeddings
            try:
                self.embeddings = np.load(self.index_path)
            except Exception as e:
                print(
                    f"[SimpleVectorStore] Failed to load embeddings ({e}); "
                    "resetting index.",
                    flush=True,
                )
                self.reset_index(persist=False)
                return

            # Load metadata
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(
                    f"[SimpleVectorStore] Failed to load metadata ({e}); "
                    "resetting index.",
                    flush=True,
                )
                self.reset_index(persist=False)
                return

            # Sanity checks
            if self.embeddings.ndim != 2:
                print(
                    "[SimpleVectorStore] Embeddings array is not 2D; "
                    "resetting index.",
                    flush=True,
                )
                self.reset_index(persist=False)
                return

            n_emb, _ = self.embeddings.shape
            n_meta = len(self.metadata)

            if n_emb != n_meta:
                n = min(n_emb, n_meta)
                print(
                    f"[SimpleVectorStore] Mismatch between embeddings ({n_emb}) "
                    f"and metadata ({n_meta}); truncating to {n}.",
                    flush=True,
                )
                self.embeddings = self.embeddings[:n, :]
                self.metadata = self.metadata[:n]
                self._save()
        else:
            # No existing index/metadata
            self.embeddings = None
            self.metadata = []

    def _save(self) -> None:
        """
        Persist embeddings + metadata. If there are no embeddings, we remove
        the embeddings file but still write an empty metadata file.
        """
        if self.embeddings is not None and self.embeddings.size > 0:
            np.save(self.index_path, self.embeddings)
        else:
            # If no embeddings, remove file if it exists to avoid confusion
            if os.path.exists(self.index_path):
                try:
                    os.remove(self.index_path)
                except OSError:
                    pass

        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    # -----------------------------
    # Public API
    # -----------------------------

    def reset_index(self, persist: bool = True) -> None:
        """
        Completely clear the in-memory and on-disk index.

        Safe because this store only contains *derived* data (embeddings)
        plus metadata; the real content (docs/notes) lives elsewhere.
        """
        self.embeddings = None
        self.metadata = []

        # Remove old files to avoid confusion
        for path in (self.index_path, self.meta_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

        if persist:
            self._save()

    def remove_by_source_prefix(self, folder: str) -> None:
        """
        Drop all chunks whose 'source_path' is under the given folder.

        Used for force reindexing of a specific docs folder.
        """
        if self.embeddings is None or not self.metadata:
            return

        folder_abs = os.path.abspath(folder)
        keep_indices: List[int] = []

        for i, m in enumerate(self.metadata):
            src = m.get("source_path")
            if not isinstance(src, str):
                keep_indices.append(i)
                continue
            src_abs = os.path.abspath(src)
            # If this chunk belongs to the folder, skip it (i.e., delete)
            if src_abs.startswith(folder_abs):
                continue
            keep_indices.append(i)

        if not keep_indices:
            # everything removed
            self.embeddings = None
            self.metadata = []
        else:
            self.embeddings = self.embeddings[keep_indices, :]
            self.metadata = [self.metadata[i] for i in keep_indices]

        self._save()

    def add_documents(self, texts: List[str], metadatas: List[Dict[str, Any]]) -> None:
        """
        Add new text chunks + metadata to the store.

        If the embedding dimension changes (e.g., because you switched
        EMBED_MODEL), the index is automatically reset and rebuilt from
        the new data to avoid crashes.
        """
        if not texts:
            return

        # 1) Embed texts
        new_embs = embed_texts(texts)

        # Normalize to numpy array
        if not isinstance(new_embs, np.ndarray):
            new_embs = np.array(new_embs, dtype="float32")

        if new_embs.ndim == 1:
            # Single vector
            new_embs = new_embs.reshape(1, -1)

        # 2) Merge / reset based on dimensions
        if self.embeddings is None or self.embeddings.size == 0:
            # First time index creation
            self.embeddings = new_embs
            self.metadata = []
        else:
            old_dim = self.embeddings.shape[1]
            new_dim = new_embs.shape[1]

            if old_dim != new_dim:
                # Dimension changed: reset index and start fresh
                print(
                    f"[SimpleVectorStore] Embedding dimension changed from "
                    f"{old_dim} to {new_dim}. Resetting vector index.",
                    flush=True,
                )
                self.reset_index(persist=False)
                self.embeddings = new_embs
                self.metadata = []
            else:
                # Same dim → safe to append
                self.embeddings = np.vstack([self.embeddings, new_embs])

        # 3) Attach metadata
        self.metadata.extend(metadatas)
        self._save()

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Simple cosine-similarity search over the stored embeddings.

        If there is a dimension mismatch between query embedding and index,
        we fail gracefully by returning an empty list.
        """
        if self.embeddings is None or self.embeddings.size == 0:
            return []

        # Embed query
        q_embs = embed_texts([query])
        if isinstance(q_embs, np.ndarray):
            q_emb = q_embs[0]
        else:
            q_emb = q_embs[0]

        q_emb = np.array(q_emb, dtype="float32")
        if q_emb.ndim != 1:
            q_emb = q_emb.reshape(-1)

        # Dim check
        if self.embeddings.shape[1] != q_emb.shape[0]:
            print(
                "[SimpleVectorStore] Search embedding dimension mismatch "
                "(index vs query). The index is likely from an older "
                "embedding model. Consider clearing STORAGE_DIR or resetting "
                "the index. Returning no results instead of raising.",
                flush=True,
            )
            return []

        # Cosine similarity
        norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(q_emb)
        sims = (self.embeddings @ q_emb) / (norms + 1e-8)
        idxs = np.argsort(-sims)[:top_k]

        results: List[Dict[str, Any]] = []
        for i in idxs:
            meta = self.metadata[i].copy()
            meta["score"] = float(sims[i])
            results.append(meta)
        return results
