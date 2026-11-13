"""Rutas de datos del usuario (multiplataforma).

Los datos viven fuera del código, en un directorio propio del usuario:

- Linux:   ~/.local/share/gastli   (respeta XDG_DATA_HOME)
- macOS:   ~/Library/Application Support/gastli
- Windows: %APPDATA%\\gastli

Se puede cambiar con la variable de entorno GASTLI_HOME.
"""
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("GASTLI_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "gastli"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "gastli"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "gastli"


def db_path() -> str:
    return str(data_dir() / "finanzas.db")


def backups_dir() -> str:
    return str(data_dir() / "backups")


def exports_dir() -> str:
    return str(data_dir() / "exports")
