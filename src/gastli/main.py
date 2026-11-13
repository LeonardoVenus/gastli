"""Punto de entrada de GASTLI (comando `gastli`)."""
import sys


def main():
    if sys.version_info < (3, 8):
        print("Error: se requiere Python 3.8 o superior.", file=sys.stderr)
        print(f"Versión detectada: {sys.version}", file=sys.stderr)
        sys.exit(1)

    try:
        import curses  # noqa: F401
        import sqlite3  # noqa: F401
        import xml.etree.ElementTree  # noqa: F401
        import zipfile  # noqa: F401
    except ImportError as e:
        print(f"Error: falta un módulo estándar de Python: {e}", file=sys.stderr)
        if sys.platform == "win32":
            print("En Windows instala 'windows-curses' (pip install windows-curses).", file=sys.stderr)
        sys.exit(1)

    from gastli.cli import ejecutar_cli
    from gastli.core import FinanceCore
    from gastli.db import Database

    db = Database()
    core = FinanceCore(db)

    # Respaldo automático al iniciar
    try:
        db.realizar_respaldo()
    except Exception:
        pass

    if len(sys.argv) > 1:
        # Modo línea de comando no interactivo
        sys.exit(ejecutar_cli(core, sys.argv[1:]))

    # Modo interactivo (TUI)
    if not sys.stdin.isatty():
        print("Aviso: la entrada estándar no es un terminal interactivo.", file=sys.stderr)
        print("Ejecuta 'gastli --help' para ver los comandos disponibles en scripts.", file=sys.stderr)
        sys.exit(1)

    from gastli.tui.app import iniciar_tui

    try:
        iniciar_tui(core)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
