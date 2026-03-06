"""
intent_parser.py — Parse a WhatsApp message to detect client intent.

Handles both structured button payloads (interactive quick-replies)
and freeform text with keyword matching.

Returns one of:
    'confirm' | 'cancel' | 'reschedule' | 'human' | 'book' |
    'upsell_yes' | 'upsell_no' | 'unknown'
"""

import unicodedata
import re


# ── Keyword lists ──────────────────────────────────────────────────────────────
# All lowercase, accent-stripped (normalization strips accents before matching).

CONFIRM_KEYWORDS = {
    "si", "sí", "confirmo", "confirmado", "ok", "okay", "de acuerdo",
    "perfecto", "ahi estare", "ahí estaré", "claro", "va", "dale",
    "listo", "voy", "alli estare", "allí estaré", "por supuesto",
    "con gusto", "ahi voy", "ahí voy",
}

CANCEL_KEYWORDS = {
    "no", "cancelar", "cancelo", "cancelacion", "cancelación",
    "no puedo", "no voy", "no ire", "no iré", "no asistire",
    "no asistiré", "cancela", "borra", "elimina",
}

RESCHEDULE_KEYWORDS = {
    "reagendar", "cambiar", "reprogramar", "otro dia", "otro día",
    "otra hora", "mover", "cambio de fecha", "diferente dia",
}

HUMAN_KEYWORDS = {
    "persona", "humano", "ayuda", "hablar", "llamar", "comunicar",
    "operador", "encargada", "dueña", "duena", "alguien", "staff",
    "empleada", "asesora", "atencion", "atención",
}

UPSELL_YES_KEYWORDS = {
    "si", "sí", "quiero", "me interesa", "agrega", "tambien", "también",
    "añade", "suma", "cotiza", "cotizame", "me apunto", "claro",
    "porfa", "por favor", "va", "dale",
}

UPSELL_NO_KEYWORDS = {
    "no", "no gracias", "esta bien", "está bien", "solo eso",
    "nada mas", "nada más", "no por ahora", "asi esta bien",
    "así está bien", "gracias",
}

BOOK_KEYWORDS = {
    "agendar", "agenda", "cita", "reservar", "reserva",
    "quiero cita", "hacer cita", "nueva cita", "turno",
    "anotar", "apuntar", "programar", "quiero agendar", "pedir cita",
}

# Button payloads sent by the interactive message template
BUTTON_PAYLOADS = {
    "CONFIRM": "confirm",
    "CANCEL": "cancel",
    "HUMAN": "human",
    "RESCHEDULE": "reschedule",
}


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, strip accents, remove punctuation."""
    text = text.lower().strip()
    # Remove accents (NFD decomposes accented chars, then we drop combining marks)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Remove punctuation except spaces
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


def _matches(normalized_text: str, keywords: set[str]) -> bool:
    """True if normalized_text exactly matches any keyword or contains it as a word."""
    if normalized_text in keywords:
        return True
    words = set(normalized_text.split())
    return bool(words & keywords)


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_intent(message: dict, context: str = "reminder") -> str:
    """
    Parse a WhatsApp message dict (as received from the webhook) and return intent.

    Args:
        message: The message object from Meta's webhook payload.
        context: 'reminder' (for confirm/cancel) or 'upsell' (for yes/no).

    Returns:
        Intent string: 'confirm' | 'cancel' | 'reschedule' | 'human' |
                       'upsell_yes' | 'upsell_no' | 'unknown'
    """
    msg_type = message.get("type", "")

    # ── Structured button payload (most reliable) ──────────────────────────────
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply", {})
        payload = reply.get("id", "").upper()
        if payload in BUTTON_PAYLOADS:
            return BUTTON_PAYLOADS[payload]

    # ── Freeform text (fuzzy keyword matching) ─────────────────────────────────
    if msg_type == "text":
        raw = message.get("text", {}).get("body", "")
    else:
        # Unsupported type (image, audio, etc.) → escalate to human
        return "human"

    normalized = _normalize(raw)
    if not normalized:
        return "unknown"

    # Book, human, and reschedule always take priority regardless of context
    if _matches(normalized, BOOK_KEYWORDS):
        return "book"
    if _matches(normalized, HUMAN_KEYWORDS):
        return "human"
    if _matches(normalized, RESCHEDULE_KEYWORDS):
        return "reschedule"

    # In upsell context, check upsell keywords before generic confirm/cancel
    # so that "sí" and "no" resolve to upsell_yes/upsell_no correctly
    if context == "upsell":
        if _matches(normalized, UPSELL_YES_KEYWORDS):
            return "upsell_yes"
        if _matches(normalized, UPSELL_NO_KEYWORDS):
            return "upsell_no"

    if _matches(normalized, CANCEL_KEYWORDS):
        return "cancel"
    if _matches(normalized, CONFIRM_KEYWORDS):
        return "confirm"

    return "unknown"


# ── Slot selection parsing ──────────────────────────────────────────────────────

_TIME_OF_DAY = {
    "manana": (9, 11),
    "mediodia": (12, 13),
    "tarde": (14, 17),
    "noche": (17, 19),
}

_ANY_SLOT_KEYWORDS = {
    "cualquier", "el que sea", "que sea", "antes posible",
    "lo antes", "indiferente", "lo mismo", "cual sea",
}


def parse_preferred_slot(message: dict, slots: list) -> "int | None":
    """
    Mapea preferencia de día/hora en texto libre al mejor slot disponible.
    Devuelve índice, o None si no se detectó preferencia útil.
    """
    if not slots:
        return 0

    if message.get("type") != "text":
        return None

    raw = message.get("text", {}).get("body", "")
    normalized = _normalize(raw)

    if any(kw in normalized for kw in _ANY_SLOT_KEYWORDS):
        return 0

    preferred_weekday: "int | None" = None
    for name, weekday in _DAY_NAMES.items():
        if name in normalized:
            preferred_weekday = weekday
            break

    import datetime as _dt_mod
    import pytz as _pytz
    _TZ = _pytz.timezone("America/Mexico_City")
    today = _dt_mod.datetime.now(_TZ).date()

    preferred_date: "object | None" = None
    if re.search(r"\bmanana\b", normalized) and preferred_weekday is None:
        preferred_date = today + _dt_mod.timedelta(days=1)
    elif "hoy" in normalized:
        preferred_date = today
    elif "pasado" in normalized and "manana" in normalized:
        preferred_date = today + _dt_mod.timedelta(days=2)

    preferred_hour: "int | None" = None
    time_match = re.search(r"las?\s+(\d{1,2})(?::(\d{2}))?(?:\s*(am|pm))?", normalized)
    if time_match:
        h = int(time_match.group(1))
        if time_match.group(3) == "pm" and h < 12:
            h += 12
        elif not time_match.group(3) and h < 8:
            h += 12
        preferred_hour = h
    else:
        for kw, (h_min, h_max) in _TIME_OF_DAY.items():
            if kw in normalized:
                preferred_hour = (h_min + h_max) // 2
                break

    if preferred_weekday is None and preferred_date is None and preferred_hour is None:
        return None

    best_idx = 0
    best_score = float("inf")
    for i, slot in enumerate(slots):
        score = 0.0
        if preferred_date is not None and slot.date() != preferred_date:
            score += 200
        if preferred_weekday is not None and slot.weekday() != preferred_weekday:
            score += 100
        if preferred_hour is not None:
            score += abs(slot.hour - preferred_hour) * 2
        if score < best_score:
            best_score = score
            best_idx = i

    return best_idx


_ORDINALS = {
    "1": 0, "uno": 0, "primero": 0, "primera": 0,
    "2": 1, "dos": 1, "segundo": 1, "segunda": 1,
    "3": 2, "tres": 2, "tercero": 2, "tercera": 2,
    "4": 3, "cuatro": 3, "cuarto": 3, "cuarta": 3,
    "5": 4, "cinco": 4, "quinto": 4, "quinta": 4,
}

_DAY_NAMES = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}


def parse_slot_index(message: dict, slots: list) -> "int | None":
    """
    Intenta hacer match entre un mensaje de WhatsApp y uno de los slots ofrecidos.
    Acepta:
      - Número o ordinal: "1", "el segundo"
      - Día de la semana: "el martes", "martes"
      - Día + hora: "el martes a las 3", "martes 10am"
    Devuelve el índice (0-based) del slot elegido, o None si no se puede determinar.
    """
    if not slots:
        return None

    msg_type = message.get("type", "")

    # Botón de lista interactiva con índice codificado
    if msg_type == "interactive":
        reply = message.get("interactive", {}).get("list_reply", {})
        raw_id = reply.get("id", "")
        if raw_id.startswith("SLOT_"):
            try:
                idx = int(raw_id.split("_")[1])
                if 0 <= idx < len(slots):
                    return idx
            except (ValueError, IndexError):
                pass

    if msg_type != "text":
        return None

    raw = message.get("text", {}).get("body", "")
    normalized = _normalize(raw)

    # Buscar número / ordinal en el texto
    for token in normalized.split():
        if token in _ORDINALS:
            idx = _ORDINALS[token]
            if idx < len(slots):
                return idx

    # Buscar día de la semana
    matched_day: "int | None" = None
    for name, weekday in _DAY_NAMES.items():
        if name in normalized:
            matched_day = weekday
            break

    if matched_day is None:
        return None

    # Buscar hora mencionada (opcional)
    import re
    hour_match = re.search(r"\b(\d{1,2})\s*(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?", normalized)
    mentioned_hour: "int | None" = None
    if hour_match:
        h = int(hour_match.group(1))
        if "pm" in normalized or "p.m" in normalized:
            if h != 12:
                h += 12
        mentioned_hour = h

    # Filtrar slots por día de la semana (y hora si se especificó)
    candidates = [
        (i, s) for i, s in enumerate(slots)
        if s.weekday() == matched_day
    ]
    if not candidates:
        return None

    if mentioned_hour is not None:
        hour_match_slots = [(i, s) for i, s in candidates if s.hour == mentioned_hour]
        if hour_match_slots:
            return hour_match_slots[0][0]

    # Si hay un solo candidato para ese día, elegirlo directamente
    if len(candidates) == 1:
        return candidates[0][0]

    return None
