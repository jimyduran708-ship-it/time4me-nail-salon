# ─────────────────────────────────────────────────────
# Time 4 me Nail Salón — Comandos de desarrollo
# Uso: make <comando>
# ─────────────────────────────────────────────────────

.PHONY: install test run db sync reminders

# Instalar dependencias
install:
	pip install -r requirements.txt

# Correr todos los tests locales (sin APIs externas)
test:
	python tools/smoke_test.py

# Inicializar la base de datos
db:
	python tools/db_init.py

# Correr el servidor Flask en modo desarrollo
run:
	python app.py

# Disparar sync manual del calendario (para probar sin esperar 30 min)
sync:
	python -c "from tools.reminder_scheduler import sync_calendar_to_db; sync_calendar_to_db()"

# Disparar envío manual de recordatorios (para probar)
reminders:
	python -c "from tools.reminder_scheduler import send_reminders; send_reminders()"

# Disparar envío manual de confirmaciones (para probar)
confirmations:
	python -c "from tools.reminder_scheduler import send_booking_confirmations; send_booking_confirmations()"
