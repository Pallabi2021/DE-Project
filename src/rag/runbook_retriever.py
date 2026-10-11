"""
Runbook Retriever for Autonomous Data Quality & Incident Resolution Platform.

Implements a hybrid retrieval system over operational runbooks:
- Section-level chunking of Markdown runbooks.
- BM25 / keyword term frequency ranking (zero external dependencies).
- Optional OpenAI embedding similarity (text-embedding-3-small) with graceful BM25 fallback.
- Runbook category retrieval and remediation action extraction.
"""

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def _tokenize(text: str) -> List[str]:
    """
    Tokenizes text into normalized keywords, handling plurals and code identifiers.
    """
    # Find all alphanumeric tokens and identifiers
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    expanded: List[str] = []
    stopwords = {
        "a", "an", "the", "in", "on", "of", "for", "with", "at", "by", "from",
        "up", "about", "into", "over", "after", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "and", "or", "but", "if", "then", "else", "when", "as", "to", "this",
        "that", "these", "those", "it", "its"
    }

    for tok in tokens:
        # Split tokens with underscores into parts (e.g. customer_id -> customer, id)
        sub_tokens = [tok]
        if "_" in tok:
            sub_tokens.extend([t for t in tok.split("_") if t])

        for st in sub_tokens:
            if st in stopwords:
                continue
            expanded.append(st)
            # Basic suffix stripping to bridge singular/plural forms (e.g. columns -> column)
            if len(st) > 4:
                if st.endswith("ies"):
                    expanded.append(st[:-3] + "y")
                elif st.endswith("es"):
                    expanded.append(st[:-2])
                elif st.endswith("s"):
                    expanded.append(st[:-1])
                elif st.endswith("ing"):
                    expanded.append(st[:-3])
                elif st.endswith("ed"):
                    expanded.append(st[:-2])

    return expanded


class BM25Ranker:
    """
    Pure Python BM25 (Okapi) ranking engine without external dependencies.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avg_doc_len = 0.0
        self.doc_lengths: List[int] = []
        self.doc_term_freqs: List[Counter] = []
        self.doc_freqs: Counter = Counter()
        self.idf: Dict[str, float] = {}

    def fit(self, tokenized_docs: List[List[str]]) -> None:
        self.corpus_size = len(tokenized_docs)
        if self.corpus_size == 0:
            self.avg_doc_len = 0.0
            return

        self.doc_lengths = [len(doc) for doc in tokenized_docs]
        self.avg_doc_len = sum(self.doc_lengths) / self.corpus_size
        self.doc_term_freqs = [Counter(doc) for doc in tokenized_docs]

        self.doc_freqs = Counter()
        for doc in tokenized_docs:
            for term in set(doc):
                self.doc_freqs[term] += 1

        # Lucene BM25 IDF formulation: ln(1 + (N - n + 0.5) / (n + 0.5)) - guaranteed positive
        self.idf = {}
        for term, freq in self.doc_freqs.items():
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score(self, query_tokens: List[str]) -> List[float]:
        if self.corpus_size == 0:
            return []

        scores = [0.0] * self.corpus_size
        for term in query_tokens:
            if term not in self.idf:
                continue
            idf_val = self.idf[term]
            for doc_idx in range(self.corpus_size):
                tf = self.doc_term_freqs[doc_idx].get(term, 0)
                if tf <= 0:
                    continue
                doc_len = self.doc_lengths[doc_idx]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_len or 1.0)))
                scores[doc_idx] += idf_val * (numerator / denominator)

        return scores


class RunbookRetriever:
    """
    RAG retriever for operational runbooks supporting BM25 and optional OpenAI embeddings.
    """

    def __init__(self, runbooks_dir: Optional[str] = None):
        if runbooks_dir:
            self.runbooks_dir = Path(runbooks_dir)
        else:
            # Look relative to file location or current working directory
            cand1 = Path(__file__).resolve().parent.parent.parent / "knowledge" / "runbooks"
            cand2 = Path.cwd() / "knowledge" / "runbooks"
            if cand1.exists():
                self.runbooks_dir = cand1
            elif cand2.exists():
                self.runbooks_dir = cand2
            else:
                self.runbooks_dir = cand1

        self.chunks: List[Dict[str, Any]] = []
        self.runbooks_by_category: Dict[str, Dict[str, Any]] = {}
        self.bm25 = BM25Ranker()
        self.openai_client = None
        self.chunk_embeddings: List[List[float]] = []

        self._init_openai_if_available()
        self.index_runbooks()

    def _init_openai_if_available(self) -> None:
        """Attempts to initialize OpenAI client if API key is present."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return
        try:
            import openai
            self.openai_client = openai.OpenAI(api_key=api_key)
        except Exception:
            self.openai_client = None

    def _extract_remediations(self, text: str) -> List[str]:
        """Extracts remediation action identifiers from markdown text."""
        remediations: List[str] = []
        # Match backtick identifiers like `reprocess_with_schema_evolution`
        backtick_matches = re.findall(r"`([a-zA-Z0-9_]+)`", text)
        remediation_keywords = {
            "reprocess_with_schema_evolution",
            "backfill_missing_column",
            "quarantine_invalid_records",
            "deduplicate_silver",
            "fill_default_values",
            "full_replay",
            "partial_replay",
        }
        for match in backtick_matches:
            if match in remediation_keywords or "_" in match:
                if match not in remediations:
                    remediations.append(match)

        # Also search for list lines under remediation sections
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                # Extract first code block or word
                m = re.search(r"[-*]\s*`?([a-zA-Z0-9_]+)`?", line)
                if m:
                    action = m.group(1)
                    if action in remediation_keywords and action not in remediations:
                        remediations.append(action)

        return remediations

    def _parse_runbook_markdown(self, file_path: Path) -> Dict[str, Any]:
        """Parses a markdown runbook into structured sections."""
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        title = file_path.stem.replace("_", " ").title()
        sections: Dict[str, str] = {}
        current_section = "Overview"
        current_lines: List[str] = []

        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                continue
            elif line.startswith("## "):
                if current_lines:
                    sections[current_section] = "\n".join(current_lines).strip()
                    current_lines = []
                current_section = line[3:].strip()
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_section] = "\n".join(current_lines).strip()

        # Extract runbook category slug
        category = file_path.stem.replace("_runbook", "").lower()

        # Extract overall remediations
        remediations = self._extract_remediations(content)

        return {
            "category": category,
            "filename": file_path.name,
            "file_path": str(file_path.resolve()),
            "title": title,
            "sections": sections,
            "content": content,
            "recommended_remediations": remediations,
        }

    def index_runbooks(self) -> int:
        """
        Loads and parses all markdown files from runbooks_dir into indexed chunks.
        Returns the number of indexed chunks.
        """
        self.chunks = []
        self.runbooks_by_category = {}

        if not self.runbooks_dir.exists():
            return 0

        markdown_files = list(self.runbooks_dir.glob("*.md"))
        for file_path in markdown_files:
            parsed = self._parse_runbook_markdown(file_path)
            category = parsed["category"]
            self.runbooks_by_category[category] = parsed
            # Also store by exact filename stem
            self.runbooks_by_category[file_path.stem] = parsed

            # Create chunks per section
            for section_name, section_content in parsed["sections"].items():
                if not section_content.strip():
                    continue

                # Section-specific remediations or fallback to overall runbook remediations
                sec_remediations = self._extract_remediations(section_content)
                if not sec_remediations:
                    sec_remediations = parsed["recommended_remediations"]

                chunk_text = f"{parsed['title']} - {section_name}\n{section_content}"
                chunk = {
                    "category": category,
                    "title": parsed["title"],
                    "section": section_name,
                    "content": section_content,
                    "full_chunk_text": chunk_text,
                    "file_path": parsed["file_path"],
                    "filename": parsed["filename"],
                    "recommended_remediations": sec_remediations,
                }
                self.chunks.append(chunk)

        # Fit BM25 ranker on all chunks
        tokenized_corpus = [_tokenize(chunk["full_chunk_text"]) for chunk in self.chunks]
        self.bm25.fit(tokenized_corpus)

        # Try computing embeddings if OpenAI client is active
        self._compute_embeddings_if_available()

        return len(self.chunks)

    def _compute_embeddings_if_available(self) -> None:
        """Precomputes chunk embeddings if OpenAI is available."""
        self.chunk_embeddings = []
        if not self.openai_client or not self.chunks:
            return

        try:
            texts = [c["full_chunk_text"][:8000] for c in self.chunks]
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            self.chunk_embeddings = [d.embedding for d in response.data]
        except Exception:
            # Graceful fallback: do not crash, BM25 will be used
            self.chunk_embeddings = []

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Searches runbook sections relevant to query.
        Returns a list of dicts with title, section, content, relevance_score, and recommended_remediations.
        """
        if not self.chunks:
            self.index_runbooks()

        if not self.chunks:
            return []

        query_tokens = _tokenize(query)
        bm25_scores = self.bm25.score(query_tokens)

        # Normalize BM25 scores to [0.0, 1.0]
        max_bm25 = max(bm25_scores) if bm25_scores else 0.0
        norm_bm25 = [
            (score / max_bm25) if max_bm25 > 0 else 0.0
            for score in bm25_scores
        ]

        final_scores = list(norm_bm25)

        # If OpenAI embeddings are available, compute hybrid score
        if self.openai_client and self.chunk_embeddings and len(self.chunk_embeddings) == len(self.chunks):
            try:
                emb_resp = self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[query[:8000]],
                )
                query_emb = emb_resp.data[0].embedding
                emb_scores = [
                    self._cosine_similarity(query_emb, c_emb)
                    for c_emb in self.chunk_embeddings
                ]
                # Hybrid weighting: 60% semantic embedding, 40% BM25 keyword matching
                final_scores = [
                    0.4 * bm_s + 0.6 * max(0.0, emb_s)
                    for bm_s, emb_s in zip(norm_bm25, emb_scores)
                ]
            except Exception:
                # Fall back to BM25 scores
                final_scores = norm_bm25

        # Rank chunks by score descending
        ranked_indices = sorted(
            range(len(self.chunks)),
            key=lambda idx: final_scores[idx],
            reverse=True,
        )

        results: List[Dict[str, Any]] = []
        for idx in ranked_indices[:top_k]:
            score = final_scores[idx]
            chunk = self.chunks[idx]
            results.append({
                "title": chunk["title"],
                "section": chunk["section"],
                "content": chunk["content"],
                "relevance_score": round(float(score), 4),
                "recommended_remediations": list(chunk["recommended_remediations"]),
                "category": chunk["category"],
                "file_path": chunk["file_path"],
                "filename": chunk["filename"],
            })

        return results

    def get_runbook_by_category(self, category: str) -> Dict[str, Any]:
        """
        Fetches specific runbook by category name or file stem.
        Matches case-insensitively, allowing variations like 'schema_drift', 'SCHEMA_DRIFT', 'schema'.
        """
        if not self.runbooks_by_category:
            self.index_runbooks()

        norm = category.strip().lower().replace("-", "_")
        norm = norm.replace("_runbook.md", "").replace(".md", "").replace("_runbook", "")

        # Direct match
        if norm in self.runbooks_by_category:
            return self.runbooks_by_category[norm]

        # Partial prefix/suffix match
        for key, runbook in self.runbooks_by_category.items():
            if norm == key or norm in key or key in norm:
                return runbook

        return {}
