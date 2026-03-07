"""
claude_agent.py — Claude AI agent for the WhatsApp appointment confirmation system.

The agent detects the client's intent (confirm / cancel / reschedule / other)
and returns a tool decision to app.py for execution. Cancel and reschedule
are handled as handoffs to the salon owner — the bot does not modify Calendar.

Public API:
    run(message_text, client, appointment, history, wa_phone, phone_e164) -> dict
        Returns {"tool": str, "input": dict}
"""

import os
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_LOOP_ITERATIONS = 3

SYSTEM_PROMPT = """Eres Vale, la asistente virtual de Time 4 me Nail Salón en Guadalajara, México.

SOBRE EL SALÓN:
- Servicios: manicure, pedicure, nail art, gel, acrílico, depilación
- Horario: lunes a sábado de 10:00 a.m. a 7:00 p.m.
- Zona horaria: America/Mexico_City

TU ESTILO:
- Responde siempre en el mismo tono y nivel de formalidad que usa la clienta
- Usa español mexicano casual si ella lo usa (ella, tú, etc.)
- Sé breve y directa — no des respuestas largas innecesarias
- Nunca reveles que eres un bot; actúa como una persona real del salón

TU ROL:
Google Calendar es la agenda central del salón. La dueña gestiona las citas directamente ahí.
Tu única función es atender los mensajes entrantes de las clientas y detectar su intención
respecto a su cita: confirmar asistencia, cancelar o reagendar.

FLUJOS:

1. CONFIRMAR CITA: Si la clienta confirma que asistirá (dice "sí", "ahí estaré", "confirmo", "ok", etc.)
   → usa confirm_appointment

2. CANCELAR CITA: Si la clienta quiere cancelar
   → usa cancel_appointment
   → NO cancelas nada en Calendar. El equipo del salón lo resolverá.

3. REAGENDAR CITA: Si la clienta quiere cambiar su cita a otro día u hora
   → usa reschedule_appointment
   → NO preguntes por horarios disponibles ni ofrezcas slots.
   → El equipo del salón contactará a la clienta para coordinar el nuevo horario.

4. OTROS / DUDAS: Preguntas sobre precios, pagos, servicios, quejas, fotos, audios, o cualquier
   cosa fuera de los flujos anteriores → usa escalate_to_human

Si el mensaje es ambiguo, puedes enviar un send_message para aclarar la intención antes de ejecutar
una acción. Por ejemplo: si no está claro si quiere cancelar o reagendar, pregunta.

REGLAS:
- Si appointment es null, la clienta no tiene cita próxima registrada; usa escalate_to_human
- Si client es null, es una clienta nueva sin registro; usa escalate_to_human
- Usa el historial de conversación para no repetir preguntas ya respondidas"""


CLAUDE_TOOLS = [
    {
        "name": "confirm_appointment",
        "description": "Marca la cita como confirmada en la base de datos y en Google Calendar. Usa esto cuando la clienta confirma que asistirá.",
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "integer",
                    "description": "El ID de la cita a confirmar (del campo 'id' en el contexto de appointment)"
                },
                "response_message": {
                    "type": "string",
                    "description": "Mensaje personalizado para enviar a la clienta confirmando su cita"
                }
            },
            "required": ["appointment_id", "response_message"]
        }
    },
    {
        "name": "cancel_appointment",
        "description": "La clienta quiere cancelar su cita. El bot notifica a la dueña del salón y le envía el link de contacto a la clienta para que coordinen. NO cancela nada en Calendar automáticamente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "integer",
                    "description": "El ID de la cita que la clienta quiere cancelar"
                },
                "response_message": {
                    "type": "string",
                    "description": "Mensaje breve de confirmación para la clienta antes del handoff (ej. 'Entendido, le avisamos al equipo')"
                }
            },
            "required": ["appointment_id", "response_message"]
        }
    },
    {
        "name": "reschedule_appointment",
        "description": "La clienta quiere reagendar su cita a otro día u hora. El bot notifica a la dueña del salón y le envía el link de contacto a la clienta para que coordinen el nuevo horario. NO preguntes por slots ni muevas nada en Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "integer",
                    "description": "El ID de la cita que la clienta quiere mover"
                },
                "response_message": {
                    "type": "string",
                    "description": "Mensaje breve para la clienta antes del handoff (ej. 'Claro, le avisamos al equipo para coordinar el cambio')"
                }
            },
            "required": ["appointment_id", "response_message"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": "Envía el link de WhatsApp de la dueña a la clienta. Usa esto para preguntas sobre precios, pagos, quejas, mensajes con fotos/audios, o cualquier situación fuera del alcance del bot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "response_message": {
                    "type": "string",
                    "description": "Mensaje breve antes de dar el link (ej. 'Un momento, te comunico con alguien del equipo')"
                }
            },
            "required": ["response_message"]
        }
    },
    {
        "name": "send_message",
        "description": "Envía un mensaje conversacional sin modificar nada. Usa para aclarar la intención de la clienta cuando el mensaje es ambiguo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Texto del mensaje a enviar"
                }
            },
            "required": ["message"]
        }
    },
]


# ── Public API ─────────────────────────────────────────────────────────────────

def run(
    message_text: str,
    client: "dict | None",
    appointment: "dict | None",
    history: list,
    wa_phone: str,
    phone_e164: str,
) -> dict:
    """
    Ask Claude what to do given the current conversation state.

    Returns a dict: {"tool": str, "input": dict}
    The caller (app.py) executes the tool.
    """
    try:
        api_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        context_block = _build_context_block(
            message_text=message_text,
            client=client,
            appointment=appointment,
            history=history,
        )

        messages = [{"role": "user", "content": context_block}]

        for iteration in range(MAX_LOOP_ITERATIONS):
            response = api_client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=CLAUDE_TOOLS,
                tool_choice={"type": "auto"},
                messages=messages,
            )

            logger.debug(f"[claude_agent] iter={iteration} stop_reason={response.stop_reason}")

            if response.stop_reason == "end_turn":
                text = _extract_text(response)
                if text:
                    return {"tool": "send_message", "input": {"message": text}}
                # No text and no tool — fall through to safety fallback
                break

            if response.stop_reason == "tool_use":
                tool_call = _extract_tool_call(response)
                if not tool_call:
                    break

                tool_name = tool_call["name"]
                tool_input = tool_call["input"]
                tool_use_id = tool_call["id"]

                logger.info(f"[claude_agent] Claude chose tool: {tool_name}")

                # All tools are returned to app.py for execution
                return {"tool": tool_name, "input": tool_input}

        # Safety fallback if loop exhausted without resolution
        logger.warning("[claude_agent] Loop exhausted without resolution — escalating")
        return {
            "tool": "escalate_to_human",
            "input": {"response_message": "Un momento, te comunico con alguien del equipo. 😊"}
        }

    except anthropic.APIConnectionError as exc:
        logger.error(f"[claude_agent] API connection error: {exc}")
        return {
            "tool": "send_message",
            "input": {"message": "Disculpa, tuve un problema técnico momentáneo. Por favor intenta en unos minutos."}
        }
    except anthropic.RateLimitError as exc:
        logger.error(f"[claude_agent] Rate limit: {exc}")
        return {
            "tool": "escalate_to_human",
            "input": {"response_message": "En este momento estoy muy ocupada. Un momento y te atiendo."}
        }
    except Exception as exc:
        logger.error(f"[claude_agent] Unexpected error: {exc}", exc_info=True)
        return {
            "tool": "escalate_to_human",
            "input": {"response_message": "Tuve un error inesperado. Un momento, te comunico con alguien."}
        }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_context_block(
    message_text: str,
    client: "dict | None",
    appointment: "dict | None",
    history: list,
) -> str:
    """Build a plain-text context block for Claude to read."""
    lines = []

    lines.append(f"Mensaje actual: \"{message_text}\"")
    lines.append("")

    if client:
        lines.append(f"Cliente: {client['name']} (ID: {client['id']}, tel: {client.get('phone', '')})")
    else:
        lines.append("Cliente: nueva clienta (no registrada aún)")

    if appointment:
        from tools.whatsapp_templates import _format_datetime
        try:
            date_str, time_str = _format_datetime(appointment["start_time"])
            appt_line = (
                f"Cita próxima: {appointment.get('service', 'servicio')} — "
                f"{date_str} a las {time_str} "
                f"(ID: {appointment['id']}, status: {appointment.get('status', '?')})"
            )
        except Exception:
            appt_line = (
                f"Cita próxima: {appointment.get('service', 'servicio')} — "
                f"{appointment.get('start_time', '?')} "
                f"(ID: {appointment['id']}, status: {appointment.get('status', '?')})"
            )
        lines.append(appt_line)
    else:
        lines.append("Cita próxima: ninguna")

    lines.append("")

    if history:
        lines.append("Historial reciente (cronológico):")
        for msg in history:
            prefix = "bot" if msg.get("direction") == "outbound" else "cliente"
            content = msg.get("content", "")
            lines.append(f"  [{prefix}] {content}")
    else:
        lines.append("Historial reciente: ninguno (primer mensaje)")

    return "\n".join(lines)


def _extract_text(response) -> str:
    """Extract the first text block from a response."""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            return block.text.strip()
    return ""


def _extract_tool_call(response) -> "dict | None":
    """Extract the first tool_use block from a response."""
    for block in response.content:
        if block.type == "tool_use":
            return {"id": block.id, "name": block.name, "input": block.input}
    return None


