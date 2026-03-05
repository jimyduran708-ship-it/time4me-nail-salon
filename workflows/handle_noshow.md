# Workflow: Manejo de No-Show

## Objetivo
Detectar citas que pasaron sin que el cliente se presentara, marcarlas en el sistema,
actualizar Google Calendar, y enviar un mensaje de seguimiento para ofrecer reagendar.

## Trigger
APScheduler job `mark_no_shows` — corre diario a las 8:00 PM hora México.

## Pasos

1. `db_appointments.get_no_show_candidates()`
   - Citas donde `end_time < ahora` y `status IN ('pending', 'confirmed')`
   - Estas son citas que ya terminaron pero nunca fueron marcadas como completadas

2. Para cada candidato:
   a. `db_appointments.update_appointment_status(id, 'no_show')`
   b. `calendar_writer.mark_no_show(google_event_id)` → agrega label [NO SHOW] en Calendar
   c. Si el cliente tiene teléfono:
      - `whatsapp_templates.no_show_followup(client_name)` → armar template
      - `whatsapp_sender.send_template_message(...)` → enviar

## Mensaje de no-show

El mensaje es amigable, sin confrontación:
- NO menciona que "no llegaste"
- Dice que "no pudimos verte" y ofrece reagendar
- Incluye horarios del salón para facilitar el contacto

## Registro histórico

El status `no_show` queda en SQLite para que la dueña pueda:
- Ver qué clientes no se presentan frecuentemente
- Tomar decisiones sobre política de confirmación obligatoria

## Casos borde

| Situación | Manejo |
|-----------|--------|
| Cita completada pero no marcada (cliente llegó pero se olvidó confirmar en Calendar) | Marcada como no_show por el sistema. La dueña puede corregir manualmente el status si aplica |
| Falla al etiquetar en Calendar | Log warning; status en SQLite ya fue actualizado — continúa |
| Falla al enviar mensaje | Log error; no_show ya marcado en DB |
| Cliente cancela tarde (mismo día) pero el job ya corrió | La cancelación tiene precedencia; el job ya habrá marcado no_show primero — aceptable |
