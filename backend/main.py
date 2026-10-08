"""Persistent FIFO queue; serialized writes protect four desks."""
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB = os.environ.get("QUEUE_DB", str(Path(__file__).parent / "data" / "queue.db"))
OPERATOR_KEY = os.environ.get("OPERATOR_KEY", "")


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection(write=False):
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connection(True) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS desks(
            id INTEGER PRIMARY KEY CHECK(id BETWEEN 1 AND 4),
            paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'waiting'
                CHECK(status IN ('waiting','serving','completed','cancelled')),
            desk_id INTEGER REFERENCES desks(id),
            created_at TEXT NOT NULL,
            called_at TEXT,
            completed_at TEXT)""")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_desk
            ON tickets(desk_id) WHERE status='serving'""")
        conn.execute("CREATE INDEX IF NOT EXISTS waiting_order ON tickets(status,id)")
        conn.executemany("INSERT OR IGNORE INTO desks(id) VALUES(?)", [(i,) for i in range(1,5)])
        assign_waiting(conn)


def assign_waiting(conn):
    """Must run inside the caller's write transaction, preserving FIFO order."""
    free_desks = conn.execute("""SELECT id FROM desks WHERE paused=0
        AND NOT EXISTS (SELECT 1 FROM tickets WHERE desk_id=desks.id AND status='serving')
        ORDER BY id""").fetchall()
    for desk in free_desks:
        ticket = conn.execute("SELECT id FROM tickets WHERE status='waiting' ORDER BY id LIMIT 1").fetchone()
        if ticket is None:
            break
        conn.execute("UPDATE tickets SET status='serving',desk_id=?,called_at=? WHERE id=?",
                     (desk["id"], now(), ticket["id"]))


@asynccontextmanager
async def lifespan(app):
    if len(OPERATOR_KEY) < 16:
        raise RuntimeError("OPERATOR_KEY debe contener al menos 16 caracteres")
    initialize()
    yield


app = FastAPI(title="Atención a clientes", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


def operator(authorization: str = Header(default="")):
    expected = "Bearer " + OPERATOR_KEY
    if len(OPERATOR_KEY) < 16 or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Clave de operador incorrecta")


def ticket_view(conn, row):
    position = None
    if row["status"] == "waiting":
        position = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status='waiting' AND id<=?", (row["id"],)
        ).fetchone()[0]
    return {"id": row["id"], "number": f"T{row['id']:04d}", "status": row["status"],
            "desk_id": row["desk_id"], "position": position,
            "created_at": row["created_at"], "called_at": row["called_at"],
            "completed_at": row["completed_at"]}


def desk_exists(conn, desk_id):
    row = conn.execute("SELECT * FROM desks WHERE id=?", (desk_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Mesa inexistente")
    return row


class NewTicket(BaseModel):
    request_id: UUID


class Finish(BaseModel):
    ticket_id: int


class Pause(BaseModel):
    paused: bool


@app.get("/api/health")
def health():
    with connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/state")
def state():
    with connection() as conn:
        waiting = conn.execute("SELECT * FROM tickets WHERE status='waiting' ORDER BY id").fetchall()
        desks = []
        for desk in conn.execute("SELECT * FROM desks ORDER BY id"):
            active = conn.execute("SELECT * FROM tickets WHERE desk_id=? AND status='serving'", (desk["id"],)).fetchone()
            desks.append({"id": desk["id"], "paused": bool(desk["paused"]),
                          "ticket": ticket_view(conn, active) if active else None})
        completed = conn.execute("SELECT COUNT(*) FROM tickets WHERE status='completed'").fetchone()[0]
        return {"waiting": [ticket_view(conn, row) for row in waiting], "desks": desks,
                "completed": completed, "updated_at": now()}


@app.post("/api/tickets")
def take_ticket(payload: NewTicket):
    token = str(payload.request_id)
    with connection(True) as conn:
        # Same request after a network retry returns the original ticket.
        conn.execute("INSERT OR IGNORE INTO tickets(token,created_at) VALUES(?,?)", (token, now()))
        assign_waiting(conn)
        row = conn.execute("SELECT * FROM tickets WHERE token=?", (token,)).fetchone()
        return {**ticket_view(conn, row), "token": token}


@app.get("/api/tickets/{token}")
def get_ticket(token: UUID):
    with connection() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE token=?", (str(token),)).fetchone()
        if row is None:
            raise HTTPException(404, "Turno no encontrado")
        return ticket_view(conn, row)


@app.post("/api/tickets/{token}/cancel")
def cancel_ticket(token: UUID):
    with connection(True) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE token=?", (str(token),)).fetchone()
        if row is None:
            raise HTTPException(404, "Turno no encontrado")
        if row["status"] != "waiting":
            raise HTTPException(409, "Solo puedes cancelar un turno en espera")
        conn.execute("UPDATE tickets SET status='cancelled', completed_at=? WHERE id=?", (now(), row["id"]))
        return {"status": "cancelled"}


@app.get("/api/operator/session", dependencies=[Depends(operator)])
def session():
    return {"authenticated": True}


@app.post("/api/desks/{desk_id}/next", dependencies=[Depends(operator)])
def call_next(desk_id: int):
    with connection(True) as conn:
        desk = desk_exists(conn, desk_id)
        if desk["paused"]:
            raise HTTPException(409, "La mesa está pausada")
        if conn.execute("SELECT 1 FROM tickets WHERE desk_id=? AND status='serving'", (desk_id,)).fetchone():
            raise HTTPException(409, "Finaliza el turno actual antes de llamar al siguiente")
        row = conn.execute("SELECT * FROM tickets WHERE status='waiting' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            raise HTTPException(409, "No hay turnos en espera")
        conn.execute("UPDATE tickets SET status='serving',desk_id=?,called_at=? WHERE id=?",
                     (desk_id, now(), row["id"]))
        return ticket_view(conn, conn.execute("SELECT * FROM tickets WHERE id=?", (row["id"],)).fetchone())


@app.post("/api/desks/{desk_id}/finish", dependencies=[Depends(operator)])
def finish(desk_id: int, payload: Finish):
    with connection(True) as conn:
        desk_exists(conn, desk_id)
        row = conn.execute("SELECT * FROM tickets WHERE id=? AND desk_id=? AND status='serving'",
                           (payload.ticket_id, desk_id)).fetchone()
        if row is None:
            raise HTTPException(409, "Ese turno ya no está siendo atendido en esta mesa")
        conn.execute("UPDATE tickets SET status='completed',completed_at=? WHERE id=?", (now(), row["id"]))
        assign_waiting(conn)
        next_ticket = conn.execute("SELECT * FROM tickets WHERE desk_id=? AND status='serving'", (desk_id,)).fetchone()
        return {"status": "completed", "next_ticket": ticket_view(conn, next_ticket) if next_ticket else None}


@app.post("/api/desks/{desk_id}/pause", dependencies=[Depends(operator)])
def pause(desk_id: int, payload: Pause):
    with connection(True) as conn:
        desk_exists(conn, desk_id)
        if conn.execute("SELECT 1 FROM tickets WHERE desk_id=? AND status='serving'", (desk_id,)).fetchone():
            raise HTTPException(409, "Finaliza la atención antes de pausar la mesa")
        conn.execute("UPDATE desks SET paused=? WHERE id=?", (int(payload.paused), desk_id))
        assign_waiting(conn)
        return {"paused": payload.paused}

