# Workflow: Procesar Cancelación

## Objetivo
Cancelar una cita en el sistema cuando el cliente lo solicita por WhatsApp,
liberar el slot en Google Calendar, notificar a la dueña, y ofrecer reagendar.

## Trigger
`intent_parser` devuelve `'cancel'` para el mensaje de un cliente.

## Pasos

1. **Actualizar estado en SQLite**
   - `db_appointments.update_appointment_status(appointment_id, 'cancelled')`

2. **Cancelar en Google Calendar**
   - `calendar_writer.mark_cancelled(google_event_id)`
   - Esto: cancela el evento Y agrega label [CANCELADO] al título
   - El evento NO se borra — queda en Calendar como registro histórico

3. **Notificar a la dueña**
   - `escalation_handler.notify_owner_cancellation(appointment, client)`
   - La dueña recibe un WhatsApp con datos de la cita cancelada
   - Puede decidir si intenta rellenar el slot o no

4. **Confirmar cancelación al cliente**
   - `whatsapp_sender.send_template_message(template=cancellation_confirmed(...))`
   - Template: `time4me_cancelacion_confirmada`
   - Incluye oferta de reagendar

## Registro en historial

Si la cancelación ocurre con **menos de 24h de anticipación**, agregar nota en client.notes:
```
[2026-03-15] Cancelación tardía (<24h) — Uñas acrílicas 10:00am
```
Esto queda visible para la dueña y puede informar decisiones de política futura.

## Casos borde

| Situación | Manejo |
|-----------|--------|
| Evento ya cancelado en Calendar | `calendar_writer.mark_cancelled` es idempotente — continúa sin error |
| Appointment no encontrado | Log de warning; responder igualmente con texto de cancelación |
| Falla al notificar a dueña | Log error; la cancelación en DB y Calendar ya está hecha |
| Cliente cancela y quiere reagendar en el mismo mensaje | Escalar a humano para que la dueña ofrezca alternativas |
