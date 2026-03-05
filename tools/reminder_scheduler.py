"""
reminder_scheduler.py — APScheduler job definitions.

Called from app.py on startup. All jobs run in the America/Mexico_City timezone.
Jobs are designed to be idempotent — safe to re-run if interrupted.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)
TZ = pytz.timezone("America/Mexico_City")


# ── Job functions ──────────────────────────────────────────────────────────────

def sync_calendar_to_db() -> None:
    """
    Read upcoming Google Calendar events and upsert into SQLite.
    Handles new appointments, updates, and owner-initiated cancellations.
    """
    from tools.calendar_reader import get_upcoming_events
    from tools.db_appointments import upsert_appointment, update_appointment_status, get_appointment_by_event_id
    from tools.db_clients import get_or_create_client
    from tools.phone_normalizer import normalize_to_e164
    from tools.escalation_handler import notify_owner_no_phone

    logger.info("[scheduler] sync_calendar_to_db: starting")
    try:
        events = get_upcoming_events(hours_ahead=72)
    except Exception as exc:
        logger.error(f"[scheduler] sync_calendar_to_db: failed to read calendar — {exc}")
        return

    for event in events:
        event_id = event["google_event_id"]
        google_status = event.get("status", "confirmed")

        # If Google says this is cancelled, mirror that in our DB
        if google_status == "cancelled":
            existing = get_appointment_by_event_id(event_id)
            if existing and existing["status"] not in ("cancelled",):
                update_appointment_status(existing["id"], "cancelled")
                logger.info(f"[scheduler] Event {event_id} cancelled by owner — updated DB")
            continue

        phone_raw = event.get("phone")
        client_name = event.get("client_name") or "Cliente"
        phone = normalize_to_e164(phone_raw) if phone_raw else None

        client_id = None
        if phone:
            client, created = get_or_create_client(client_name, phone)
            client_id = client["id"]
            if created:
                logger.info(f"[scheduler] New client created: {client_name} ({phone})")
        else:
            notify_owner_no_phone(event_id, event.get("service", ""), event.get("start_time", ""))

        upsert_appointment(
            google_event_id=event_id,
            client_id=client_id,
            service=event.get("service"),
            stylist=event.get("stylist"),
            start_time=event.get("start_time"),
            end_time=event.get("end_time"),
        )

    logger.info(f"[scheduler] sync_calendar_to_db: synced {len(events)} events")


def send_booking_confirmations() -> None:
    """Send WhatsApp confirmation to newly-synced appointments (no confirmation yet)."""
    from tools.db_appointments import get_appointments_needing_confirmation, mark_confirmation_sent
    from tools.db_clients import get_client_by_id
    from tools.whatsapp_sender import send_template_message
    from tools.whatsapp_templates import booking_confirmation
    from tools.phone_normalizer import to_whatsapp_format

    appointments = get_appointments_needing_confirmation()
    logger.info(f"[scheduler] send_booking_confirmations: {len(appointments)} to send")

    for appt in appointments:
        client = get_client_by_id(appt["client_id"])
        if not client:
            continue
        wa_phone = to_whatsapp_format(client["phone"])
        template = booking_confirmation(
            client_name=client["name"],
            service=appt.get("service") or "tu servicio",
            start_time_iso=appt["start_time"],
            stylist=appt.get("stylist") or "tu estilista",
        )
        try:
            send_template_message(
                to=wa_phone,
                template=template,
                appointment_id=appt["id"],
                client_id=client["id"],
            )
            mark_confirmation_sent(appt["id"])
            logger.info(f"[scheduler] Confirmation sent for appointment {appt['id']}")
        except Exception as exc:
            logger.error(f"[scheduler] Failed to send confirmation for appt {appt['id']}: {exc}")


def send_reminders() -> None:
    """Send day-before reminders with interactive confirmation buttons at 9:00 AM."""
    from tools.db_appointments import get_appointments_needing_reminder, mark_reminder_sent
    from tools.db_clients import get_client_by_id
    from tools.whatsapp_sender import send_template_message
    from tools.whatsapp_templates import appointment_reminder
    from tools.phone_normalizer import to_whatsapp_format

    appointments = get_appointments_needing_reminder()
    logger.info(f"[scheduler] send_reminders: {len(appointments)} to send")

    for appt in appointments:
        client = get_client_by_id(appt["client_id"])
        if not client:
            continue
        wa_phone = to_whatsapp_format(client["phone"])
        template = appointment_reminder(
            client_name=client["name"],
            service=appt.get("service") or "tu servicio",
            start_time_iso=appt["start_time"],
            stylist=appt.get("stylist") or "tu estilista",
        )
        try:
            send_template_message(
                to=wa_phone,
                template=template,
                appointment_id=appt["id"],
                client_id=client["id"],
            )
            mark_reminder_sent(appt["id"])
            logger.info(f"[scheduler] Reminder sent for appointment {appt['id']}")
        except Exception as exc:
            logger.error(f"[scheduler] Failed to send reminder for appt {appt['id']}: {exc}")


def send_upsell_prompts() -> None:
    """Send upsell prompt at 9:30 AM (30 min after reminders)."""
    from tools.db_appointments import get_appointments_needing_upsell, mark_upsell_sent
    from tools.db_clients import get_client_by_id
    from tools.whatsapp_sender import send_template_message
    from tools.whatsapp_templates import upsell_prompt
    from tools.phone_normalizer import to_whatsapp_format

    appointments = get_appointments_needing_upsell()
    logger.info(f"[scheduler] send_upsell_prompts: {len(appointments)} to send")

    for appt in appointments:
        client = get_client_by_id(appt["client_id"])
        if not client:
            continue
        wa_phone = to_whatsapp_format(client["phone"])
        template = upsell_prompt(client_name=client["name"])
        try:
            send_template_message(
                to=wa_phone,
                template=template,
                appointment_id=appt["id"],
                client_id=client["id"],
            )
            mark_upsell_sent(appt["id"])
            logger.info(f"[scheduler] Upsell sent for appointment {appt['id']}")
        except Exception as exc:
            logger.error(f"[scheduler] Failed to send upsell for appt {appt['id']}: {exc}")


def mark_no_shows() -> None:
    """Mark past appointments without a completion status as no_show."""
    from tools.db_appointments import get_no_show_candidates, update_appointment_status, get_appointment_by_id
    from tools.db_clients import get_client_by_id
    from tools.calendar_writer import mark_no_show
    from tools.whatsapp_sender import send_template_message
    from tools.whatsapp_templates import no_show_followup
    from tools.phone_normalizer import to_whatsapp_format

    candidates = get_no_show_candidates()
    logger.info(f"[scheduler] mark_no_shows: {len(candidates)} candidates")

    for appt in candidates:
        update_appointment_status(appt["id"], "no_show")
        try:
            mark_no_show(appt["google_event_id"])
        except Exception as exc:
            logger.warning(f"[scheduler] Could not label no_show in Calendar: {exc}")

        client = get_client_by_id(appt["client_id"]) if appt.get("client_id") else None
        if client:
            wa_phone = to_whatsapp_format(client["phone"])
            template = no_show_followup(client_name=client["name"])
            try:
                send_template_message(
                    to=wa_phone,
                    template=template,
                    appointment_id=appt["id"],
                    client_id=client["id"],
                )
            except Exception as exc:
                logger.error(f"[scheduler] Failed to send no_show followup for appt {appt['id']}: {exc}")

        logger.info(f"[scheduler] Appointment {appt['id']} marked as no_show")


# ── Scheduler setup ────────────────────────────────────────────────────────────

def create_scheduler() -> BackgroundScheduler:
    """
    Build and return a configured APScheduler instance.
    Call scheduler.start() from app.py after Flask app is ready.
    """
    scheduler = BackgroundScheduler(timezone=TZ)

    # Sync calendar every 30 minutes
    scheduler.add_job(
        sync_calendar_to_db,
        trigger="interval",
        minutes=30,
        id="sync_calendar",
        replace_existing=True,
    )

    # Check for unconfirmed appointments every 15 minutes
    scheduler.add_job(
        send_booking_confirmations,
        trigger="interval",
        minutes=15,
        id="send_confirmations",
        replace_existing=True,
    )

    # Reminders: daily at 9:00 AM Mexico City time
    scheduler.add_job(
        send_reminders,
        trigger=CronTrigger(hour=9, minute=0, timezone=TZ),
        id="send_reminders",
        replace_existing=True,
    )

    # Upsell: daily at 9:30 AM Mexico City time
    scheduler.add_job(
        send_upsell_prompts,
        trigger=CronTrigger(hour=9, minute=30, timezone=TZ),
        id="send_upsell",
        replace_existing=True,
    )

    # No-show marking: daily at 8:00 PM Mexico City time
    scheduler.add_job(
        mark_no_shows,
        trigger=CronTrigger(hour=20, minute=0, timezone=TZ),
        id="mark_no_shows",
        replace_existing=True,
    )

    return scheduler
