"""
db_appointments.py — Appointment CRUD and state machine.

Valid statuses: pending | confirmed | cancelled | completed | no_show
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from tools.db_init import get_connection


# ── Read ──────────────────────────────────────────────────────────────────────

def get_appointment_by_event_id(google_event_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM appointments WHERE google_event_id = ?",
            (google_event_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_appointment_by_id(appointment_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_latest_appointment_for_client(client_id: int) -> Optional[dict]:
    """Most recent upcoming appointment for a client (for webhook routing)."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM appointments
            WHERE client_id = ?
              AND start_time >= ?
              AND status NOT IN ('cancelled', 'completed', 'no_show')
            ORDER BY start_time ASC
            LIMIT 1
            """,
            (client_id, now),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_appointments_needing_confirmation() -> list[dict]:
    """Pending appointments with no confirmation sent yet, in the future."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM appointments
            WHERE status = 'pending'
              AND confirmation_sent_at IS NULL
              AND client_id IS NOT NULL
              AND start_time > ?
            ORDER BY start_time ASC
            """,
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_appointments_needing_reminder() -> list[dict]:
    """
    Appointments that start tomorrow (calendar day in UTC) and
    have not yet received a reminder.
    """
    tomorrow_start = (datetime.utcnow() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    tomorrow_end = tomorrow_start + timedelta(days=1)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM appointments
            WHERE status IN ('pending', 'confirmed')
              AND reminder_sent_at IS NULL
              AND client_id IS NOT NULL
              AND start_time >= ?
              AND start_time < ?
            ORDER BY start_time ASC
            """,
            (tomorrow_start.isoformat(), tomorrow_end.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_appointments_needing_upsell() -> list[dict]:
    """Appointments tomorrow with reminder sent but no upsell yet."""
    tomorrow_start = (datetime.utcnow() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    tomorrow_end = tomorrow_start + timedelta(days=1)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM appointments
            WHERE status IN ('pending', 'confirmed')
              AND reminder_sent_at IS NOT NULL
              AND upsell_sent_at IS NULL
              AND client_id IS NOT NULL
              AND start_time >= ?
              AND start_time < ?
            ORDER BY start_time ASC
            """,
            (tomorrow_start.isoformat(), tomorrow_end.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_no_show_candidates() -> list[dict]:
    """Appointments that ended in the past but are still pending/confirmed."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM appointments
            WHERE status IN ('pending', 'confirmed')
              AND end_time < ?
            ORDER BY end_time ASC
            """,
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert_appointment(google_event_id: str, **fields) -> dict:
    """
    Insert or update an appointment by google_event_id.
    Creates the record if it doesn't exist; updates mutable fields if it does.
    """
    allowed = {
        "client_id", "service", "stylist",
        "start_time", "end_time", "status",
    }
    data = {k: v for k, v in fields.items() if k in allowed}
    data["updated_at"] = datetime.utcnow().isoformat()

    existing = get_appointment_by_event_id(google_event_id)
    conn = get_connection()
    try:
        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in data)
            values = list(data.values()) + [google_event_id]
            conn.execute(
                f"UPDATE appointments SET {set_clause} WHERE google_event_id = ?",
                values,
            )
        else:
            data["google_event_id"] = google_event_id
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            conn.execute(
                f"INSERT INTO appointments ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
        conn.commit()
        return get_appointment_by_event_id(google_event_id)
    finally:
        conn.close()


def update_appointment_status(appointment_id: int, status: str) -> None:
    valid = {"pending", "confirmed", "cancelled", "completed", "no_show"}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}. Must be one of {valid}")
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, appointment_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_confirmation_sent(appointment_id: int) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appointments SET confirmation_sent_at = ?, updated_at = ? WHERE id = ?",
            (now, now, appointment_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_reminder_sent(appointment_id: int) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appointments SET reminder_sent_at = ?, updated_at = ? WHERE id = ?",
            (now, now, appointment_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_upsell_sent(appointment_id: int) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appointments SET upsell_sent_at = ?, updated_at = ? WHERE id = ?",
            (now, now, appointment_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_client_response(appointment_id: int, response: str) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appointments SET client_response = ?, updated_at = ? WHERE id = ?",
            (response, now, appointment_id),
        )
        conn.commit()
    finally:
        conn.close()
