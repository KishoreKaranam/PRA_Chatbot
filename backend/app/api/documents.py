"""Serve the PDF copies of PRA source documents (read-only, one folder only)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.application.grounding.sources import resolve_document

router = APIRouter()


@router.get("/documents/{filename}")
async def get_document(filename: str) -> FileResponse:
    """
    Open a source document PDF in the browser.

    Only files that exist directly in the configured documents folder
    (DOCUMENTS_DIR, default backend/documents) can be returned.
    """
    path = resolve_document(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )
