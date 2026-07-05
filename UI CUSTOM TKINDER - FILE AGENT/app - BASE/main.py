"""
main.py — Entry point: bootstrap + run app.

Responsabilidades:
  - Configurar logging
  - Importar y lanzar FileAgentApp
  - Manejar excepciones globales
"""
from __future__ import annotations

import logging
import sys

from .app import FileAgentApp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        app = FileAgentApp()
        app.mainloop()
    except Exception as e:
        logging.exception("Fatal error in FileAgentApp")
        sys.exit(1)


if __name__ == "__main__":
    main()
