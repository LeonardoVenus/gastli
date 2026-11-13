"""Exportador ligero a formato CSV."""
import csv
import os
from typing import Optional

from gastli.core import FinanceCore


class CsvExporter:
    def __init__(self, core: FinanceCore):
        self.core = core
        self.db = core.db

    def exportar_movimientos(self, ruta_destino: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)
        movs = self.db.get_movimientos()
        with open(ruta_destino, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ID",
                    "Fecha",
                    "Tipo",
                    "Cuenta Origen",
                    "Cuenta Destino",
                    "Categoría",
                    "Nota",
                    "Monto Centavos",
                    "Monto Decimal",
                ]
            )
            for m in movs:
                writer.writerow(
                    [
                        m.id,
                        m.fecha,
                        m.tipo,
                        m.cuenta_origen_nombre,
                        m.cuenta_destino_nombre,
                        m.categoria_nombre,
                        m.nota,
                        m.monto_centavos,
                        f"{m.monto_centavos / 100.0:.2f}",
                    ]
                )
        return ruta_destino
