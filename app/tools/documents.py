"""parse_document – extract text from PDF or .txt uploads with scanned-PDF OCR fallback."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import time
from typing import Any

import psutil
from pypdf import PdfReader

# Bounded OCR concurrency: exactly one vision OCR job at a time
_OCR_SEMAPHORE = asyncio.Semaphore(1)


def parse_document(content: bytes, filename: str) -> str:
    """Extract text from a PDF or .txt file.

    Uses pypdf first. If extracted text is under 50 characters,
    falls back to Gemini vision OCR.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(content)
    if lower.endswith(".txt"):
        return content.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {filename}. Only .pdf and .txt are accepted.")


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    full = "\n".join(parts).strip()
    if len(full) < 50:
        # Trigger bounded-memory Gemini vision OCR fallback
        return _ocr_pdf_sync(content)
    return full


async def ocr_pdf_pages_async(content: bytes) -> str:
    """Render scanned PDF pages and extract text using Gemini vision.

    Memory bounded: renders ONE page at a time at ~108 DPI (scale=1.5),
    capped at 5 pages, encodes to JPEG, frees the buffer before next page,
    with OCR concurrency bounded to 1.
    """
    import pypdfium2 as pdfium

    from app.llm_gate import default_gate

    async with _OCR_SEMAPHORE:
        proc = psutil.Process(os.getpid())
        mem_before_mb = proc.memory_info().rss / (1024 * 1024)
        t0 = time.time()

        pdf = pdfium.PdfDocument(content)
        total_pages = len(pdf)
        pages_to_process = min(total_pages, 5)
        extracted_pages: list[str] = []

        for idx in range(pages_to_process):
            page = pdf[idx]
            # scale=1.5 yields 72 * 1.5 = 108 DPI, within the 100-120 DPI requirement
            bitmap = page.render(scale=1.5)
            pil_img = bitmap.to_pil()

            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            jpeg_bytes = buf.getvalue()

            # Free buffers immediately before API call
            del pil_img
            del bitmap
            buf.close()

            b64_img = base64.b64encode(jpeg_bytes).decode("ascii")
            del jpeg_bytes

            prompt_messages: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all legible text, course titles, marks, grades, dates, "
                                "degree names, and institutional headers from this scanned document page verbatim."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                        },
                    ],
                }
            ]

            try:
                page_text = await default_gate.complete(
                    messages=prompt_messages,
                    tier="fast",
                    temperature=0.1,
                    max_tokens=1000,
                    agent_name="OCR_Vision",
                )
                if page_text:
                    extracted_pages.append(page_text.strip())
            except Exception as ocr_err:
                extracted_pages.append(f"[OCR extraction failed on page {idx+1}: {ocr_err}]")

        mem_after_mb = proc.memory_info().rss / (1024 * 1024)
        duration_s = round(time.time() - t0, 2)
        from app.events import global_bus

        global_bus.emit(
            {
                "agent": "OCR_Vision",
                "type": "tool_result",
                "phase": "document_parse",
                "message": f"Vision OCR completed in {duration_s}s (memory: {mem_before_mb:.1f}MB -> {mem_after_mb:.1f}MB)",
                "data": {"duration_s": duration_s, "mem_before_mb": mem_before_mb, "mem_after_mb": mem_after_mb},
            }
        )
        combined = "\n\n".join(extracted_pages).strip()
        if not combined:
            return "[Scanned document: no text could be extracted]"
        return combined



def _ocr_pdf_sync(content: bytes) -> str:
    """Synchronous runner for ocr_pdf_pages_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, ocr_pdf_pages_async(content)).result(timeout=60)
        else:
            return loop.run_until_complete(ocr_pdf_pages_async(content))
    except Exception:
        return asyncio.run(ocr_pdf_pages_async(content))

