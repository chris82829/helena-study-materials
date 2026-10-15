"""BM25 + multilingual E5 retrieval over an already filtered set of jobs.

Documents are embedded verbatim; only queries receive the E5 instruction.
The immutable model revision and preprocessing version isolate persisted caches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata

import numpy as np
from rank_bm25 import BM25Okapi


MODEL_ID = "intfloat/multilingual-e5-large-instruct"
MODEL_REVISION = "274baa43b0e13e37fafa6428dbc7938e62e5c439"
CACHE_VERSION = "documents-verbatim-normalized-max512-v1"
QUERY_INSTRUCTION = (
    "Given a job seeker's profile and preferences, retrieve job postings that "
    "match the candidate's skills, experience, and employment criteria."
)
RRF_K = 60
LEG_LIMIT = 20
_TOKEN_PATTERN = re.compile(r"(?:\.[^\W_]\w*|[^\W_]+(?:\+{1,2}|#)?)", re.UNICODE)
_LOGGER = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    """The actual embedding model could not produce usable vectors."""


def tokenize(text: str) -> list[str]:
    """Case-insensitive Unicode terms, preserving C++, C#, and .NET."""
    return _TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", text).casefold())


class HybridRetriever:
    """Fuse the first 20 results per retriever with RRF (k=60).

    ``jobs`` must already satisfy the caller's hard filters. ``encoder`` is an
    optional SentenceTransformer-compatible dependency for small offline tests;
    production always loads the pinned E5 model when no encoder is injected.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        device: str = "cpu",
        batch_size: int = 8,
        encoder=None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.device = device
        self.batch_size = batch_size
        self._encoder = encoder
        self._encoder_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        namespace = hashlib.sha256(
            f"{MODEL_ID}\n{MODEL_REVISION}\n{CACHE_VERSION}".encode('utf-8')
        ).hexdigest()[:20]
        self._cache_dir = Path(cache_dir).expanduser() / namespace

    def _get_encoder(self):
        with self._encoder_lock:
            if self._encoder is None:
                try:
                    # Import and download happen only on the first embedding request.
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(
                        MODEL_ID, revision=MODEL_REVISION, device=self.device
                    )
                    model.max_seq_length = 512
                    self._encoder = model
                except Exception:
                    raise EmbeddingUnavailable(
                        "Das E5-Embedding-Modell konnte nicht geladen werden."
                    ) from None
            return self._encoder

    def prepare_query_encoder(self) -> None:
        """Load E5 and run one short query before the first user search."""
        self._encode([f"Instruct: {QUERY_INSTRUCTION}\nQuery: Python SQL Datenanalyse"])

    def _encode(self, texts: list[str]) -> np.ndarray:
        try:
            with self._inference_lock:
                encoder = self._get_encoder()
                vectors = np.asarray(
                    encoder.encode(
                        texts,
                        batch_size=self.batch_size,
                        normalize_embeddings=True,
                        convert_to_numpy=True,
                        show_progress_bar=False,
                    ),
                    dtype=np.float32,
                )
            if (
                vectors.ndim != 2
                or vectors.shape[0] != len(texts)
                or vectors.shape[1] < 1
                or not np.isfinite(vectors).all()
            ):
                raise ValueError("Invalid embedding matrix")
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.isfinite(norms).all() or (norms <= 0).any():
                raise ValueError("Invalid embedding norms")
            # Also enforce normalization for injected encoders and future SDK changes.
            return vectors / norms
        except EmbeddingUnavailable:
            raise
        except Exception:
            raise EmbeddingUnavailable(
                "Das E5-Embedding-Modell konnte keine gültigen Vektoren erzeugen."
            ) from None

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.npy"

    def _read_cached(self, text: str, dimension: int | None) -> np.ndarray | None:
        path = self._cache_path(text)
        try:
            # No pickle or arbitrary object deserialization; reject implausible files.
            if path.stat().st_size > 1_048_576:
                return None
            vector = np.load(path, allow_pickle=False)
            if not isinstance(vector, np.ndarray):
                # An NPZ archive is not a document vector, even with a .npy name.
                if hasattr(vector, "close"):
                    vector.close()
                return None
            if (
                vector.ndim != 1
                or not 1 <= vector.size <= 65_536
                or (dimension is not None and vector.size != dimension)
                or not np.issubdtype(vector.dtype, np.number)
                or np.iscomplexobj(vector)
                or not np.isfinite(vector).all()
            ):
                return None
            vector = vector.astype(np.float32)
            norm = np.linalg.norm(vector)
            if not np.isfinite(norm) or norm <= 0:
                return None
            return vector / norm
        except Exception:
            # A partial/corrupt cache is recomputed from the actual model.
            return None

    def _write_cached(self, text: str, vector: np.ndarray) -> None:
        temporary_path = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self._cache_dir, prefix=".embedding-", suffix=".npy", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                np.save(handle, vector, allow_pickle=False)
            os.replace(temporary_path, self._cache_path(text))
        except OSError:
            # Persistence is an optimization; inference must still return real vectors.
            _LOGGER.warning("Embedding cache could not be persisted.")
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _documents(self, texts: list[str], dimension: int | None = None) -> np.ndarray:
        unique_texts = list(dict.fromkeys(texts))
        vectors = {text: self._read_cached(text, dimension) for text in unique_texts}
        missing = [text for text, vector in vectors.items() if vector is None]
        if missing:
            encoded = self._encode(missing)
            if dimension is not None and encoded.shape[1] != dimension:
                raise EmbeddingUnavailable("E5 lieferte inkonsistente Vektordimensionen.")
            dimension = encoded.shape[1]
            for text, vector in zip(missing, encoded):
                vectors[text] = vector
                self._write_cached(text, vector)
        if dimension is None:
            dimension = vectors[unique_texts[0]].size
        inconsistent = [
            text for text, vector in vectors.items() if vector.size != dimension
        ]
        if inconsistent:
            encoded = self._encode(inconsistent)
            if encoded.shape[1] != dimension:
                raise EmbeddingUnavailable("E5 lieferte inkonsistente Vektordimensionen.")
            for text, vector in zip(inconsistent, encoded):
                vectors[text] = vector
                self._write_cached(text, vector)
        return np.stack([vectors[text] for text in texts])

    def warmup(self, jobs: list[dict], progress=None) -> None:
        """Persist small batches, so an interrupted full import can resume."""
        chunk_size = max(32, self.batch_size)
        for offset in range(0, len(jobs), chunk_size):
            self._documents([job['search_text'] for job in jobs[offset:offset + chunk_size]])
            if progress is not None:
                progress(min(offset + chunk_size, len(jobs)), len(jobs))

    @staticmethod
    def _stable_key(jobs: list[dict], index: int) -> tuple[str, int]:
        return str(jobs[index]["id"]), index

    def _lexical(self, jobs: list[dict], query: str) -> dict[int, tuple[int, float]]:
        terms = tokenize(query)
        documents = [tokenize(job["search_text"]) for job in jobs]
        if not terms or not any(documents):
            return {}
        scores = BM25Okapi(documents).get_scores(terms)
        query_terms = set(terms)
        # BM25 can return zero for real matches (e.g. IDF=0 in tiny corpora).
        # Membership, rather than score>0, distinguishes actual lexical matches.
        matches = [
            index for index, document in enumerate(documents)
            if query_terms.intersection(document)
        ]
        ranked = sorted(
            matches,
            key=lambda index: (-float(scores[index]), self._stable_key(jobs, index)),
        )[:LEG_LIMIT]
        return {index: (rank, float(scores[index])) for rank, index in enumerate(ranked, 1)}

    def _semantic(self, jobs: list[dict], query: str) -> dict[int, tuple[int, float]]:
        instructed = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {query}"
        query_vector = self._encode([instructed])[0]
        documents = self._documents(
            [job["search_text"] for job in jobs], dimension=query_vector.size
        )
        scores = documents @ query_vector
        ranked = sorted(
            range(len(jobs)),
            key=lambda index: (-float(scores[index]), self._stable_key(jobs, index)),
        )[:LEG_LIMIT]
        return {index: (rank, float(scores[index])) for rank, index in enumerate(ranked, 1)}

    def search(self, jobs: list[dict], query: str, top_k: int = 20) -> list[dict]:
        """Return at most 20 fused candidates from the caller's eligible jobs."""
        if not jobs or top_k <= 0:
            return []
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must contain text")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="retrieval") as pool:
            lexical_future = pool.submit(self._lexical, jobs, query)
            semantic_future = pool.submit(self._semantic, jobs, query)
            lexical = lexical_future.result()
            semantic = semantic_future.result()
        results = []
        for index in lexical.keys() | semantic.keys():
            bm25_rank, bm25_score = lexical.get(index, (None, None))
            semantic_rank, semantic_score = semantic.get(index, (None, None))
            rrf_score = sum(
                1.0 / (RRF_K + rank)
                for rank in (bm25_rank, semantic_rank) if rank is not None
            )
            results.append((index, {
                "job": jobs[index],
                "rrf_score": rrf_score,
                "bm25_rank": bm25_rank,
                "semantic_rank": semantic_rank,
                "bm25_score": bm25_score,
                "semantic_score": semantic_score,
            }))
        results.sort(key=lambda item: (-item[1]["rrf_score"], self._stable_key(jobs, item[0])))
        return [result for _, result in results[:min(top_k, LEG_LIMIT)]]
