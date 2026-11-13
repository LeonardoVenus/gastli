#!/usr/bin/env sh
# Instalador de GASTLI: usa pipx si existe; si no, pip --user.
set -e

REPO="${GASTLI_REPO:-git+https://github.com/LeonardoVenus/gastli}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: se requiere Python 3.8 o superior." >&2
    exit 1
fi

if command -v pipx >/dev/null 2>&1; then
    pipx install --force "$REPO"
else
    python3 -m pip install --user --upgrade "$REPO" \
        || python3 -m pip install --user --upgrade --break-system-packages "$REPO"
    echo "Si 'gastli' no se encuentra, agrega ~/.local/bin a tu PATH."
fi

echo "Listo. Ejecuta: gastli"
