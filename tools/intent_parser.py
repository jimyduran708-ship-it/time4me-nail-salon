"""
intent_parser.py — Parse a WhatsApp message to detect client intent.

Handles both structured button payloads (interactive quick-replies)
and freeform text with keyword matching.

Returns one of:
    'confirm' | 'cancel' | 'reschedule' | 'human' |
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

    # Human and reschedule always take priority regardless of context
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
