"""Shared response envelopes so every endpoint has a predictable shape."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.logging import request_id_ctx

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    request_id: str | None = Field(default_factory=request_id_ctx.get)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
