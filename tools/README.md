# Tools

Scripts Python para ejecución determinista. Cada script hace **una sola cosa** y la hace bien.

## Convenciones

- **Entradas**: Argumentos CLI (`argparse`) o stdin
- **Salidas**: JSON o texto plano a stdout
- **Errores**: Mensajes a stderr, código de salida no-cero en fallo
- **Sin lógica de negocio**: Solo ejecución. La orquestación es tarea del agente.
- **Credenciales**: Leer desde `.env` vía `python-dotenv`

## Estructura de un script

```python
#!/usr/bin/env python3
"""Una línea describiendo qué hace este script."""

import argparse
import json
import sys
from dotenv import load_dotenv

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="...")
    args = parser.parse_args()

    # ... lógica ...

    print(json.dumps(result))

if __name__ == "__main__":
    main()
```

## Scripts disponibles

| Script | Descripción | Inputs |
|--------|-------------|--------|
| *(ninguno aún)* | | |
