import pytest
from app.services.pdf_ingest import extract_text, chunk_text, approx_token_count


def _make_pdf(text: str) -> bytes:
    import fitz  # pymupdf
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    buf = doc.tobytes()
    doc.close()
    return buf


def test_extract_text_recovers_visible_text():
    pdf = _make_pdf("Hello from a PDF. Feynman teach-back works.")
    got = extract_text(pdf)
    assert "Hello from a PDF" in got
    assert "Feynman" in got


def test_extract_text_on_non_pdf_raises():
    with pytest.raises(ValueError):
        extract_text(b"not a pdf")


def test_chunk_text_respects_max_tokens():
    text = " ".join(["word"] * 3000)
    chunks = chunk_text(text, max_tokens=800, overlap=100)
    assert all(approx_token_count(c) <= 800 for c in chunks)
    assert len(chunks) >= 3


def test_chunk_text_has_overlap():
    text = " ".join([f"w{i}" for i in range(2000)])
    chunks = chunk_text(text, max_tokens=200, overlap=50)
    # overlap means last ~50 tokens of chunk[i] should appear in chunk[i+1]
    for a, b in zip(chunks, chunks[1:]):
        tail = " ".join(a.split()[-40:])
        assert tail.split()[0] in b


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("", max_tokens=800, overlap=100) == []


def test_approx_token_count_positive():
    assert approx_token_count("one two three") >= 3
