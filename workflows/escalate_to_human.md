# Workflow: Escalación a Humano

## Objetivo
Conectar al cliente con la dueña del salón cuando el bot no puede resolver
la solicitud: el cliente pide hablar con alguien, quiere reagendar, o envía
un mensaje que el bot no entiende.

## Trigger
`intent_parser` devuelve `'human'`, `'reschedule'`, o `'unknown'`.

## Qué hace el bot

1. **Enviar template al cliente**
   - `whatsapp_templates.human_escalation(client_name, owner_whatsapp)`
   - Template: `time4me_escalacion_humano`
   - El mensaje incluye el link `wa.me/{OWNER_WHATSAPP}` para que el cliente
     contacte directamente a la dueña

2. **Registrar en message_log**
   - `direction='outbound'`, `message_type='human_escalation'`

## Lo que NO hace el bot

- El bot **no** llama a la dueña ni le envía notificación automática
- La dueña recibirá el mensaje porque el cliente le escribe directamente
- Si la dueña quiere recibir alertas internas, esto puede agregarse como mejora futura

## Razones comunes de escalación

| Reason | Intent parseado |
|--------|----------------|
| Cliente escribe "quiero hablar con alguien" | `human` |
| Cliente quiere cambiar fecha/hora | `reschedule` |
| Mensaje completamente ambiguo | `unknown` |
| Cliente envía foto/audio/video | `human` (tipo no manejado) |
| Número desconocido (no en DB) | escalación sin cita asociada |

## Casos borde

| Situación | Manejo |
|-----------|--------|
| `OWNER_WHATSAPP` no configurado | Log error; enviar template igualmente sin el link |
| Cliente escala varias veces seguidas | Cada escalación se loguea; no hay límite — la dueña verá los mensajes repetidos |
| Fuera del horario de atención | El bot igual envía el link; la dueña responde cuando pueda |
