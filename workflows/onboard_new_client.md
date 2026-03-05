# Workflow: Onboarding de Nuevo Cliente

## Objetivo
Documentar cómo el equipo del salón debe registrar correctamente una cita nueva
en Google Calendar para que el bot pueda procesarla automáticamente.

## Quién lo hace
El personal del salón (recepcionista o dueña) — manualmente en Google Calendar.

## Formato de evento (obligatorio)

### Título del evento
```
[Servicio] - [Nombre de estilista]
```

Ejemplos válidos:
- `Uñas acrílicas - Carmen`
- `Pedicure spa - Ana`
- `Esmaltado semipermanente - Diana`

Si no se sabe la estilista al momento:
- `Uñas acrílicas - Por asignar`

### Descripción del evento
```
Cliente: [Nombre completo]
Teléfono: [Número con código de país]
Notas: [opcional]
```

Ejemplos de teléfono válidos:
- `+523312345678` (México con código de país — preferido)
- `3312345678` (el sistema lo normaliza a México automáticamente)
- `+15551234567` (extranjero — incluir código de país)

### Ejemplo completo
```
Título: Uñas acrílicas - Carmen
Inicio: 15/06/2026 10:00 AM
Fin:    15/06/2026 11:30 AM

Descripción:
Cliente: María González
Teléfono: +523312345678
Notas: Alergia a acrílicos, usar gel
```

## Qué pasa después (automático)

1. El bot sincroniza el evento en < 30 minutos
2. Busca el teléfono en la base de datos:
   - Si es nuevo: crea perfil de cliente automáticamente
   - Si ya existe: lo vincula a la cita
3. En < 15 minutos después de la sync: envía confirmación por WhatsApp

## Errores comunes a evitar

| Error | Consecuencia | Solución |
|-------|-------------|---------|
| No poner teléfono en descripción | Bot no puede enviar mensaje; dueña recibe alerta | Agregar teléfono al evento |
| Formato incorrecto: "Tel: 33-1234-5678" | Bot no parsea el número | Usar formato `Teléfono: +523312345678` |
| Título sin " - " | Bot registra todo como servicio, sin estilista | Separar con ` - ` |
| Evento de todo el día (sin hora) | Bot no puede determinar horario exacto | Siempre usar hora de inicio y fin |

## Clientes recurrentes

Para clientes que ya tienen perfil en la base de datos:
- El sistema los reconoce automáticamente por teléfono
- El historial de visitas se actualiza solo
- No es necesario hacer nada diferente en Calendar

## Clientes extranjeros

- Siempre incluir código de país en el teléfono
- Ejemplos: `+15551234567` (USA), `+34612345678` (España)
- Todos los mensajes se envían en español (política actual del salón)
