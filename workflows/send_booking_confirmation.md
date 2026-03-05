# Workflow: Enviar Confirmación de Cita

## Objetivo
Enviar un mensaje de WhatsApp al cliente dentro de los 15 minutos siguientes
a que se crea o sincroniza una nueva cita en Google Calendar.

## Trigger
APScheduler job `send_booking_confirmations` — corre cada 15 minutos.

## Pasos

1. `db_appointments.get_appointments_needing_confirmation()`
   - Retorna citas con: `status='pending'`, `confirmation_sent_at IS NULL`,
     `client_id IS NOT NULL`, `start_time > now`

2. Para cada cita:
   a. `db_clients.get_client_by_id(client_id)` → obtener nombre y teléfono
   b. `phone_normalizer.to_whatsapp_format(client.phone)` → formato para API
   c. `whatsapp_templates.booking_confirmation(...)` → armar template
   d. `whatsapp_sender.send_template_message(...)` → enviar
   e. `db_appointments.mark_confirmation_sent(appointment_id)` → marcar enviado

## Condiciones para enviar confirmación

- La cita debe tener `client_id` (teléfono del cliente registrado)
- La cita debe ser en el futuro
- No se debe haber enviado confirmación antes (`confirmation_sent_at IS NULL`)
- El appointment status debe ser 'pending'

## Información incluida en la confirmación

- Nombre del cliente
- Servicio (ej: "Uñas acrílicas")
- Fecha en español (ej: "sábado 14 de junio")
- Hora local Mexico City
- Nombre de la estilista
- Dirección del salón

## Casos borde

| Situación | Manejo |
|-----------|--------|
| Cita agendada para el mismo día | Se envía igualmente en < 15 min |
| Falla en el envío | Log de error; se reintenta en el próximo ciclo de 15 min |
| Número de teléfono inválido | Log de warning; `notify_owner_no_phone` alerta a la dueña |
| Template no aprobado aún | Meta devuelve 400; log error; NO lanzar en producción sin aprobación |
