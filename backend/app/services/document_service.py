"""
Orchestrates upload: validate (extension, MIME, %PDF magic bytes, size), hash for
dedupe, store via ObjectStorage, create Document/DocumentVersion/ProcessingJob rows,
enqueue the worker job, write an audit log. Never parses the PDF inline — expensive work
is asynchronous.

Status: interface placeholder — implemented in Phase 3.
"""

from __future__ import annotations


class DocumentService:
    """See module docstring. Implemented in Phase 3."""
