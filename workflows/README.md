# Workflows

SOPs (Standard Operating Procedures) en Markdown. Cada workflow le dice al agente **qué hacer y cómo hacerlo** para una tarea específica.

## Convenciones

Cada archivo `nombre_tarea.md` sigue esta estructura:

```markdown
# Nombre del Workflow

## Objetivo
Qué produce este workflow y para qué sirve.

## Inputs requeridos
- `variable_1`: descripción
- `variable_2`: descripción

## Pasos
1. [Descripción del paso] → ejecutar `tools/nombre_script.py --arg valor`
2. ...

## Output esperado
Qué devuelve o dónde se guarda el resultado.

## Manejo de errores
- Error conocido X → acción correctiva Y
- Límite de rate → esperar N segundos y reintentar

## Notas
Restricciones, quirks de APIs, aprendizajes del uso real.
```

## Principios

- **Siempre referenciar tools por nombre**, no escribir código inline
- **Actualizar cuando aprendes algo nuevo**: límites de rate, endpoints mejores, comportamientos inesperados
- **No crear workflows sin pedirlo explícitamente**

## Workflows disponibles

| Archivo | Descripción |
|---------|-------------|
| *(ninguno aún)* | |
