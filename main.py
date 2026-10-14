"""Run: python -m uvicorn main:app --host 127.0.0.1 --port 18053 --reload"""
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import Settings
from model_client import ModelError, generate_answer


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(
        strict=True, min_length=1, max_length=2000,
        description="Text; strip outer whitespace before checking 1–2000 characters.",
        examples=["Giải thích API bằng một câu tiếng Việt."],
    )

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatResponse(BaseModel):
    answer: str = Field(min_length=1, description="Text returned by the model API.")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorDetail(BaseModel):
    code: Literal["model_timeout", "model_unavailable", "model_backend_error"]
    message: str


class BackendErrorResponse(BaseModel):
    detail: ErrorDetail


def create_app(settings: Settings | None = None, transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings if settings is not None else Settings.load()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(app.state.settings.timeout_seconds),
            follow_redirects=False, transport=transport,
        ) as client:
            app.state.model_client = client
            yield

    app = FastAPI(
        title="AI Guru — Chat API", version="1.0.0", lifespan=lifespan,
        description="Single-turn chat through an independent model API.",
    )

    @app.get("/health", response_model=HealthResponse, tags=["Health"],
             summary="Check application liveness, without calling the model")
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post("/chat", response_model=ChatResponse, tags=["Chat"], responses={
        502: {"model": BackendErrorResponse, "description": "Backend rejected request or invalid response"},
        503: {"model": BackendErrorResponse, "description": "Backend unavailable"},
        504: {"model": BackendErrorResponse, "description": "Backend timeout"},
    })
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        try:
            answer = await generate_answer(
                request.app.state.model_client, request.app.state.settings, body.message,
            )
        except ModelError as exc:
            raise HTTPException(status_code=exc.status, detail={
                "code": exc.code, "message": exc.message,
            }) from None
        return ChatResponse(answer=answer)

    return app


app = create_app()
