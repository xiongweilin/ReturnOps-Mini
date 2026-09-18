from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from returnops.api.routes import router
from returnops.errors import ReturnOpsError


def _error(code: str, message: str, *, details: dict | list | None = None, status: int = 400):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "requestId": str(uuid.uuid4()),
                "details": details,
            }
        },
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ReturnOpsError):
        raise exc
    return _error(exc.code, exc.message, details=exc.details, status=exc.status_code)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ()) if part != "body") or "body"
        fields.append({"field": location, "message": item.get("msg", "invalid")})
    return _error("validation_error", "请求参数校验失败", details=fields, status=422)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReturnOps Mini",
        version="0.1.0",
        description="用于工程判断训练的小型多租户退货退款系统。",
    )
    app.add_exception_handler(ReturnOpsError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(Path(__file__).with_name("static") / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
