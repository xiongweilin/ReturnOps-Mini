from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("FAKE_PAYMENT_DB", "/data/fake-payment.db")
WEBHOOK_URL = os.environ.get("FAKE_PAYMENT_WEBHOOK_URL", "http://api:8000/v1/webhooks/payment")
WEBHOOK_SECRET = os.environ.get("FAKE_PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")
_lock = threading.Lock()


class RefundRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    return_case_id: str


def _init() -> None:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refunds (
                idempotency_key TEXT PRIMARY KEY,
                refund_id TEXT NOT NULL UNIQUE,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                return_case_id TEXT NOT NULL,
                status TEXT NOT NULL,
                post_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    _init()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row(key: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM refunds WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return None if row is None else dict(row)


def _store(key: str, request: RefundRequest) -> dict:
    with _lock, _db() as conn:
        existing = conn.execute(
            "SELECT * FROM refunds WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE refunds SET post_count = post_count + 1 WHERE idempotency_key = ?", (key,)
            )
            return dict(existing)
        refund_id = f"rf_{uuid.uuid4().hex[:18]}"
        conn.execute(
            """
            INSERT INTO refunds (
                idempotency_key, refund_id, amount_minor, currency, return_case_id, status
            ) VALUES (?, ?, ?, ?, ?, 'succeeded')
            """,
            (key, refund_id, request.amount_minor, request.currency, request.return_case_id),
        )
        return {
            "idempotency_key": key,
            "refund_id": refund_id,
            "amount_minor": request.amount_minor,
            "currency": request.currency,
            "return_case_id": request.return_case_id,
            "status": "succeeded",
            "post_count": 1,
        }


def _send_webhook(row: dict, *, duplicate: bool = False) -> None:
    payload = {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "refund_id": row["refund_id"],
        "idempotency_key": row["idempotency_key"],
        "status": row["status"],
        "amount_minor": row["amount_minor"],
        "currency": row["currency"],
    }
    try:
        with httpx.Client(timeout=3.0) as client:
            client.post(WEBHOOK_URL, headers={"X-Webhook-Secret": WEBHOOK_SECRET}, json=payload)
            if duplicate:
                client.post(WEBHOOK_URL, headers={"X-Webhook-Secret": WEBHOOK_SECRET}, json=payload)
    except Exception:
        # This fake provider deliberately does not make refund success depend on
        # webhook delivery. A real provider would have its own durable retry queue.
        pass


app = FastAPI(title="Fake Payment Provider", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    _init()
    return {"status": "ok"}


@app.post("/refunds")
def create_refund(
    body: RefundRequest,
    background: BackgroundTasks,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    simulate: str = Header(default="normal", alias="X-Simulate"),
) -> dict:
    if simulate == "503_before_processing":
        raise HTTPException(status_code=503, detail="simulated pre-processing failure")

    row = _store(idempotency_key, body)

    if simulate == "timeout_after_processing":
        # Persist success first, then withhold the ACK long enough for ReturnOps to
        # time out. The caller must classify the result as UNKNOWN and reconcile.
        background.add_task(_send_webhook, row)
        time.sleep(5)
    elif simulate == "webhook_before_timeout":
        # Deliberately race two evidence paths: send a success webhook from a
        # separate thread before the original HTTP request finally times out.
        # ReturnOps must keep the fresher committed SUCCEEDED fact and must not
        # downgrade it to UNKNOWN in the timeout handler.
        threading.Thread(target=_send_webhook, args=(row,), daemon=True).start()
        time.sleep(5)
    elif simulate == "duplicate_webhook":
        background.add_task(_send_webhook, row, duplicate=True)
    elif simulate != "no_webhook":
        background.add_task(_send_webhook, row)

    return {
        "refund_id": row["refund_id"],
        "status": row["status"],
        "amount_minor": row["amount_minor"],
        "currency": row["currency"],
        "idempotency_key": row["idempotency_key"],
    }


@app.get("/refunds/by-idempotency-key")
def refund_by_key(key: str = Query(min_length=1)) -> dict:
    row = _row(key)
    if row is None:
        raise HTTPException(status_code=404, detail="refund not found")
    return {
        "refund_id": row["refund_id"],
        "status": row["status"],
        "amount_minor": row["amount_minor"],
        "currency": row["currency"],
        "idempotency_key": row["idempotency_key"],
        "post_count": row["post_count"],
    }
