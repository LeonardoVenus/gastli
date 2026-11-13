"""Vista 6: Métricas y Análisis de Gastos Hormiga."""
import curses
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from gastli.core import FinanceCore
from gastli.models import centavos_a_str
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
from gastli.tui.widgets import draw_box, draw_mini_bar_chart, safe_addstr


class HormigaView:
    def __init__(
        self,
        core: FinanceCore,
        abrir_modal: Callable[[Any], None],
        notificar: Callable[[str], None],
    ):
        self.core = core
        self.abrir_modal = abrir_modal
        self.notificar = notificar
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        pass

    def handle_key(self, ch: int) -> bool:
        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        return False

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w
        config = self.core.db.get_config()
        h_data = self.core.obtener_metricas_hormiga()

        mitad_w = w // 2
        alto_util = h

        # ---------------- PANEL IZQUIERDO: MÉTRICAS Y TOP 5 ---------------- #
        draw_box(win, y, x, alto_util, mitad_w, title=f"Gasto Hormiga - {h_data.mes_str}")

        curr_y = y + 2
        col_w = mitad_w - 6

        safe_addstr(win, curr_y, x + 3, "RESUMEN DEL MES", attr_title())
        curr_y += 2

        tot_h_str = centavos_a_str(h_data.total_hormiga_centavos, config.moneda, con_signo=False)
        safe_addstr(win, curr_y, x + 3, f"{'Total Gasto Hormiga':<{col_w - 18}}", attr_normal())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{tot_h_str:>16}", attr_negative())
        curr_y += 1

        tot_g_str = centavos_a_str(h_data.total_gastos_centavos, config.moneda, con_signo=False)
        safe_addstr(win, curr_y, x + 3, f"{'Gasto Total del Mes':<{col_w - 18}}", attr_normal())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{tot_g_str:>16}", attr_normal())
        curr_y += 1

        pct_str = f"{h_data.porcentaje_hormiga:.1f}%"
        safe_addstr(win, curr_y, x + 3, f"{'% del Gasto Total':<{col_w - 18}}", attr_title())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{pct_str:>16}", attr_warning())
        curr_y += 1

        proy_str = centavos_a_str(h_data.proyeccion_anual_centavos, config.moneda, con_signo=False)
        safe_addstr(win, curr_y, x + 3, f"{'Proyección Anual':<{col_w - 18}}", attr_normal())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{proy_str:>16}", attr_negative())
        curr_y += 2

        safe_addstr(win, curr_y, x + 3, "─" * col_w, attr_muted())
        curr_y += 1

        # TOP 5 GASTOS HORMIGA
        safe_addstr(win, curr_y, x + 3, "TOP 5 CONCEPTOS / CATEGORÍAS", attr_title())
        curr_y += 2

        if not h_data.top_conceptos:
            safe_addstr(win, curr_y, x + 3, "(Sin registros de gastos hormiga este mes)", attr_muted())
        else:
            for idx, (concepto, suma) in enumerate(h_data.top_conceptos, start=1):
                s_str = centavos_a_str(suma, config.moneda, con_signo=False)
                c_nom = f"{idx}. {concepto}"
                safe_addstr(win, curr_y, x + 3, f"{c_nom:<{col_w - 18}}", attr_normal())
                safe_addstr(win, curr_y, x + mitad_w - 20, f"{s_str:>16}", attr_title())
                curr_y += 1

        # ---------------- PANEL DERECHO: GRÁFICA DE BARRAS DIARIA ---------------- #
        right_x = x + mitad_w
        right_w = w - mitad_w
        draw_box(win, y, right_x, alto_util, right_w, title="Distribución Diaria del Mes")

        r_y = y + 2
        safe_addstr(win, r_y, right_x + 3, "Gasto por día (caracteres de bloque):", attr_title())
        r_y += 2

        max_dia_str = centavos_a_str(h_data.max_dia_centavos, config.moneda, con_signo=False)
        safe_addstr(win, r_y, right_x + 3, f"Pico máximo diario: {max_dia_str}", attr_muted())
        r_y += 2

        # Altura de la gráfica
        alto_grafica = max(5, alto_util - 12)
        barras_chars = draw_mini_bar_chart(
            h_data.barras_diarias, height=alto_grafica, max_value=h_data.max_dia_centavos
        )

        for l_idx, linea in enumerate(barras_chars):
            # Escalar si el ancho disponible es suficiente
            safe_addstr(win, r_y + l_idx, right_x + 4, linea, attr_warning())

        # Eje horizontal con días (1, 5, 10, 15, 20, 25, 30)
        eje_y = r_y + len(barras_chars)
        safe_addstr(win, eje_y, right_x + 4, "─" * len(h_data.barras_diarias), attr_muted())
        eje_y += 1

        dias_labels = ""
        for d in range(1, len(h_data.barras_diarias) + 1):
            if d == 1 or d % 5 == 0:
                dias_labels += f"{d:<5}"
        safe_addstr(win, eje_y, right_x + 4, dias_labels[:right_w - 8], attr_muted())
        eje_y += 1
        safe_addstr(win, eje_y, right_x + 4, "Días del mes", attr_title())
