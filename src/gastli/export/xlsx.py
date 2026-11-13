"""Generador nativo de libros Excel (.xlsx) usando únicamente zipfile y XML estándar."""
import os
import zipfile
from datetime import date, datetime
from typing import Any, List, Optional, Tuple
from xml.sax.saxutils import escape

from gastli.core import FinanceCore
from gastli.db import Database
from gastli.models import TipoCuenta, TipoMovimiento


def _col_letter(col_idx: int) -> str:
    """Convierte un índice de columna 1-based (1=A, 2=B, etc.) a letra de Excel."""
    res = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        res = chr(65 + remainder) + res
    return res


class SheetBuilder:
    def __init__(self, name: str):
        self.name = name
        self.rows: List[List[Tuple[Any, int]]] = []  # (valor, style_id)
        self.col_widths: List[int] = []

    def add_row(self, cells: List[Tuple[Any, int]]):
        self.rows.append(cells)
        for idx, (val, _) in enumerate(cells):
            s_val = str(val if val is not None else "")
            longitud = max(len(s_val) + 4, 12)
            if idx >= len(self.col_widths):
                self.col_widths.append(longitud)
            else:
                self.col_widths[idx] = max(self.col_widths[idx], longitud)

    def to_xml(self) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        ]

        if self.col_widths:
            lines.append("  <cols>")
            for idx, w in enumerate(self.col_widths, start=1):
                ancho = min(max(w, 10), 45)
                lines.append(
                    f'    <col min="{idx}" max="{idx}" width="{ancho}" customWidth="1"/>'
                )
            lines.append("  </cols>")

        lines.append("  <sheetData>")
        for r_idx, row in enumerate(self.rows, start=1):
            lines.append(f'    <row r="{r_idx}">')
            for c_idx, (val, style_id) in enumerate(row, start=1):
                coord = f"{_col_letter(c_idx)}{r_idx}"
                s_attr = f' s="{style_id}"' if style_id else ""

                if val is None:
                    lines.append(f'      <c r="{coord}"{s_attr}/>')
                elif isinstance(val, (int, float)):
                    lines.append(f'      <c r="{coord}"{s_attr}><v>{val}</v></c>')
                else:
                    texto = escape(str(val))
                    lines.append(
                        f'      <c r="{coord}" t="inlineStr"{s_attr}><is><t>{texto}</t></is></c>'
                    )
            lines.append("    </row>")
        lines.append("  </sheetData>")
        lines.append("</worksheet>")
        return "\n".join(lines)


class ExcelExporter:
    """Generador completo de archivo .xlsx para el sistema de finanzas."""

    def __init__(self, core: FinanceCore):
        self.core = core
        self.db = core.db

    def exportar(self, ruta_destino: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)

        sheets = [
            self._construir_hoja_resumen(),
            self._construir_hoja_movimientos(),
            self._construir_hoja_cuentas(),
            self._construir_hoja_tarjetas(),
            self._construir_hoja_deudas(),
            self._construir_hoja_hormiga(),
        ]

        with zipfile.ZipFile(ruta_destino, "w", zipfile.ZIP_DEFLATED) as z:
            # 1. [Content_Types].xml
            z.writestr("[Content_Types].xml", self._get_content_types_xml(len(sheets)))
            # 2. _rels/.rels
            z.writestr("_rels/.rels", self._get_root_rels_xml())
            # 3. xl/_rels/workbook.xml.rels
            z.writestr("xl/_rels/workbook.xml.rels", self._get_workbook_rels_xml(len(sheets)))
            # 4. xl/workbook.xml
            z.writestr("xl/workbook.xml", self._get_workbook_xml([s.name for s in sheets]))
            # 5. xl/styles.xml
            z.writestr("xl/styles.xml", self._get_styles_xml())
            # 6. xl/worksheets/sheetN.xml
            for idx, sheet in enumerate(sheets, start=1):
                z.writestr(f"xl/worksheets/sheet{idx}.xml", sheet.to_xml())

        return ruta_destino

    def _construir_hoja_resumen(self) -> SheetBuilder:
        sb = SheetBuilder("Resumen")
        resumen = self.core.obtener_resumen_global()
        por_dep = self.core.calcular_por_depositar(horizonte_dias=15)
        gasto_mes = self.core.calcular_gasto_mes()

        # Título
        sb.add_row([("RESUMEN FINANCIERO PERSONAL", 4)])
        sb.add_row([("", 0)])

        # Saldos Globales
        sb.add_row([("Concepto", 1), ("Monto", 1)])
        sb.add_row([("Total Activos (Débito + Efectivo)", 0), (resumen.total_activos / 100.0, 2)])
        sb.add_row([("  - Débito", 0), (resumen.saldo_debito / 100.0, 2)])
        sb.add_row([("  - Efectivo", 0), (resumen.saldo_efectivo / 100.0, 2)])
        sb.add_row([("Total Pasivos (Tarjetas + Deudas)", 0), (resumen.total_pasivos / 100.0, 2)])
        sb.add_row([("  - Tarjetas de Crédito", 0), (resumen.deuda_tarjetas / 100.0, 2)])
        sb.add_row([("  - Préstamos / Deudas", 0), (resumen.deuda_prestamos / 100.0, 2)])
        sb.add_row([("Patrimonio Neto", 1), (resumen.patrimonio_neto / 100.0, 2)])
        sb.add_row([("Gasto del Mes Actual", 0), (gasto_mes / 100.0, 2)])
        sb.add_row([("", 0)])

        # Widget Por Depositar
        sb.add_row([("POR DEPOSITAR (HORIZONTE 15 DÍAS)", 4)])
        sb.add_row([("Compromiso", 1), ("Cuenta de Pago", 1), ("Fecha Venc.", 1), ("Monto", 1)])
        for comp in por_dep.compromisos:
            sb.add_row(
                [
                    (comp.descripcion, 0),
                    (comp.cuenta_pago_nombre, 0),
                    (comp.fecha_vencimiento.strftime("%Y-%m-%d"), 0),
                    (comp.monto_centavos / 100.0, 2),
                ]
            )
        sb.add_row([("Total Compromisos", 1), ("", 0), ("", 0), (por_dep.total_compromisos / 100.0, 2)])
        sb.add_row([("Falta Depositar (Neto)", 1), ("", 0), ("", 0), (por_dep.total_falta_depositar / 100.0, 2)])

        return sb

    def _construir_hoja_movimientos(self) -> SheetBuilder:
        sb = SheetBuilder("Movimientos")
        sb.add_row(
            [
                ("ID", 1),
                ("Fecha", 1),
                ("Tipo", 1),
                ("Cuenta Origen", 1),
                ("Cuenta Destino", 1),
                ("Categoría", 1),
                ("Concepto / Nota", 1),
                ("Monto", 1),
            ]
        )
        movs = self.db.get_movimientos()
        for m in movs:
            sb.add_row(
                [
                    (m.id, 0),
                    (m.fecha, 0),
                    (m.tipo.upper(), 0),
                    (m.cuenta_origen_nombre or "-", 0),
                    (m.cuenta_destino_nombre or "-", 0),
                    (m.categoria_nombre or "-", 0),
                    (m.nota, 0),
                    (m.monto_centavos / 100.0, 2),
                ]
            )
        return sb

    def _construir_hoja_cuentas(self) -> SheetBuilder:
        sb = SheetBuilder("Cuentas")
        sb.add_row(
            [
                ("ID", 1),
                ("Nombre", 1),
                ("Tipo", 1),
                ("Saldo Actual", 1),
                ("Total Depositado", 1),
                ("Estado", 1),
            ]
        )
        cuentas = self.db.get_cuentas(incluir_archivadas=True)
        for c in cuentas:
            saldo = self.core.calcular_saldo_cuenta(c.id)
            depositado = self.core.calcular_total_depositado(c.id)
            estado = "Archivada" if c.archivada else "Activa"
            sb.add_row(
                [
                    (c.id, 0),
                    (c.nombre, 0),
                    (c.tipo.upper(), 0),
                    (saldo / 100.0, 2),
                    (depositado / 100.0, 2),
                    (estado, 0),
                ]
            )
        return sb

    def _construir_hoja_tarjetas(self) -> SheetBuilder:
        sb = SheetBuilder("Tarjetas")
        sb.add_row(
            [
                ("Tarjeta", 1),
                ("Límite", 1),
                ("Saldo Deudor", 1),
                ("Disponible", 1),
                ("% Uso", 1),
                ("Día Corte", 1),
                ("Próximo Corte", 1),
                ("Fecha Límite Pago", 1),
                ("Pago No Intereses", 1),
                ("Cuenta de Pago", 1),
            ]
        )
        detalles = self.core.obtener_detalles_tarjetas()
        for d in detalles:
            sb.add_row(
                [
                    (d.cuenta.nombre, 0),
                    (d.tarjeta.limite_centavos / 100.0, 2),
                    (d.saldo_actual / 100.0, 2),
                    (d.credito_disponible / 100.0, 2),
                    (f"{d.porcentaje_uso:.1f}%", 0),
                    (d.tarjeta.dia_corte, 0),
                    (d.proximo_corte.strftime("%Y-%m-%d"), 0),
                    (d.fecha_limite_pago.strftime("%Y-%m-%d"), 0),
                    (d.pago_para_no_intereses / 100.0, 2),
                    (d.cuenta_pago_nombre, 0),
                ]
            )
        return sb

    def _construir_hoja_deudas(self) -> SheetBuilder:
        sb = SheetBuilder("Deudas")
        sb.add_row(
            [
                ("Deuda / Préstamo", 1),
                ("Monto Original", 1),
                ("Saldo Restante", 1),
                ("Cuota", 1),
                ("Día de Pago", 1),
                ("Próximo Vencimiento", 1),
                ("Días Restantes", 1),
                ("Cuenta de Pago", 1),
            ]
        )
        detalles = self.core.obtener_detalles_deudas()
        for d in detalles:
            sb.add_row(
                [
                    (d.cuenta.nombre, 0),
                    (d.deuda.monto_original_centavos / 100.0, 2),
                    (d.saldo_restante / 100.0, 2),
                    (d.cuota_centavos / 100.0, 2),
                    (d.deuda.dia_pago, 0),
                    (d.proximo_pago.strftime("%Y-%m-%d"), 0),
                    (d.dias_al_pago, 0),
                    (d.cuenta_pago_nombre, 0),
                ]
            )
        return sb

    def _construir_hoja_hormiga(self) -> SheetBuilder:
        sb = SheetBuilder("Hormiga")
        h = self.core.obtener_metricas_hormiga()
        sb.add_row([("MÉTRICAS DE GASTO HORMIGA", 4)])
        sb.add_row([("Período", 1), (h.mes_str, 0)])
        sb.add_row([("Total Gasto Hormiga", 1), (h.total_hormiga_centavos / 100.0, 2)])
        sb.add_row([("Total Gastos del Mes", 1), (h.total_gastos_centavos / 100.0, 2)])
        sb.add_row([("% del Gasto Total", 1), (f"{h.porcentaje_hormiga:.1f}%", 0)])
        sb.add_row([("Proyección Anual", 1), (h.proyeccion_anual_centavos / 100.0, 2)])
        sb.add_row([("", 0)])

        sb.add_row([("TOP 5 GASTOS HORMIGA", 4)])
        sb.add_row([("Concepto", 1), ("Total Acumulado", 1)])
        for concepto, suma in h.top_conceptos:
            sb.add_row([(concepto, 0), (suma / 100.0, 2)])

        return sb

    # ================= XML Helpers ================= #
    def _get_content_types_xml(self, num_sheets: int) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '  <Default Extension="xml" ContentType="application/xml"/>',
            '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        ]
        for i in range(1, num_sheets + 1):
            lines.append(
                f'  <Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        lines.append("</Types>")
        return "\n".join(lines)

    def _get_root_rels_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    def _get_workbook_rels_xml(self, num_sheets: int) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        for i in range(1, num_sheets + 1):
            lines.append(
                f'  <Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            )
        lines.append(
            f'  <Relationship Id="rId{num_sheets + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )
        lines.append("</Relationships>")
        return "\n".join(lines)

    def _get_workbook_xml(self, sheet_names: List[str]) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            "  <sheets>",
        ]
        for idx, name in enumerate(sheet_names, start=1):
            escaped = escape(name)
            lines.append(f'    <sheet name="{escaped}" sheetId="{idx}" r:id="rId{idx}"/>')
        lines.append("  </sheets>")
        lines.append("</workbook>")
        return "\n".join(lines)

    def _get_styles_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1">
    <numFmt numFmtId="164" formatCode="$#,##0.00"/>
  </numFmts>
  <fonts count="4">
    <font><name val="Calibri"/><sz val="11"/><color rgb="FF2C3E50"/></font>
    <font><b/><name val="Calibri"/><sz val="11"/><color rgb="FF1A252F"/></font>
    <font><name val="Calibri"/><sz val="11"/><color rgb="FF2C3E50"/></font>
    <font><b/><name val="Calibri"/><sz val="13"/><color rgb="FF2C3E50"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill fillType="none"/></fill>
    <fill><patternFill fillType="gray125"/></fill>
    <fill><patternFill fillType="solid"><fgColor rgb="FFEAECEE"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD5D8DC"/></left>
      <right style="thin"><color rgb="FFD5D8DC"/></right>
      <top style="thin"><color rgb="FFD5D8DC"/></top>
      <bottom style="thin"><color rgb="FFD5D8DC"/></bottom>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="5">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
</styleSheet>"""
