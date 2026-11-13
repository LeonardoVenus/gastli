"""Vista 3: Cuentas de Débito y Efectivo (Activos)."""
import curses
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from gastli.core import FinanceCore
from gastli.models import Cuenta, Movimiento, TipoCuenta, TipoMovimiento, centavos_a_str, parse_monto_a_centavos
from gastli.tui.theme import (
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
from gastli.tui.widgets import FormModal, TableWidget, draw_box, safe_addstr


class CuentasView:
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
            ("Nombre de Cuenta", 24, "L"),
            ("Tipo", 12, "L"),
            ("Saldo Actual", 16, "R"),
            ("Total Depositado", 18, "R"),
            ("Estado", 10, "L"),
        ]
        self.table = TableWidget(headers, box_title="Cuentas de Débito y Efectivo (Activos)")
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def cargar_datos(self):
        cuentas = self.core.db.get_cuentas(incluir_archivadas=True)
        config = self.core.db.get_config()

        rows = []
        attrs = []
        for c in cuentas:
            if not c.es_activo:
                continue
            saldo = self.core.calcular_saldo_cuenta(c.id)
            depositado = self.core.calcular_total_depositado(c.id)
            estado = "Archivada" if c.archivada else "Activa"

            s_str = centavos_a_str(saldo, config.moneda, con_signo=True)
            d_str = centavos_a_str(depositado, config.moneda, con_signo=False)

            row_attr = attr_muted() if c.archivada else (attr_positive() if saldo > 0 else attr_normal())
            rows.append([c.id, c.nombre, c.tipo.capitalize(), s_str, d_str, estado])
            attrs.append(row_attr)

        self.table.set_data(rows, attrs)

    def get_cuenta_seleccionada(self) -> Optional[Cuenta]:
        if not self.table.rows or self.table.selected_index >= len(self.table.rows):
            return None
        fila = self.table.rows[self.table.selected_index]
        return self.core.db.get_cuenta(fila[0])

    def handle_key(self, ch: int) -> bool:
        if self.table.handle_key(ch):
            return True

        if ch in (ord("i"), ord("I")):
            self.accion_depositar()
            return True
        elif ch in (ord("t"), ord("T")):
            self.accion_transferir()
            return True
        elif ch in (ord("a"), ord("A")):
            self.accion_ajustar_saldo()
            return True
        elif ch in (ord("c"), ord("C")):
            self.accion_crear_cuenta()
            return True
        elif ch in (ord("e"), ord("E"), ord("r"), ord("R"), ord("\n"), ord("\r"), curses.KEY_ENTER):
            self.accion_modificar_cuenta()
            return True
        elif ch in (ord("d"), ord("D")):
            self.accion_borrar_cuenta()
            return True
        elif ch in (ord("x"), ord("X")):
            self.accion_archivar_cuenta()
            return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> bool:
        from gastli.tui.widgets import es_clic
        # Clic en botones de acción inferiores
        btn_y = self.y + self.h - 1
        if es_clic(bstate) and my == btn_y and self.x <= mx < self.x + self.w:
            rel_x = mx - self.x
            if rel_x <= 15:
                self.accion_depositar()
            elif 16 <= rel_x <= 27:
                self.accion_transferir()
            elif 28 <= rel_x <= 40:
                self.accion_ajustar_saldo()
            elif 41 <= rel_x <= 51:
                self.accion_crear_cuenta()
            elif 52 <= rel_x <= 66:
                self.accion_modificar_cuenta()
            elif 67 <= rel_x <= 77:
                self.accion_borrar_cuenta()
            elif rel_x >= 78:
                self.accion_archivar_cuenta()
            return True

        consumido, doble_clic = self.table.handle_mouse(my, mx, bstate)
        if doble_clic:
            self.accion_modificar_cuenta()
        return consumido

    def accion_depositar(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            return

        campos = [
            {"key": "monto", "label": "Monto a depositar:", "type": "number", "value": ""},
            {"key": "nota", "label": "Concepto / Nota:", "type": "text", "value": "Depósito bancario"},
        ]

        def on_guardar(vals):
            try:
                centavos = parse_monto_a_centavos(vals["monto"])
                cat_id = self.core.db.get_or_create_categoria("Ingresos extra")
                hoy_str = date.today().strftime("%Y-%m-%d")
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.INGRESO,
                    monto_centavos=centavos,
                    cuenta_destino_id=cta.id,
                    categoria_id=cat_id,
                    nota=vals["nota"],
                )
                self.core.db.agregar_movimiento(mov)
                self.cargar_datos()
                self.abrir_modal(None)
                self.notificar(f"Depósito registrado en '{cta.nombre}'")
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal(f"Depositar en {cta.nombre}", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_transferir(self):
        cta_orig = self.get_cuenta_seleccionada()
        cuentas = [c for c in self.core.db.get_cuentas() if c.es_activo]
        if len(cuentas) < 2:
            self.notificar("Se necesitan al menos 2 cuentas de activos para transferir.")
            return

        nombres = [c.nombre for c in cuentas]
        ids = [c.id for c in cuentas]
        idx_origen = ids.index(cta_orig.id) if cta_orig and cta_orig.id in ids else 0
        idx_dest = (idx_origen + 1) % len(nombres)

        campos = [
            {"key": "monto", "label": "Monto a transferir:", "type": "number", "value": ""},
            {"key": "origen", "label": "Cuenta origen:", "type": "choice", "options": nombres, "value": idx_origen},
            {"key": "destino", "label": "Cuenta destino:", "type": "choice", "options": nombres, "value": idx_dest},
            {"key": "nota", "label": "Nota:", "type": "text", "value": "Transferencia"},
        ]

        def on_guardar(vals):
            try:
                centavos = parse_monto_a_centavos(vals["monto"])
                idx_o = vals["origen"] if isinstance(vals["origen"], int) else nombres.index(vals["origen"])
                idx_d = vals["destino"] if isinstance(vals["destino"], int) else nombres.index(vals["destino"])
                if ids[idx_o] == ids[idx_d]:
                    self.notificar("La cuenta de origen y destino deben ser distintas.")
                    return

                hoy_str = date.today().strftime("%Y-%m-%d")
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.TRANSFERENCIA,
                    monto_centavos=centavos,
                    cuenta_origen_id=ids[idx_o],
                    cuenta_destino_id=ids[idx_d],
                    nota=vals["nota"],
                )
                self.core.db.agregar_movimiento(mov)
                self.cargar_datos()
                self.abrir_modal(None)
                self.notificar(f"Transferencia de {centavos_a_str(centavos)} realizada")
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal("Transferencia entre Cuentas", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_ajustar_saldo(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            return

        saldo_actual = self.core.calcular_saldo_cuenta(cta.id)
        config = self.core.db.get_config()

        campos = [
            {
                "key": "saldo_real",
                "label": f"Saldo real en {cta.nombre}:",
                "type": "number",
                "value": f"{saldo_actual / 100.0:.2f}",
            },
            {"key": "nota", "label": "Motivo del ajuste:", "type": "text", "value": "Ajuste con estado de cuenta"},
        ]

        def on_guardar(vals):
            try:
                nuevo_centavos = parse_monto_a_centavos(vals["saldo_real"])
                self.core.ajustar_saldo_cuenta(cta.id, nuevo_centavos, nota=vals["nota"])
                self.cargar_datos()
                self.abrir_modal(None)
                self.notificar(f"Saldo ajustado a {centavos_a_str(nuevo_centavos, config.moneda)}")
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal(f"Ajustar Saldo ({cta.nombre})", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_crear_cuenta(self):
        tipos = ["debito", "efectivo"]
        campos = [
            {"key": "nombre", "label": "Nombre de la cuenta:", "type": "text", "value": ""},
            {"key": "tipo", "label": "Tipo de cuenta:", "type": "choice", "options": ["Débito", "Efectivo"], "value": 0},
            {"key": "saldo_inicial", "label": "Saldo inicial:", "type": "number", "value": "0.00"},
        ]

        def on_guardar(vals):
            try:
                nombre = vals["nombre"].strip()
                if not nombre:
                    self.notificar("El nombre no puede estar vacío.")
                    return
                t_idx = vals["tipo"] if isinstance(vals["tipo"], int) else 0
                tipo = tipos[t_idx]
                saldo_ini = parse_monto_a_centavos(vals["saldo_inicial"])
                cid = self.core.db.crear_cuenta(nombre, tipo, saldo_inicial_centavos=saldo_ini)
                self.cargar_datos()
                for i, r in enumerate(self.table.rows):
                    if r[0] == cid:
                        self.table.selected_index = i
                        break
                self.abrir_modal(None)
                self.notificar(f"Cuenta '{nombre}' creada con éxito.")
            except Exception as e:
                self.notificar(f"Error: {e}")

        modal = FormModal("Crear Nueva Cuenta", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_modificar_cuenta(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            self.notificar("Selecciona una cuenta para modificar.")
            return

        tipos = ["debito", "efectivo"]
        tipos_nombres = ["Débito", "Efectivo"]
        idx_tipo = tipos.index(cta.tipo) if cta.tipo in tipos else 0

        campos = [
            {"key": "nombre", "label": "Nombre de cuenta:", "type": "text", "value": cta.nombre},
            {"key": "tipo", "label": "Tipo de cuenta:", "type": "choice", "options": tipos_nombres, "value": idx_tipo},
        ]

        def on_guardar(vals):
            nuevo_nom = vals["nombre"].strip()
            if not nuevo_nom:
                self.notificar("El nombre no puede estar vacío.")
                return
            t_idx = vals["tipo"] if isinstance(vals["tipo"], int) else tipos_nombres.index(vals["tipo"])
            nuevo_tipo = tipos[t_idx]
            try:
                self.core.db.actualizar_cuenta(
                    cta.id,
                    nombre=nuevo_nom,
                    cuenta_pago_id=cta.cuenta_pago_id,
                    archivada=cta.archivada,
                    tipo=nuevo_tipo,
                )
                self.cargar_datos()
                for i, r in enumerate(self.table.rows):
                    if r[0] == cta.id:
                        self.table.selected_index = i
                        break
                self.abrir_modal(None)
                self.notificar(f"Cuenta '{nuevo_nom}' actualizada con éxito.")
            except Exception as e:
                self.notificar(f"Error al actualizar: {e}")

        modal = FormModal(f"Modificar Cuenta: {cta.nombre}", campos, on_guardar, lambda: self.abrir_modal(None))
        self.abrir_modal(modal)

    def accion_renombrar_cuenta(self):
        self.accion_modificar_cuenta()

    def accion_borrar_cuenta(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            return

        from gastli.tui.widgets import ConfirmModal

        def on_confirmar():
            self.core.db.borrar_cuenta(cta.id)
            self.cargar_datos()
            self.abrir_modal(None)
            self.notificar(f"Cuenta '{cta.nombre}' y sus movimientos eliminados.")

        modal = ConfirmModal(
            "Eliminar Cuenta",
            f"¿Deseas eliminar '{cta.nombre}' y todos sus movimientos?",
            on_confirmar,
            lambda: self.abrir_modal(None),
        )
        self.abrir_modal(modal)

    def accion_archivar_cuenta(self):
        cta = self.get_cuenta_seleccionada()
        if not cta:
            return
        nuevo_estado = not cta.archivada
        self.core.db.actualizar_cuenta(cta.id, cta.nombre, cta.cuenta_pago_id, archivada=nuevo_estado)
        self.cargar_datos()
        txt = "archivada" if nuevo_estado else "reactivada"
        self.notificar(f"Cuenta '{cta.nombre}' {txt}.")

    def render(self, win, y: int, x: int, h: int, w: int):
        self.y, self.x, self.h, self.w = y, x, h, w

        # Tabla ocupa casi todo el alto menos barra de botones
        alto_tabla = h - 2
        self.table.render(win, y, x, alto_tabla, w, tiene_foco=True)

        # Barra inferior de botones de acción
        btn_y = y + h - 1
        safe_addstr(win, btn_y, x + 2, "[i] Depósito", attr_title())
        safe_addstr(win, btn_y, x + 16, "[t] Transf", attr_title())
        safe_addstr(win, btn_y, x + 28, "[a] Ajustar", attr_title())
        safe_addstr(win, btn_y, x + 41, "[c] Nueva", attr_title())
        safe_addstr(win, btn_y, x + 52, "[e] Modificar", attr_title())
        safe_addstr(win, btn_y, x + 67, "[d] Borrar", attr_warning())
        if w >= 88:
            safe_addstr(win, btn_y, x + 79, "[x] Archivar", attr_muted())
        else:
            safe_addstr(win, btn_y, x + 79, "[x]", attr_muted())
