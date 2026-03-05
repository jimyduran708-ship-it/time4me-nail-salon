# Workflow: Manejo de Respuesta del Cliente

## Objetivo
Procesar un mensaje entrante de WhatsApp y tomar la acción correcta:
confirmar, cancelar, reagendar, escalar a humano, o registrar respuesta de upsell.

## Trigger
`POST /webhook` recibe un nuevo mensaje de WhatsApp (evento `messages`).

## Flujo

```
Webhook POST
  → extraer sender_phone + message + message_id
  → verificar dedup en message_log (ignorar si ya procesado)
  → normalizar phone a E.164
  → buscar cliente en DB por phone
      ├── no encontrado → escalar a humano ("cliente desconocido")
      └── encontrado → continuar
  → obtener cita próxima del cliente
  → determinar contexto (reminder vs upsell)
  → parse_intent(message, context)
  → enrutar por intent (ver tabla abajo)
  → registrar mensaje en message_log
  → return 200 (procesamiento en background thread)
```

## Tabla de routing por intent

| Intent | Acción |
|--------|--------|
| `confirm` | Actualizar status='confirmed' + label [CONFIRMADO] en Calendar + responder "¡Perfecto!" |
| `cancel` | Ejecutar workflow: process_cancellation.md |
| `reschedule` | Escalar a humano (la dueña reagenda manualmente) |
| `human` | Enviar número de la dueña al cliente |
| `upsell_yes` | Registrar `client_response='upsell_accepted'` en appointment |
| `upsell_no` | Registrar `client_response='upsell_declined'` en appointment |
| `unknown` | Escalar a humano automáticamente |

## Determinación de contexto para intent_parser

- Si `upsell_sent_at IS NOT NULL` y `client_response IS NULL`:
  → contexto = `'upsell'` (interpreta "sí"/"no" como respuesta al upsell)
- En cualquier otro caso:
  → contexto = `'reminder'`

## Dedup de mensajes

Antes de procesar, verificar `message_log` por `whatsapp_message_id`.
Si ya existe → retornar 200 sin hacer nada.
Meta garantiza at-least-once delivery; esto previene duplicados.

## Casos borde

| Situación | Manejo |
|-----------|--------|
| Mensaje de tipo imagen/audio/video | intent='human' automáticamente |
| Cliente sin cita próxima | Escalar a humano (no hay contexto para confirmar/cancelar) |
| Respuesta ambigua post-cancelación | Ignorar (appointment ya en status=cancelled) |
| Texto completamente irreconocible | intent='unknown' → escalar a humano |
