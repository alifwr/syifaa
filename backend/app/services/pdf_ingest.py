"""PDF text extraction and chunking.

`approx_token_count` uses a cheap whitespace heuristic scaled by 1.3
(words→tokens); good enough for chunk-boundary math, not billing.
"""
import fitz


def extract_text(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"cannot open as PDF: {e}") from e
    try:
        parts = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return "\n\n".join(parts).strip()


def approx_token_count(s: str) -> int:
    return int(len(s.split()) * 1.3) + 1


def chunk_text(text: str, max_tokens: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if overlap >= max_tokens:
        raise ValueError("overlap must be smaller than max_tokens")

    words = text.split()
    # Words per chunk so that 1.3 * words ≈ max_tokens.
    words_per_chunk = max(1, int(max_tokens / 1.3))
    # Treat overlap token count conservatively as a word count so that
    # actual word-level overlap is guaranteed >= overlap (not under-estimated
    # by the 1.3 scaling factor).
    words_overlap = min(overlap, words_per_chunk - 1)
    stride = max(1, words_per_chunk - words_overlap)

    chunks: list[str] = []
    i = 0
    while i < len(words):
        piece = words[i : i + words_per_chunk]
        chunks.append(" ".join(piece))
        if i + words_per_chunk >= len(words):
            break
        i += stride
    return chunks
