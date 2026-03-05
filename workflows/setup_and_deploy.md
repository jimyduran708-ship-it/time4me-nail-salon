# Workflow: Setup y Deploy — Time 4 me Nail Salón

## Objetivo
Configurar y desplegar el sistema de recordatorios de WhatsApp desde cero.
Seguir los pasos en orden; cada fase debe completarse antes de pasar a la siguiente.

---

## Fase 1 — Google Cloud (Cuenta de Servicio + Calendar)

### 1.1 Crear proyecto en Google Cloud
1. Ir a [console.cloud.google.com](https://console.cloud.google.com)
2. Crear nuevo proyecto: `time4me-nail-salon`
3. Habilitar la **Google Calendar API**:
   - APIs & Services → Library → buscar "Google Calendar API" → Habilitar

### 1.2 Crear cuenta de servicio
1. IAM & Admin → Service Accounts → Create Service Account
   - Nombre: `salon-bot`
   - Role: no es necesario asignar role al proyecto
2. Una vez creada, ir a la cuenta → Keys → Add Key → JSON
3. Descargar el archivo JSON y guardarlo como `service_account.json` en la raíz del proyecto
4. **Nunca subas este archivo a git** (ya está en `.gitignore`)

### 1.3 Crear y compartir el Google Calendar
1. Abrir [calendar.google.com](https://calendar.google.com)
2. Crear un nuevo calendario: "Time 4 me — Citas"
3. Configuración del calendario → Compartir con personas específicas
   - Agregar el email de la cuenta de servicio (termina en `@...gserviceaccount.com`)
   - Permiso: **Modificar eventos**
4. Configuración → ID del calendario → copiar el ID (termina en `@group.calendar.google.com`)
5. Pegar en `.env` como `GOOGLE_CALENDAR_ID`

---

## Fase 2 — Meta WhatsApp Business

### 2.1 Crear cuenta de Meta Business Manager
1. Ir a [business.facebook.com](https://business.facebook.com)
2. Crear cuenta para el negocio
3. Verificar el negocio (puede tomar 1-2 días)

### 2.2 Registrar número de WhatsApp Business
> El salón necesita un número de teléfono nuevo dedicado al negocio.
> Opciones: número mexicano virtual (ej. Telcel/AT&T) o VoIP (ej. Twilio voice number).

1. En Meta Business Manager → WhatsApp → Números de teléfono → Agregar
2. Seguir el proceso de verificación del número (código SMS o llamada)
3. Una vez verificado, el número aparecerá en Meta for Developers

### 2.3 Crear App en Meta for Developers
1. Ir a [developers.facebook.com](https://developers.facebook.com)
2. Create App → Business → agregar producto **WhatsApp**
3. En WhatsApp → Configuración de API:
   - Copiar **Phone Number ID** → pegar en `.env` como `WHATSAPP_PHONE_NUMBER_ID`
   - Copiar **WhatsApp Business Account ID** → pegar en `.env` como `WHATSAPP_BUSINESS_ACCOUNT_ID`
4. Generar token de acceso permanente:
   - Business Settings → System Users → Add → Admin
   - Asignar el WABA y el número a este system user
   - Generate Token (no expira) → pegar en `.env` como `WHATSAPP_ACCESS_TOKEN`

### 2.4 Inventar y guardar el Verify Token
- Crear un string aleatorio (ej. `salon_webhook_2026_xyz`)
- Pegar en `.env` como `WHATSAPP_VERIFY_TOKEN`

### 2.5 Someter los templates para aprobación
Ir a Meta Business Manager → WhatsApp → Templates → Create Template

Someter los siguientes templates (copiar texto exacto del plan):
1. `time4me_confirmacion_cita` — categoría: Utility
2. `time4me_recordatorio_cita` — categoría: Utility (con botones interactivos)
3. `time4me_cancelacion_confirmada` — categoría: Utility
4. `time4me_upsell_servicios` — categoría: Marketing
5. `time4me_noshow_reagendar` — categoría: Utility
6. `time4me_escalacion_humano` — categoría: Utility

> ⚠️ La aprobación toma 24-48 horas. NO lanzar con clientes reales hasta que todos estén aprobados.

---

## Fase 3 — Railway.app

### 3.1 Crear cuenta y proyecto
1. Ir a [railway.app](https://railway.app) → Sign up con GitHub
2. New Project → Deploy from GitHub repo
3. Seleccionar el repositorio del proyecto

### 3.2 Agregar variables de entorno en Railway
En el proyecto → Variables → agregar todas las variables del `.env`:
- `GOOGLE_CALENDAR_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON` → **NO pegar ruta**, pegar el contenido JSON completo como variable
  (Railway permite values multi-línea)
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_BUSINESS_ACCOUNT_ID`
- `OWNER_WHATSAPP`
- `DATABASE_PATH` → `/data/salon.db`
- `PORT` → `8080`

### 3.3 Configurar el volumen de datos
En Railway → tu servicio → Volumes → Add Volume
- Mount Path: `/data`
- Esto persiste la base de datos SQLite entre deploys y reinicios

### 3.4 Desplegar y verificar
1. Railway hace deploy automático al hacer push a main
2. Verificar que el health check `/health` responde 200
3. Copiar la URL pública del servicio (ej. `https://time4me-bot.railway.app`)

---

## Fase 4 — Conectar Webhook de Meta

1. En Meta for Developers → tu app → WhatsApp → Configuración
2. Webhook URL: `https://time4me-bot.railway.app/webhook`
3. Verify Token: el mismo string que pusiste en `WHATSAPP_VERIFY_TOKEN`
4. Click "Verify and Save"
5. Suscribirse a: `messages` y `message_status_updates`

Si la verificación falla:
- Confirmar que el servidor está corriendo (Railway → Logs)
- Confirmar que `WHATSAPP_VERIFY_TOKEN` en Railway coincide con el que pusiste en Meta

---

## Fase 5 — Prueba End-to-End

### Prueba 1: Confirmación de cita
1. Crear evento en Google Calendar con formato:
   - Título: `Uñas acrílicas - Carmen`
   - Descripción:
     ```
     Cliente: Test Cliente
     Teléfono: [tu número de teléfono personal]
     ```
2. Esperar hasta 15 minutos → debes recibir el mensaje de confirmación en WhatsApp

### Prueba 2: Recordatorio con botones
1. Crear evento para mañana
2. Disparar el job manualmente o esperar las 9:00 AM
3. Verificar que recibes el mensaje con 3 botones

### Prueba 3: Confirmar
- Presionar el botón "Confirmar ✅"
- Verificar en Google Calendar que el título ahora dice `[CONFIRMADO]`

### Prueba 4: Cancelar
- Presionar el botón "Cancelar ❌"
- Verificar que el evento se cancela en Calendar
- Verificar que la dueña recibe notificación en WhatsApp

### Prueba 5: Hablar con alguien
- Presionar "Hablar con alguien 💬"
- Verificar que recibes el link de WhatsApp de la dueña

---

## Convención de Eventos en Google Calendar

Todo el equipo que agenda citas debe seguir este formato exacto:

**Título del evento:**
```
[Servicio] - [Nombre de estilista]
```
Ejemplos: `Uñas acrílicas - Carmen`, `Pedicure spa - Ana`

**Descripción del evento:**
```
Cliente: [Nombre completo del cliente]
Teléfono: [Número con código de país, ej: +523312345678]
Notas: [opcional — alergias, preferencias, etc.]
```

> Si el campo "Teléfono" falta o tiene formato incorrecto, la dueña recibirá una alerta
> por WhatsApp para que lo corrija antes del recordatorio.

---

## Política de Confirmación (comunicar a la dueña)

| Situación | Lo que hace el bot |
|-----------|-------------------|
| Cita agendada | Confirmación vía WhatsApp en < 15 min |
| Día anterior 9:00 AM | Recordatorio con botones de confirmar/cancelar |
| Día anterior 9:30 AM | Pregunta si quieren agregar servicio adicional |
| Sin respuesta al recordatorio | Cita permanece; la dueña puede decidir si llama |
| Cancela antes de 24h | Bot cancela el evento, avisa a la dueña |
| Cancela con menos de 24h | Bot cancela igual; queda registrado en historial |
| No show | Marcado en historial; bot envía mensaje de reagenda |
| Pide hablar con alguien | Bot envía número de la dueña al cliente |

---

## Troubleshooting

**El bot no envía mensajes:**
- Verificar que los templates están aprobados en Meta
- Revisar logs en Railway → tu servicio → Logs
- Verificar que `WHATSAPP_ACCESS_TOKEN` no expiró

**El webhook no recibe mensajes:**
- Verificar URL y token en Meta for Developers → Webhook
- Confirmar que el servidor responde 200 en `/webhook` GET

**La base de datos se pierde entre deploys:**
- Confirmar que el volumen `/data` está configurado en Railway
- `DATABASE_PATH` debe ser `/data/salon.db` en producción

**No sincroniza eventos del calendario:**
- Verificar que la cuenta de servicio está invitada al calendario con permiso de modificación
- Verificar que `GOOGLE_CALENDAR_ID` es correcto
- Revisar Railway Logs por errores de autenticación de Google
