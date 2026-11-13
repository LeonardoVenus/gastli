"""Vista 1: Resumen General y Widget 'Por depositar'."""
import curses
from typing import Optional

from gastli.core import FinanceCore
from gastli.models import TipoCuenta, centavos_a_str
from gastli.tui.theme import (
    BOX_H,
    attr_border,
    attr_muted,
    attr_negative,
    attr_normal,
    attr_positive,
    attr_selected,
    attr_tab_active,
    attr_title,
    attr_warning,
)
from gastli.tui.widgets import draw_box, safe_addstr


class ResumenView:
    def __init__(self, core: FinanceCore):
        self.core = core
        self.horizontes = [7, 15, 30]
        self.horiz_idx = 1  # 15 días por defecto
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    @property
    def horizonte_actual(self) -> int:
        return self.horizontes[self.horiz_idx]

    def handle_key(self, ch: int) -> bool:
        if ch in (ord("h"), ord("H")):
            self.horiz_idx = (self.horiz_idx + 1) % len(self.horizontes)
            return True
        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        if not es_clic(bstate):
            return False

        # Clic en selector de horizonte en el panel derecho (título o fila del selector)
        mitad_w = self.w // 2
        right_x = self.x + mitad_w
        if (my == self.y or my == self.y + 2) and right_x <= mx < self.x + self.w:
            # Alternar horizonte
            self.horiz_idx = (self.horiz_idx + 1) % len(self.horizontes)
            return True
        return False

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w
        config = self.core.db.get_config()
        resumen = self.core.obtener_resumen_global()
        por_dep = self.core.calcular_por_depositar(horizonte_dias=self.horizonte_actual)
        gasto_mes = self.core.calcular_gasto_mes()
        cuentas = self.core.db.get_cuentas(incluir_archivadas=False)

        mitad_w = w // 2
        alto_util = h

        # ---------------- PANEL IZQUIERDO: SALDOS ---------------- #
        draw_box(win, y, x, alto_util, mitad_w, title="Saldos y Estado Actual")

        curr_y = y + 2
        col_w = mitad_w - 6

        safe_addstr(win, curr_y, x + 3, "CUENTAS DE ACTIVOS", attr_title())
        curr_y += 1

        for c in cuentas:
            if c.es_activo:
                saldo = self.core.calcular_saldo_cuenta(c.id)
                saldo_str = centavos_a_str(saldo, config.moneda, con_signo=True)
                attr_s = attr_positive() if saldo > 0 else attr_normal()
                nombre_tipo = f"{c.nombre} ({c.tipo})"
                safe_addstr(win, curr_y, x + 3, f"{nombre_tipo:<{col_w - 18}}", attr_normal())
                safe_addstr(win, curr_y, x + mitad_w - 20, f"{saldo_str:>16}", attr_s)
                curr_y += 1

        tot_act_str = centavos_a_str(resumen.total_activos, config.moneda, con_signo=True)
        safe_addstr(win, curr_y, x + 3, "─" * col_w, attr_muted())
        curr_y += 1
        safe_addstr(win, curr_y, x + 3, f"{'Total Activos':<{col_w - 18}}", attr_title())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{tot_act_str:>16}", attr_positive())
        curr_y += 2

        # Sección Pasivos
        safe_addstr(win, curr_y, x + 3, "TARJETAS Y DEUDAS (PASIVOS)", attr_title())
        curr_y += 1
        for c in cuentas:
            if c.es_pasivo:
                saldo = self.core.calcular_saldo_cuenta(c.id)
                saldo_str = centavos_a_str(saldo, config.moneda, con_signo=False)
                attr_p = attr_negative() if saldo > 0 else attr_muted()
                nombre_tipo = f"{c.nombre} ({c.tipo})"
                safe_addstr(win, curr_y, x + 3, f"{nombre_tipo:<{col_w - 18}}", attr_normal())
                safe_addstr(win, curr_y, x + mitad_w - 20, f"{saldo_str:>16}", attr_p)
                curr_y += 1

        tot_pas_str = centavos_a_str(resumen.total_pasivos, config.moneda, con_signo=False)
        safe_addstr(win, curr_y, x + 3, "─" * col_w, attr_muted())
        curr_y += 1
        safe_addstr(win, curr_y, x + 3, f"{'Total Pasivos':<{col_w - 18}}", attr_title())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{tot_pas_str:>16}", attr_negative())
        curr_y += 2

        # Gasto mes y Patrimonio
        safe_addstr(win, curr_y, x + 3, "MÉTRICAS DEL MES", attr_title())
        curr_y += 1
        gasto_str = centavos_a_str(gasto_mes, config.moneda, con_signo=False)
        safe_addstr(win, curr_y, x + 3, f"{'Gasto del Mes':<{col_w - 18}}", attr_normal())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{gasto_str:>16}", attr_negative())
        curr_y += 1

        patr_str = centavos_a_str(resumen.patrimonio_neto, config.moneda, con_signo=True)
        attr_patr = attr_positive() if resumen.patrimonio_neto >= 0 else attr_negative()
        safe_addstr(win, curr_y, x + 3, f"{'Patrimonio Neto':<{col_w - 18}}", attr_title())
        safe_addstr(win, curr_y, x + mitad_w - 20, f"{patr_str:>16}", attr_patr)

        # ---------------- PANEL DERECHO: POR DEPOSITAR ---------------- #
        right_x = x + mitad_w
        right_w = w - mitad_w
        titulo_dep = f"Por depositar, {self.horizonte_actual} días [tecla h]"
        draw_box(win, y, right_x, alto_util, right_w, title=titulo_dep)

        r_y = y + 2
        r_col_w = right_w - 6

        # Selector rápido de horizonte
        sel_str = "Horizonte: "
        for h_val in self.horizontes:
            if h_val == self.horizonte_actual:
                sel_str += f"[{h_val}d*] "
            else:
                sel_str += f"{h_val}d  "
        safe_addstr(win, r_y, right_x + 3, sel_str, attr_title())
        r_y += 2

        if not por_dep.compromisos:
            safe_addstr(
                win,
                r_y,
                right_x + 3,
                f"No hay compromisos en los próximos {self.horizonte_actual} días.",
                attr_positive(),
            )
        else:
            safe_addstr(win, r_y, right_x + 3, "Próximos compromisos por vencer:", attr_title())
            r_y += 1
            for comp in por_dep.compromisos[: alto_util - 12]:
                m_str = centavos_a_str(comp.monto_centavos, config.moneda, con_signo=False)
                desc = comp.descripcion
                safe_addstr(win, r_y, right_x + 3, f"{desc:<{r_col_w - 16}}", attr_normal())
                safe_addstr(win, r_y, right_x + right_w - 19, f"{m_str:>15}", attr_warning())
                r_y += 1

            r_y += 1
            safe_addstr(win, r_y, right_x + 3, "─" * r_col_w, attr_muted())
            r_y += 1

            tot_comp_str = centavos_a_str(por_dep.total_compromisos, config.moneda, con_signo=False)
            safe_addstr(
                win, r_y, right_x + 3, f"{'Total Compromisos':<{r_col_w - 16}}", attr_normal()
            )
            safe_addstr(win, r_y, right_x + right_w - 19, f"{tot_comp_str:>15}", attr_warning())
            r_y += 1

            # Desglose por cuenta de débito
            for cta_id, datos in por_dep.compromisos_por_cuenta.items():
                saldo_deb = datos["saldo_actual"]
                s_deb_str = centavos_a_str(saldo_deb, config.moneda, con_signo=False)
                lbl = f"  Saldo en {datos['nombre']}"
                safe_addstr(win, r_y, right_x + 3, f"{lbl:<{r_col_w - 16}}", attr_muted())
                safe_addstr(win, r_y, right_x + right_w - 19, f"{s_deb_str:>15}", attr_muted())
                r_y += 1

            r_y += 1
            safe_addstr(win, r_y, right_x + 3, "═" * r_col_w, attr_muted())
            r_y += 1

            falta_str = centavos_a_str(por_dep.total_falta_depositar, config.moneda, con_signo=False)
            attr_falta = (
                attr_negative() if por_dep.total_falta_depositar > 0 else attr_positive()
            )
            safe_addstr(
                win, r_y, right_x + 3, f"{'FALTA DEPOSITAR':<{r_col_w - 16}}", attr_title()
            )
            safe_addstr(win, r_y, right_x + right_w - 19, f"{falta_str:>15}", attr_falta)
