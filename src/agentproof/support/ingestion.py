import base64
import binascii
import csv
import hashlib
import io
import json
from pathlib import PurePath
from types import SimpleNamespace

from pydantic import ValidationError

from agentproof.answers.retrieval import chunks

from .models import TicketInput

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMPORT_BYTES = 1024 * 1024
MAX_TEXT = 300000


class IngestionError(ValueError):
    pass


def decode_upload(filename, content_base64, extensions, *, max_bytes=MAX_UPLOAD_BYTES):
    if (
        not filename.strip()
        or filename != PurePath(filename).name
        or "\\" in filename
        or "\x00" in filename
        or len(filename) > 240
    ):
        raise IngestionError("Use a plain filename without folders")
    suffix = PurePath(filename).suffix.lower()
    if suffix not in extensions:
        raise IngestionError("Unsupported file type: " + ", ".join(sorted(extensions)))
    if len(content_base64) > ((max_bytes + 2) // 3) * 4:
        raise IngestionError(f"Upload must be at most {max_bytes // (1024 * 1024)} MiB")
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise IngestionError("File content is not valid base64") from None
    if not raw or len(raw) > max_bytes:
        raise IngestionError(
            f"Upload must contain data and be at most {max_bytes // (1024 * 1024)} MiB"
        )
    return suffix, raw


def document_content(filename, content_base64):
    suffix, raw = decode_upload(filename, content_base64, {".txt", ".md", ".pdf"})
    pages = []
    if suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise IngestionError("Encrypted PDFs are not supported")
            if len(reader.pages) > 200:
                raise IngestionError("PDFs may contain at most 200 pages")
            size = 0
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                size += len(text)
                if size > MAX_TEXT:
                    raise IngestionError("Extracted text exceeds 300,000 characters")
                pages.append({"page": index, "text": text})
        except (PdfReadError, OSError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, IngestionError):
                raise
            raise IngestionError("PDF could not be read; use a text PDF or TXT/Markdown") from None
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise IngestionError("Text files must use UTF-8 encoding") from None
        if "\x00" in text:
            raise IngestionError("Text contains binary data")
        pages = [{"page": None, "text": text}]
    text = "\n\n".join(page["text"] for page in pages)
    if not text.strip():
        raise IngestionError("No readable text found; scanned PDFs need OCR before upload")
    if len(text) > MAX_TEXT:
        raise IngestionError("Extracted text exceeds 300,000 characters")
    parts = []
    for page in pages:
        for index, passage in enumerate(
            chunks([SimpleNamespace(id="document", title=filename, text=page["text"])]), 1
        ):
            if passage["text"].strip():
                parts.append(
                    {
                        "page": page["page"],
                        "chunk": index,
                        "text": passage["text"],
                        "start": passage["start"],
                        "end": passage["end"],
                    }
                )
    return {
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "text": text,
        "pages": pages,
        "chunks": parts,
        "page_count": len(pages) if suffix == ".pdf" else 0,
    }


def imported_tickets(filename, content_base64):
    suffix, raw = decode_upload(
        filename, content_base64, {".csv", ".json"}, max_bytes=MAX_IMPORT_BYTES
    )
    try:
        text = raw.decode("utf-8-sig")
        if suffix == ".json":
            records = json.loads(text)
            if not isinstance(records, list):
                raise IngestionError("JSON import must be a list of tickets")
        else:
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise IngestionError("CSV needs unique column names")
            records = []
            for row in reader:
                records.append(row)
                if len(records) > 50:
                    raise IngestionError("Import at most 50 tickets at a time")
        if not 1 <= len(records) <= 50:
            raise IngestionError("Import between 1 and 50 tickets")
        tickets = []
        for index, row in enumerate(records, 1):
            if not isinstance(row, dict) or set(row) - {
                "title",
                "body",
                "subject",
                "description",
                "external_id",
            }:
                raise IngestionError(f"Row {index} has unsupported fields")
            if ("title" in row and "subject" in row) or ("body" in row and "description" in row):
                raise IngestionError(f"Row {index} has conflicting aliases")
            try:
                tickets.append(
                    TicketInput.model_validate(
                        {
                            "title": row.get("title", row.get("subject")),
                            "body": row.get("body", row.get("description")),
                            "external_id": row.get("external_id") or None,
                        }
                    )
                )
            except ValidationError:
                raise IngestionError(
                    f"Row {index} needs a valid title and body within the size limits"
                ) from None
        return tickets
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error, RecursionError):
        raise IngestionError("Ticket file is not valid UTF-8 CSV or JSON") from None
