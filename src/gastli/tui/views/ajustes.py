"""Vista 7: Ajustes, Configuración, Categorías, Exportación y Respaldos."""
import curses
import os
from typing import Any, Callable, Dict, List, Optional

from gastli import paths
from gastli.core import FinanceCore
from gastli.export.csv_export import CsvExporter
from gastli.export.xlsx import ExcelExporter
from gastli.models import Categoria, centavos_a_str, parse_monto_a_centavos
from gastli.tui.theme import (
    BOX_H,
    attr_border,
    attr_muted,
    attr_negative,
    attr_normal,
    attr_positive,
    attr_selected,
    attr_title,
    attr_warning,
)
from gastli.tui.widgets import FormModal, TableWidget, draw_box, safe_addstr


class AjustesView:
    def __init__(
        self,
        core: FinanceCore,
        abrir_modal: Callable[[Any], None],
        notificar: Callable[[str], None],
    ):
        self.core = core
        self.abrir_modal = abrir_modal
        self.notificar = notificar

        headers = [
            ("ID", 4, "R"),
            ("Categoría", 26, "L"),
            ("Es Hormiga", 12, "L"),
        ]
        self.table_cats = TableWidget(headers, box_title="Catálogo de Categorías")
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        cats = self.core.db.get_categorias(solo_activas=True)
        rows = []
        attrs = []
        for c in cats:
            es_h = "[X] Sí" if c.es_hormiga else "[ ] No"
            row_attr = attr_warning() if c.es_hormiga else attr_normal()
            rows.append([c.id, c.nombre, es_h])
            attrs.append(row_attr)
        self.table_cats.set_data(rows, attrs)

    def get_categoria_seleccionada(self) -> Optional[Categoria]:
        if not self.table_cats.rows or self.table_cats.selected_index >= len(self.table_cats.rows):
            return None
        fila = self.table_cats.rows[self.table_cats.selected_index]
        cats = self.core.db.get_categorias()
        for c in cats:
            if c.id == fila[0]:
                return c
        return None

    def handle_key(self, ch: int) -> bool:
        if self.table_cats.handle_key(ch):
            return True

        if ch in (ord(" "), ord("\n"), ord("\r")):
            # Conmutar marca hormiga
            self.accion_toggle_hormiga()
            return True
        elif ch in (ord("a"), ord("A")):
            self.accion_nueva_categoria()
            return True
        elif ch in (ord("x"), ord("X")):
            self.accion_exportar_excel()
            return True
        elif ch in (ord("v"), ord("V")):
            self.accion_exportar_csv()
            return True
        elif ch in (ord("b"), ord("B")):
            self.accion_crear_respaldo()
            return True
        elif ch in (ord("m"), ord("M")):
            self.accion_cambiar_moneda()
            return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        if not es_clic(bstate):
            # Podría ser scroll en la tabla
            return self.table_cats.handle_mouse(my, mx, bstate)[0]

        mitad_w = self.w // 2
        right_x = self.x + mitad_w

        # Clic en panel derecho de acciones
        if self.y <= my < self.y + self.h and right_x <= mx < self.x + self.w:
            # Detectar fila clickeada en acciones
            rel_y = my - self.y
            if rel_y == 8:
                self.accion_cambiar_moneda()
                return True
            elif rel_y == 12:
                self.accion_exportar_excel()
                return True
            elif rel_y == 14:
                self.accion_exportar_csv()
                return True
            elif rel_y == 18:
                self.accion_crear_respaldo()
                return True

        # Clic en tabla categorías (doble clic conmuta estado hormiga)
        consumido, doble_clic = self.table_cats.handle_mouse(my, mx, bstate)
        if doble_clic:
            self.accion_toggle_hormiga()
        return consumido

    def accion_toggle_hormiga(self):
        cat = self.get_categoria_seleccionada()
        if not cat:
            return
        idx_prev = self.table_cats.selected_index
        self.core.db.toggle_categoria_hormiga(cat.id)
        self.cargar_datos()
        self.table_cats.selected_index = idx_prev
        nuevo_val = not cat.es_hormiga
        txt = "marcada como hormiga" if nuevo_val else "desmarcada de hormiga"
        self.notificar(f"Categoría '{cat.nombre}' {txt}.")

    def accion_nueva_categoria(self):
        campos = [
            {"key": "nombre", "label": "Nombre de la categoría:", "type": "text", "value": ""},
            {"key": "es_hormiga", "label": "¿Es gasto hormiga?:", "type": "choice", "options": ["No", "Sí"], "value": 0},
        ]

        def on_guardar(vals):
            nom = vals["nombre"].strip()
            if not nom:
                self.notificar("El nombre de la categoría no puede estar vacío.")
                return
            es_h = vals["es_hormiga"] == 1 or vals["es_hormiga"] == "Sí"
            self.core.db.guardar_categoria(nom, es_hormiga=es_h)
            self.cargar_datos()
            self.abrir_modal(None)
            self.notificar(f"Categoría '{nom}' creada con éxito.")

        modal = FormModal("Nueva Categoría", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_cambiar_moneda(self):
        config = self.core.db.get_config()
        campos = [
            {"key": "moneda", "label": "Símbolo de moneda:", "type": "text", "value": config.moneda},
            {"key": "horizonte", "label": "Horizonte por defecto (días):", "type": "number", "value": str(config.horizonte_dias)},
            {"key": "efectivo_diario", "label": "Monto diario efectivo:", "type": "number", "value": f"{config.monto_efectivo_diario_centavos / 100.0:.2f}"},
        ]

        def on_guardar(vals):
            m = vals["moneda"].strip() or "$"
            h = int(vals["horizonte"]) if vals["horizonte"].isdigit() else 15
            ef = parse_monto_a_centavos(vals["efectivo_diario"])
            self.core.db.set_config("moneda", m)
            self.core.db.set_config("horizonte_dias", str(h))
            self.core.db.set_config("monto_efectivo_diario", str(ef))
            self.cargar_datos()
            self.abrir_modal(None)
            self.notificar("Configuración actualizada correctamente.")

        modal = FormModal("Configuración General", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_exportar_excel(self):
        try:
            ruta = os.path.join(paths.exports_dir(), "finanzas_export.xlsx")
            exp = ExcelExporter(self.core)
            exp.exportar(ruta)
            self.notificar(f"Libro Excel generado en: {ruta}")
        except Exception as e:
            self.notificar(f"Error al exportar Excel: {e}")

    def accion_exportar_csv(self):
        try:
            ruta = os.path.join(paths.exports_dir(), "finanzas_movimientos.csv")
            exp = CsvExporter(self.core)
            exp.exportar_movimientos(ruta)
            self.notificar(f"Archivo CSV generado en: {ruta}")
        except Exception as e:
            self.notificar(f"Error al exportar CSV: {e}")

    def accion_crear_respaldo(self):
        try:
            ruta = self.core.db.realizar_respaldo()
            if ruta:
                self.notificar(f"Respaldo creado: {os.path.basename(ruta)}")
        except Exception as e:
            self.notificar(f"Error al respaldar: {e}")

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w
        config = self.core.db.get_config()

        mitad_w = w // 2
        alto_util = h

        # ---------------- PANEL IZQUIERDO: CATEGORÍAS ---------------- #
        self.table_cats.render(win, y, x, alto_util - 1, mitad_w, tiene_foco=True)
        safe_addstr(win, y + alto_util - 1, x + 2, "[Espacio] Marcar/Desmarcar Hormiga  [a] Nueva cat.", attr_muted())

        # ---------------- PANEL DERECHO: AJUSTES Y HERRAMIENTAS ---------------- #
        right_x = x + mitad_w
        right_w = w - mitad_w
        draw_box(win, y, right_x, alto_util, right_w, title="Ajustes y Mantenimiento")

        r_y = y + 2
        safe_addstr(win, r_y, right_x + 3, "PARÁMETROS DEL SISTEMA", attr_title())
        r_y += 2

        safe_addstr(win, r_y, right_x + 3, f"Símbolo de moneda:        {config.moneda}", attr_normal())
        r_y += 1
        safe_addstr(win, r_y, right_x + 3, f"Horizonte por defecto:    {config.horizonte_dias} días", attr_normal())
        r_y += 1
        ef_str = centavos_a_str(config.monto_efectivo_diario_centavos, config.moneda)
        safe_addstr(win, r_y, right_x + 3, f"Monto diario de efectivo: {ef_str}", attr_normal())
        r_y += 1
        safe_addstr(win, r_y, right_x + 3, "[m] Modificar parámetros", attr_title())
        r_y += 2

        safe_addstr(win, r_y, right_x + 3, "─" * (right_w - 6), attr_muted())
        r_y += 1

        safe_addstr(win, r_y, right_x + 3, "EXPORTACIÓN DE DATOS", attr_title())
        r_y += 2
        safe_addstr(win, r_y, right_x + 3, "[x] Generar libro Excel (.xlsx real)", attr_title())
        r_y += 2
        safe_addstr(win, r_y, right_x + 3, "[v] Exportar movimientos a CSV", attr_title())
        r_y += 2

        safe_addstr(win, r_y, right_x + 3, "─" * (right_w - 6), attr_muted())
        r_y += 1

        safe_addstr(win, r_y, right_x + 3, "COPIAS DE SEGURIDAD (BACKUPS)", attr_title())
        r_y += 2
        safe_addstr(win, r_y, right_x + 3, "[b] Crear respaldo inmediato ahora", attr_title())
        r_y += 2

        respaldos = self.core.db.listar_respaldos()
        safe_addstr(win, r_y, right_x + 3, f"Respaldos almacenados ({len(respaldos)}) en {paths.backups_dir()}:", attr_muted())
        r_y += 1
        for bck in respaldos[:3]:
            safe_addstr(win, r_y, right_x + 5, f"• {bck['nombre']} ({bck['fecha']})", attr_muted())
            r_y += 1
