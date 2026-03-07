"""
db_clients.py — Client CRUD operations against SQLite.

All phones stored in E.164 format (e.g. +523312345678).
"""

import sqlite3
from datetime import datetime
from typing import Optional
from tools.db_init import get_connection


# ── Read ──────────────────────────────────────────────────────────────────────

def get_client_by_phone(phone: str) -> Optional[dict]:
    """Return client dict or None if not found."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM clients WHERE phone = ?", (phone,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_client_by_id(client_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def search_clients_by_name(name: str) -> list[dict]:
    """Case-insensitive partial match. Useful for dedup checks."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM clients WHERE LOWER(name) LIKE ?",
            (f"%{name.lower()}%",)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Write ─────────────────────────────────────────────────────────────────────

def create_client(name: str, phone: str, notes: str = "") -> dict:
    """Insert a new client. Raises sqlite3.IntegrityError if phone already exists."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO clients (name, phone, notes) VALUES (?, ?, ?)",
            (name.strip(), phone.strip(), notes),
        )
        conn.commit()
        return get_client_by_id(cur.lastrowid)
    finally:
        conn.close()


def update_client(client_id: int, **fields) -> Optional[dict]:
    """Update arbitrary fields on a client record."""
    allowed = {"name", "phone", "notes", "last_visit"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_client_by_id(client_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [client_id]
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE clients SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return get_client_by_id(client_id)
    finally:
        conn.close()


def get_or_create_client(name: str, phone: str) -> tuple[dict, bool]:
    """
    Look up client by phone. Create if not found.
    If found and name differs, update it from Calendar.
    Returns (client_dict, was_created).
    """
    existing = get_client_by_phone(phone)
    if existing:
        if name and existing["name"] != name:
            existing = update_client(existing["id"], name=name)
        return existing, False
    client = create_client(name, phone)
    return client, True


def record_visit(client_id: int) -> None:
    """Update last_visit to now."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE clients SET last_visit = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), client_id),
        )
        conn.commit()
    finally:
        conn.close()
