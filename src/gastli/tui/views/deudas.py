"""Vista 4: Tarjetas de Crédito y Deudas / Préstamos (Pasivos)."""
import curses
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from gastli.core import FinanceCore
from gastli.models import (
    Cuenta,
    Deuda,
    TarjetaCredito,
    TipoCuenta,
    TipoMovimiento,
    centavos_a_str,
    parse_monto_a_centavos,
)
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
from gastli.tui.widgets import FormModal, TableWidget, draw_box, draw_progress_bar, safe_addstr


class DeudasView:
    def __init__(
        self,
        core: FinanceCore,
        abrir_modal: Callable[[Any], None],
        notificar: Callable[[str], None],
    ):
        self.core = core
        self.abrir_modal = abrir_modal
        self.notificar = notificar

        # Dos tablas: arriba Tarjetas, abajo Deudas
        headers_tarjetas = [
            ("Tarjeta", 16, "L"),
            ("Límite", 12, "R"),
            ("Saldo Actual", 13, "R"),
            ("Disponible", 12, "R"),
            ("Uso", 18, "L"),
            ("Corte", 7, "R"),
            ("Pago", 7, "R"),
            ("No Intereses", 13, "R"),
        ]
        self.table_tarjetas = TableWidget(headers_tarjetas, box_title="Tarjetas de Crédito")

        headers_deudas = [
            ("Préstamo / Deuda", 22, "L"),
            ("Monto Original", 14, "R"),
            ("Saldo Restante", 14, "R"),
            ("Cuota Periódica", 15, "R"),
            ("Días al Vence", 13, "R"),
            ("Cuenta de Pago", 16, "L"),
        ]
        self.table_deudas = TableWidget(headers_deudas, box_title="Deudas y Préstamos Personales")

        self.panel_activo = 0  # 0: Tarjetas, 1: Deudas
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        config = self.core.db.get_config()

        # 1. Tarjetas
        detalles_tc = self.core.obtener_detalles_tarjetas()
        rows_tc = []
        attrs_tc = []
        for d in detalles_tc:
            barra = draw_progress_bar(d.porcentaje_uso, width=11)
            lim_str = centavos_a_str(d.tarjeta.limite_centavos, config.moneda, con_signo=False)
            sal_str = centavos_a_str(d.saldo_actual, config.moneda, con_signo=False)
            disp_str = centavos_a_str(d.credito_disponible, config.moneda, con_signo=False)
            no_int_str = centavos_a_str(d.pago_para_no_intereses, config.moneda, con_signo=False)

            corte_info = f"{d.dias_al_corte}d"
            pago_info = f"{d.dias_al_pago}d"

            attr_tc = attr_warning() if d.dias_al_pago <= 3 else attr_normal()
            rows_tc.append(
                [
                    d.cuenta.nombre,
                    lim_str,
                    sal_str,
                    disp_str,
                    barra,
                    corte_info,
                    pago_info,
                    no_int_str,
                ]
            )
            attrs_tc.append(attr_tc)
        self.table_tarjetas.set_data(rows_tc, attrs_tc)

        # 2. Deudas
        detalles_deu = self.core.obtener_detalles_deudas()
        rows_deu = []
        attrs_deu = []
        for d in detalles_deu:
            orig_str = centavos_a_str(d.deuda.monto_original_centavos, config.moneda, con_signo=False)
            rest_str = centavos_a_str(d.saldo_restante, config.moneda, con_signo=False)
            cuot_str = centavos_a_str(d.cuota_centavos, config.moneda, con_signo=False)

            attr_d = attr_warning() if d.dias_al_pago <= 3 else attr_normal()
            rows_deu.append(
                [
                    d.cuenta.nombre,
                    orig_str,
                    rest_str,
                    cuot_str,
                    f"{d.dias_al_pago} días",
                    d.cuenta_pago_nombre,
                ]
            )
            attrs_deu.append(attr_d)
        self.table_deudas.set_data(rows_deu, attrs_deu)

    def handle_key(self, ch: int) -> bool:
        if ch in (ord("\t"),):  # Tab cambia entre tabla tarjetas y tabla deudas
            self.panel_activo = 1 - self.panel_activo
            return True

        if self.panel_activo == 0:
            if self.table_tarjetas.handle_key(ch):
                return True
        else:
            if self.table_deudas.handle_key(ch):
                return True

        if ch in (ord("p"), ord("P")):
            self.accion_pagar()
            return True
        elif ch in (ord("c"), ord("C")):
            self.accion_nueva_tarjeta_o_deuda()
            return True
        elif ch in (ord("e"), ord("E"), ord("\n"), ord("\r"), curses.KEY_ENTER):
            self.accion_modificar_pasivo()
            return True
        elif ch in (ord("d"), ord("D")):
            self.accion_borrar_pasivo()
            return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        btn_y = self.y + self.h - 1
        if es_clic(bstate) and my == btn_y and self.x <= mx < self.x + self.w:
            rel_x = mx - self.x
            if rel_x <= 12:
                self.accion_pagar()
                return True
            elif 13 <= rel_x <= 23:
                self.accion_nueva_tarjeta_o_deuda()
                return True
            elif 24 <= rel_x <= 38:
                self.accion_modificar_pasivo()
                return True
            elif 39 <= rel_x <= 50:
                self.accion_borrar_pasivo()
                return True
            elif rel_x >= 51:
                self.panel_activo = 1 - self.panel_activo
                return True

        # Detectar clic en tabla superior o inferior
        alto_split = (self.h - 2) // 2
        split_y = self.y + alto_split

        if my < split_y:
            self.panel_activo = 0
            consumido, doble_clic = self.table_tarjetas.handle_mouse(my, mx, bstate)
            if doble_clic:
                self.accion_modificar_pasivo()
            return consumido
        else:
            self.panel_activo = 1
            consumido, doble_clic = self.table_deudas.handle_mouse(my, mx, bstate)
            if doble_clic:
                self.accion_modificar_pasivo()
            return consumido

    def get_cuenta_seleccionada(self) -> Optional[Cuenta]:
        if self.panel_activo == 0:
            detalles = self.core.obtener_detalles_tarjetas()
            if not self.table_tarjetas.rows or self.table_tarjetas.selected_index >= len(detalles):
                return None
            return detalles[self.table_tarjetas.selected_index].cuenta
        else:
            detalles = self.core.obtener_detalles_deudas()
            if not self.table_deudas.rows or self.table_deudas.selected_index >= len(detalles):
                return None
            return detalles[self.table_deudas.selected_index].cuenta

    def accion_pagar(self):
        cta_pasivo = self.get_cuenta_seleccionada()
        if not cta_pasivo:
            self.notificar("Selecciona una tarjeta o deuda para pagar.")
            return

        # Buscar saldo deudor actual y pago sugerido
        saldo_deudor = self.core.calcular_saldo_cuenta(cta_pasivo.id)
        if saldo_deudor <= 0:
            self.notificar(f"{cta_pasivo.nombre} no tiene saldo pendiente por pagar.")
            return

        monto_sugerido = saldo_deudor
        if cta_pasivo.tipo == TipoCuenta.CREDITO:
            tc_det = [
                d for d in self.core.obtener_detalles_tarjetas() if d.cuenta.id == cta_pasivo.id
            ]
            if tc_det and tc_det[0].pago_para_no_intereses > 0:
                monto_sugerido = tc_det[0].pago_para_no_intereses

        # Cuentas de activos para debitar
        cuentas_activos = [c for c in self.core.db.get_cuentas() if c.es_activo]
        if not cuentas_activos:
            self.notificar("No hay cuentas de débito o efectivo para realizar el pago.")
            return

        nombres_activos = [c.nombre for c in cuentas_activos]
        ids_activos = [c.id for c in cuentas_activos]

        # Priorizar cuenta_pago asignada
        idx_origen = (
            ids_activos.index(cta_pasivo.cuenta_pago_id)
            if cta_pasivo.cuenta_pago_id in ids_activos
            else 0
        )

        campos = [
            {
                "key": "monto",
                "label": "Monto a pagar:",
                "type": "number",
                "value": f"{monto_sugerido / 100.0:.2f}",
            },
            {
                "key": "origen",
                "label": "Cuenta de débito/origen:",
                "type": "choice",
                "options": nombres_activos,
                "value": idx_origen,
            },
            {
                "key": "nota",
                "label": "Nota del pago:",
                "type": "text",
                "value": f"Pago a {cta_pasivo.nombre}",
            },
        ]

        def on_guardar(vals):
            try:
                centavos = parse_monto_a_centavos(vals["monto"])
                idx_orig = (
                    vals["origen"]
                    if isinstance(vals["origen"], int)
                    else nombres_activos.index(vals["origen"])
                )
                cta_origen_id = ids_activos[idx_orig]

                self.core.registrar_pago_pasivo(
                    cuenta_pasivo_id=cta_pasivo.id,
                    cuenta_activo_id=cta_origen_id,
                    monto_centavos=centavos,
                    nota=vals["nota"],
                )
                self.cargar_datos()
                self.abrir_modal(None)
                self.notificar(
                    f"Pago de {centavos_a_str(centavos)} registrado a '{cta_pasivo.nombre}'."
                )
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal(
            f"Registrar Pago a {cta_pasivo.nombre}",
            campos,
            on_guardar,
            lambda: self.abrir_modal(None),
        )
        self.abrir_modal(modal)

    def accion_nueva_tarjeta_o_deuda(self):
        tipos = ["Tarjeta de Crédito", "Préstamo / Deuda"]
        cuentas_debito = [c for c in self.core.db.get_cuentas() if c.tipo == TipoCuenta.DEBITO]
        nombres_debito = ["(Ninguna)"] + [c.nombre for c in cuentas_debito]
        ids_debito = [None] + [c.id for c in cuentas_debito]

        campos = [
            {"key": "nombre", "label": "Nombre:", "type": "text", "value": ""},
            {
                "key": "tipo",
                "label": "Tipo de pasivo:",
                "type": "choice",
                "options": tipos,
                "value": self.panel_activo,
            },
            {
                "key": "monto",
                "label": "Límite o Monto Original:",
                "type": "number",
                "value": "8000.00",
            },
            {
                "key": "dia_corte",
                "label": "Día de corte / día pago (1-31):",
                "type": "number",
                "value": "15",
            },
            {
                "key": "dia_pago",
                "label": "Día límite pago / cuota día:",
                "type": "number",
                "value": "5",
            },
            {
                "key": "cuenta_pago",
                "label": "Cuenta de débito asociada:",
                "type": "choice",
                "options": nombres_debito,
                "value": 1 if len(ids_debito) > 1 else 0,
            },
        ]

        def on_guardar(vals):
            try:
                nombre = vals["nombre"].strip()
                if not nombre:
                    self.notificar("El nombre no puede estar vacío.")
                    return
                t_idx = vals["tipo"] if isinstance(vals["tipo"], int) else tipos.index(vals["tipo"])
                centavos = parse_monto_a_centavos(vals["monto"])
                dia_c = max(1, min(31, int(vals["dia_corte"])))
                dia_p = max(1, min(31, int(vals["dia_pago"])))

                idx_deb = (
                    vals["cuenta_pago"]
                    if isinstance(vals["cuenta_pago"], int)
                    else nombres_debito.index(vals["cuenta_pago"])
                )
                cta_pago_id = ids_debito[idx_deb]

                if t_idx == 0:
                    # Tarjeta
                    cid = self.core.db.crear_cuenta(
                        nombre,
                        TipoCuenta.CREDITO,
                        saldo_inicial_centavos=0,
                        cuenta_pago_id=cta_pago_id,
                    )
                    tc = TarjetaCredito(
                        cuenta_id=cid,
                        limite_centavos=centavos,
                        dia_corte=dia_c,
                        dia_limite_pago=dia_p,
                    )
                    self.core.db.guardar_tarjeta(tc)
                else:
                    # Deuda
                    cid = self.core.db.crear_cuenta(
                        nombre,
                        TipoCuenta.DEUDA,
                        saldo_inicial_centavos=0,
                        cuenta_pago_id=cta_pago_id,
                    )
                    deu = Deuda(
                        cuenta_id=cid,
                        monto_original_centavos=centavos,
                        cuota_centavos=centavos // 12 or 10000,
                        dia_pago=dia_c,
                        fecha_inicio=date.today().strftime("%Y-%m-%d"),
                    )
                    self.core.db.guardar_deuda(deu)

                self.cargar_datos()
                if t_idx == 0:
                    for i, d in enumerate(self.core.obtener_detalles_tarjetas()):
                        if d.cuenta.id == cid:
                            self.table_tarjetas.selected_index = i
                            break
                else:
                    for i, d in enumerate(self.core.obtener_detalles_deudas()):
                        if d.cuenta.id == cid:
                            self.table_deudas.selected_index = i
                            break
                self.abrir_modal(None)
                self.notificar(f"Pasivo '{nombre}' registrado con éxito.")
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal(
            "Nuevo Pasivo (Tarjeta o Deuda)", campos, on_guardar, lambda: self.abrir_modal(None)
        )
        self.abrir_modal(modal)

    def accion_modificar_pasivo(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            self.notificar("Selecciona una tarjeta o deuda para modificar.")
            return

        cuentas_debito = [c for c in self.core.db.get_cuentas() if c.tipo == TipoCuenta.DEBITO]
        nombres_debito = ["(Ninguna)"] + [c.nombre for c in cuentas_debito]
        ids_debito = [None] + [c.id for c in cuentas_debito]
        idx_deb = ids_debito.index(cta.cuenta_pago_id) if cta.cuenta_pago_id in ids_debito else 0

        if cta.tipo == TipoCuenta.CREDITO:
            tc = self.core.db.get_tarjeta(cta.id)
            if not tc:
                self.notificar(f"No se encontraron datos de la tarjeta '{cta.nombre}'.")
                return

            campos = [
                {"key": "nombre", "label": "Nombre:", "type": "text", "value": cta.nombre},
                {
                    "key": "limite",
                    "label": "Límite de crédito:",
                    "type": "number",
                    "value": f"{tc.limite_centavos / 100.0:.2f}",
                },
                {
                    "key": "dia_corte",
                    "label": "Día de corte (1-31):",
                    "type": "number",
                    "value": str(tc.dia_corte),
                },
                {
                    "key": "dia_pago",
                    "label": "Día límite pago (1-31):",
                    "type": "number",
                    "value": str(tc.dia_limite_pago),
                },
                {
                    "key": "cuenta_pago",
                    "label": "Cuenta de débito asociada:",
                    "type": "choice",
                    "options": nombres_debito,
                    "value": idx_deb,
                },
            ]

            def on_guardar_tc(vals):
                try:
                    nombre = vals["nombre"].strip()
                    if not nombre:
                        self.notificar("El nombre no puede estar vacío.")
                        return
                    limite_centavos = parse_monto_a_centavos(vals["limite"])
                    dia_c = max(1, min(31, int(vals["dia_corte"])))
                    dia_p = max(1, min(31, int(vals["dia_pago"])))

                    idx_d = (
                        vals["cuenta_pago"]
                        if isinstance(vals["cuenta_pago"], int)
                        else nombres_debito.index(vals["cuenta_pago"])
                    )
                    cta_pago_id = ids_debito[idx_d]

                    self.core.db.actualizar_cuenta(cta.id, nombre=nombre, cuenta_pago_id=cta_pago_id)
                    tc.limite_centavos = limite_centavos
                    tc.dia_corte = dia_c
                    tc.dia_limite_pago = dia_p
                    self.core.db.guardar_tarjeta(tc)

                    self.cargar_datos()
                    for i, d in enumerate(self.core.obtener_detalles_tarjetas()):
                        if d.cuenta.id == cta.id:
                            self.table_tarjetas.selected_index = i
                            break
                    self.abrir_modal(None)
                    self.notificar(f"Tarjeta '{nombre}' actualizada correctamente.")
                except Exception as e:
                    self.notificar(f"Error al actualizar: {e}")

            modal = FormModal(
                f"Modificar Tarjeta: {cta.nombre}", campos, on_guardar_tc, lambda: self.abrir_modal(None)
            )
            self.abrir_modal(modal)

        elif cta.tipo == TipoCuenta.DEUDA:
            deu = self.core.db.get_deuda(cta.id)
            if not deu:
                self.notificar(f"No se encontraron datos de la deuda '{cta.nombre}'.")
                return

            campos = [
                {"key": "nombre", "label": "Nombre:", "type": "text", "value": cta.nombre},
                {
                    "key": "monto_original",
                    "label": "Monto original:",
                    "type": "number",
                    "value": f"{deu.monto_original_centavos / 100.0:.2f}",
                },
                {
                    "key": "cuota",
                    "label": "Cuota periódica:",
                    "type": "number",
                    "value": f"{deu.cuota_centavos / 100.0:.2f}",
                },
                {
                    "key": "dia_pago",
                    "label": "Día de pago (1-31):",
                    "type": "number",
                    "value": str(deu.dia_pago),
                },
                {
                    "key": "cuenta_pago",
                    "label": "Cuenta de débito asociada:",
                    "type": "choice",
                    "options": nombres_debito,
                    "value": idx_deb,
                },
            ]

            def on_guardar_deu(vals):
                try:
                    nombre = vals["nombre"].strip()
                    if not nombre:
                        self.notificar("El nombre no puede estar vacío.")
                        return
                    monto_centavos = parse_monto_a_centavos(vals["monto_original"])
                    cuota_centavos = parse_monto_a_centavos(vals["cuota"])
                    dia_p = max(1, min(31, int(vals["dia_pago"])))

                    idx_d = (
                        vals["cuenta_pago"]
                        if isinstance(vals["cuenta_pago"], int)
                        else nombres_debito.index(vals["cuenta_pago"])
                    )
                    cta_pago_id = ids_debito[idx_d]

                    self.core.db.actualizar_cuenta(cta.id, nombre=nombre, cuenta_pago_id=cta_pago_id)
                    deu.monto_original_centavos = monto_centavos
                    deu.cuota_centavos = cuota_centavos
                    deu.dia_pago = dia_p
                    self.core.db.guardar_deuda(deu)

                    self.cargar_datos()
                    for i, d in enumerate(self.core.obtener_detalles_deudas()):
                        if d.cuenta.id == cta.id:
                            self.table_deudas.selected_index = i
                            break
                    self.abrir_modal(None)
                    self.notificar(f"Deuda '{nombre}' actualizada correctamente.")
                except Exception as e:
                    self.notificar(f"Error al actualizar: {e}")

            modal = FormModal(
                f"Modificar Deuda: {cta.nombre}", campos, on_guardar_deu, lambda: self.abrir_modal(None)
            )
            self.abrir_modal(modal)

    def accion_borrar_pasivo(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            self.notificar("Selecciona una tarjeta o deuda para eliminar.")
            return

        from gastli.tui.widgets import ConfirmModal

        def on_confirmar():
            self.core.db.borrar_cuenta(cta.id)
            self.cargar_datos()
            self.abrir_modal(None)
            self.notificar(f"'{cta.nombre}' y sus registros han sido eliminados.")

        modal = ConfirmModal(
            "Eliminar Pasivo",
            f"¿Deseas eliminar '{cta.nombre}' y todos sus registros?",
            on_confirmar,
            lambda: self.abrir_modal(None),
        )
        self.abrir_modal(modal)

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w

        alto_util = h - 2
        alto_tarjetas = alto_util // 2
        alto_deudas = alto_util - alto_tarjetas

        foco_tc = self.panel_activo == 0
        foco_deu = self.panel_activo == 1

        # Tabla superior: Tarjetas
        self.table_tarjetas.render(win, y, x, alto_tarjetas, w, tiene_foco=foco_tc)

        # Tabla inferior: Deudas
        self.table_deudas.render(
            win, y + alto_tarjetas, x, alto_deudas, w, tiene_foco=foco_deu
        )

        # Barra inferior de acciones
        btn_y = y + h - 1
        safe_addstr(win, btn_y, x + 2, "[p] Pagar", attr_title())
        safe_addstr(win, btn_y, x + 13, "[c] Nueva", attr_title())
        safe_addstr(win, btn_y, x + 24, "[e] Modificar", attr_title())
        safe_addstr(win, btn_y, x + 39, "[d] Borrar", attr_warning())
        safe_addstr(win, btn_y, x + 52, "[Tab] Cambiar tabla", attr_muted())
