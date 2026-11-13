"""Vista 2: Lista y gestión de Movimientos con filtros y búsqueda."""
import curses
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from gastli.core import FinanceCore
from gastli.models import Movimiento, TipoCuenta, TipoMovimiento, centavos_a_str
from gastli.tui.theme import (
    attr_border,
    attr_muted,
    attr_negative,
    attr_normal,
    attr_positive,
    attr_selected,
    attr_title,
    attr_warning,
)
from gastli.tui.widgets import TableWidget, draw_box, safe_addstr


class MovimientosView:
    def __init__(
        self,
        core: FinanceCore,
        abrir_modal: Callable[[Any], None],
        notificar: Callable[[str], None],
    ):
        self.core = core
        self.abrir_modal = abrir_modal
        self.notificar = notificar

        # Filtros
        self.filtro_texto: Optional[str] = None
        self.filtro_tipo: Optional[str] = None
        self.filtro_mes_actual: bool = True

        headers = [
            ("ID", 5, "R"),
            ("Fecha", 10, "L"),
            ("Tipo", 8, "L"),
            ("Origen", 14, "L"),
            ("Destino / Cat.", 18, "L"),
            ("Nota / Concepto", 22, "L"),
            ("Monto", 14, "R"),
        ]
        self.table = TableWidget(headers, box_title="Historial de Movimientos")
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        hoy = date.today()
        fecha_desde = f"{hoy.year:04d}-{hoy.month:02d}-01" if self.filtro_mes_actual else None

        movs = self.core.db.get_movimientos(
            tipo=self.filtro_tipo,
            fecha_desde=fecha_desde,
            texto_busqueda=self.filtro_texto,
        )
        config = self.core.db.get_config()

        rows = []
        attrs = []
        for m in movs:
            # Destino o categoría
            dest_cat = m.cuenta_destino_nombre or m.categoria_nombre or "-"
            con_signo = m.tipo in (TipoMovimiento.GASTO, TipoMovimiento.INGRESO)
            es_neg = m.tipo == TipoMovimiento.GASTO
            centavos_disp = -m.monto_centavos if es_neg else m.monto_centavos
            m_str = centavos_a_str(centavos_disp, config.moneda, con_signo=True)

            if m.tipo == TipoMovimiento.GASTO:
                row_attr = attr_negative()
            elif m.tipo == TipoMovimiento.INGRESO:
                row_attr = attr_positive()
            elif m.tipo == TipoMovimiento.PAGO:
                row_attr = attr_warning()
            else:
                row_attr = attr_normal()

            rows.append(
                [
                    m.id,
                    m.fecha,
                    m.tipo.capitalize()[:7],
                    m.cuenta_origen_nombre or "-",
                    dest_cat[:17],
                    m.nota[:21],
                    m_str,
                ]
            )
            attrs.append(row_attr)

        self.table.set_data(rows, attrs)

    def handle_key(self, ch: int) -> bool:
        if self.table.handle_key(ch):
            return True

        if ch in (ord("m"), ord("M")):
            # Alternar filtro de mes actual vs todos
            self.filtro_mes_actual = not self.filtro_mes_actual
            self.cargar_datos()
            estado = "Mes actual" if self.filtro_mes_actual else "Todos"
            self.notificar(f"Filtro de fecha: {estado}")
            return True

        if ch in (ord("c"), ord("C")):
            # Limpiar filtros
            self.filtro_texto = None
            self.filtro_tipo = None
            self.filtro_mes_actual = True
            self.cargar_datos()
            self.notificar("Filtros restablecidos")
            return True

        if ch in (ord("e"), ord("E"), ord("\n"), ord("\r")):
            self.accion_editar()
            return True

        if ch in (ord("d"), ord("D")):
            self.accion_borrar()
            return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        # Clic en barra de filtros
        if es_clic(bstate) and my == self.y and self.x <= mx < self.x + self.w:
            # Alternar filtro mes
            self.filtro_mes_actual = not self.filtro_mes_actual
            self.cargar_datos()
            return True

        consumido, doble_clic = self.table.handle_mouse(my, mx, bstate)
        if doble_clic:
            self.accion_editar()
        return consumido

    def get_movimiento_seleccionado(self) -> Optional[Movimiento]:
        if not self.table.rows or self.table.selected_index >= len(self.table.rows):
            return None
        fila = self.table.rows[self.table.selected_index]
        mov_id = fila[0]
        return self.core.db.get_movimiento(mov_id)

    def accion_editar(self):
        mov = self.get_movimiento_seleccionado()
        if not mov:
            return

        from gastli.tui.widgets import FormModal

        cuentas = self.core.db.get_cuentas()
        categorias = self.core.db.get_categorias()

        cuentas_nombres = [c.nombre for c in cuentas]
        cuentas_ids = [c.id for c in cuentas]
        cat_nombres = [cat.nombre for cat in categorias]
        cat_ids = [cat.id for cat in categorias]

        idx_origen = cuentas_ids.index(mov.cuenta_origen_id) if mov.cuenta_origen_id in cuentas_ids else 0
        idx_cat = cat_ids.index(mov.categoria_id) if mov.categoria_id in cat_ids else 0

        campos = [
            {"key": "fecha", "label": "Fecha (YYYY-MM-DD):", "type": "date", "value": mov.fecha},
            {"key": "monto", "label": "Monto:", "type": "number", "value": f"{mov.monto_centavos / 100.0:.2f}"},
            {"key": "origen", "label": "Cuenta origen:", "type": "choice", "options": cuentas_nombres, "value": idx_origen},
            {"key": "categoria", "label": "Categoría:", "type": "choice", "options": cat_nombres, "value": idx_cat},
            {"key": "nota", "label": "Nota:", "type": "text", "value": mov.nota},
        ]

        def on_guardar(vals):
            try:
                from gastli.models import parse_monto_a_centavos

                mov.fecha = vals["fecha"]
                mov.monto_centavos = parse_monto_a_centavos(vals["monto"])
                idx_orig = vals["origen"] if isinstance(vals["origen"], int) else cuentas_nombres.index(vals["origen"])
                mov.cuenta_origen_id = cuentas_ids[idx_orig]
                idx_c = vals["categoria"] if isinstance(vals["categoria"], int) else cat_nombres.index(vals["categoria"])
                mov.categoria_id = cat_ids[idx_c]
                mov.nota = vals["nota"]
                self.core.db.actualizar_movimiento(mov)
                self.cargar_datos()
                self.abrir_modal(None)
                self.notificar(f"Movimiento #{mov.id} actualizado con éxito")
            except Exception as ex:
                self.notificar(f"Error al editar: {ex}")

        def on_cancelar():
            self.abrir_modal(None)

        modal = FormModal(f"Editar Movimiento #{mov.id}", campos, on_guardar, on_cancelar)
        self.abrir_modal(modal)

    def accion_borrar(self):
        mov = self.get_movimiento_seleccionado()
        if not mov:
            return

        from gastli.tui.widgets import ConfirmModal

        def on_confirmar():
            self.core.db.borrar_movimiento(mov.id)
            self.cargar_datos()
            self.abrir_modal(None)
            self.notificar(f"Movimiento #{mov.id} eliminado. Presiona 'u' para deshacer")

        def on_cancelar():
            self.abrir_modal(None)

        modal = ConfirmModal(
            "Confirmar eliminación",
            f"¿Deseas eliminar el movimiento #{mov.id} ({mov.nota or mov.tipo})?",
            on_confirmar,
            on_cancelar,
        )
        self.abrir_modal(modal)

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w

        # Barra superior de filtros
        filtro_fecha_str = "Mes Actual [tecla m]" if self.filtro_mes_actual else "Todo el Historial [tecla m]"
        busqueda_str = f"Buscar: '{self.filtro_texto}'" if self.filtro_texto else "Buscar: [/]"
        safe_addstr(
            win,
            y,
            x + 2,
            f"Filtros activos: [{filtro_fecha_str}]  [{busqueda_str}]  [Limpiar filtros: c]",
            attr_muted(),
        )

        # Renderizar tabla
        self.table.render(win, y + 1, x, h - 1, w, tiene_foco=True)
