"""Vista 5: Control Diario de Efectivo y Cartera Diaria."""
import curses
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from gastli.core import FinanceCore
from gastli.models import Movimiento, TipoCuenta, TipoMovimiento, centavos_a_str
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
from gastli.tui.widgets import TableWidget, draw_box, safe_addstr


class EfectivoView:
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
            ("Hora / ID", 10, "L"),
            ("Concepto / Nota", 34, "L"),
            ("Categoría", 22, "L"),
            ("Monto", 16, "R"),
        ]
        self.table = TableWidget(headers, box_title="Gastos en Efectivo Registrados Hoy")
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        met = self.core.obtener_metricas_efectivo()
        config = self.core.db.get_config()

        rows = []
        attrs = []
        for g in met.gastos_hoy_detalle:
            m_str = centavos_a_str(-g.monto_centavos, config.moneda, con_signo=True)
            hora_id = g.created_at[11:16] if len(g.created_at) >= 16 else f"#{g.id}"
            rows.append([hora_id, g.nota or "Gasto en efectivo", g.categoria_nombre or "-", m_str])
            attrs.append(attr_negative())

        self.table.set_data(rows, attrs)

    def handle_key(self, ch: int) -> bool:
        if self.table.handle_key(ch):
            return True

        if ch in (ord("l"), ord("L")):
            self.accion_llevar_hoy()
            return True
        elif ch in (ord("s"), ord("S")):
            self.accion_devolver_sobrante()
            return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        # Clic en botones rápidos de la parte superior
        if es_clic(bstate) and my == self.y + 6 and self.x <= mx < self.x + self.w:
            rel_x = mx - self.x
            if 3 <= rel_x <= 25:
                self.accion_llevar_hoy()
                return True
            elif 28 <= rel_x <= 55:
                self.accion_devolver_sobrante()
                return True

        return self.table.handle_mouse(my, mx, bstate)[0]

    def accion_llevar_hoy(self):
        met = self.core.obtener_metricas_efectivo()
        if not met.cuenta_id:
            self.notificar("No se encontró cuenta de efectivo/cartera.")
            return

        config = self.core.db.get_config()
        try:
            mov = self.core.accion_llevar_hoy(cuenta_destino_id=met.cuenta_id)
            self.cargar_datos()
            monto_str = centavos_a_str(mov.monto_centavos, config.moneda)
            self.notificar(f"Se transfirieron {monto_str} a '{met.cuenta_nombre}' (Llevar hoy)")
        except Exception as e:
            self.notificar(f"Error: {e}")

    def accion_devolver_sobrante(self):
        met = self.core.obtener_metricas_efectivo()
        if not met.cuenta_id:
            return

        config = self.core.db.get_config()
        if met.sobra_actual <= 0:
            self.notificar("No hay saldo sobrante en cartera para devolver.")
            return

        try:
            mov = self.core.accion_devolver_sobrante(cuenta_origen_id=met.cuenta_id)
            if mov:
                self.cargar_datos()
                monto_str = centavos_a_str(mov.monto_centavos, config.moneda)
                self.notificar(f"Se devolvieron {monto_str} de sobrante a ahorro/banco")
        except Exception as e:
            self.notificar(f"Error: {e}")

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w
        config = self.core.db.get_config()
        met = self.core.obtener_metricas_efectivo()

        # ---------------- 3 TARJETAS GRANDES SUPERIORES ---------------- #
        ancho_tarjeta = max(22, (w - 6) // 3)

        # 1. LLEVÉ HOY
        x1 = x + 2
        draw_box(win, y, x1, 5, ancho_tarjeta, title="LLEVÉ HOY")
        llevo_str = centavos_a_str(met.llevo_hoy, config.moneda, con_signo=False)
        safe_addstr(win, y + 2, x1 + 4, f"{llevo_str:>14}", attr_title())

        # 2. GASTÉ HOY
        x2 = x1 + ancho_tarjeta + 1
        draw_box(win, y, x2, 5, ancho_tarjeta, title="GASTÉ HOY")
        gasto_str = centavos_a_str(met.gasto_hoy, config.moneda, con_signo=False)
        safe_addstr(win, y + 2, x2 + 4, f"{gasto_str:>14}", attr_negative())

        # 3. SOBRA (SALDO ACTUAL)
        x3 = x2 + ancho_tarjeta + 1
        ancho_t3 = min(ancho_tarjeta, w - (x3 - x) - 2)
        draw_box(win, y, x3, 5, ancho_t3, title="SOBRA (CARTERA)")
        sobra_str = centavos_a_str(met.sobra_actual, config.moneda, con_signo=False)
        attr_sobra = attr_positive() if met.sobra_actual > 0 else attr_muted()
        safe_addstr(win, y + 2, x3 + 4, f"{sobra_str:>14}", attr_sobra)

        # Barra de acciones rápidas y estadísticas intermedias
        bar_y = y + 6
        safe_addstr(win, bar_y, x + 3, "[l] Llevar hoy", attr_title())
        safe_addstr(win, bar_y, x + 20, "[s] Devolver sobrante", attr_title())

        prom_str = centavos_a_str(met.promedio_7_dias, config.moneda, con_signo=False)
        safe_addstr(
            win,
            bar_y,
            x + 48,
            f"Promedio diario últimos 7 días: {prom_str}",
            attr_muted(),
        )

        # Tabla inferior con los gastos del día
        alto_tabla = max(6, h - 8)
        self.table.render(win, y + 8, x, alto_tabla, w, tiene_foco=True)
