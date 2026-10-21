"""parse_document – extract text from PDF or .txt uploads."""

from __future__ import annotations

import io


def parse_document(content: bytes, filename: str) -> str:
    """Extract text from a PDF or .txt file.

    Returns the extracted text or raises ValueError on failure.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(content)
    if lower.endswith(".txt"):
        return content.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {filename}. Only .pdf and .txt are accepted.")


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    full = "\n".join(parts).strip()
    if len(full) < 200:
        raise ValueError(
            "No extractable text (likely a scanned PDF). "
            "Please paste the text directly instead."
        )
    return full
