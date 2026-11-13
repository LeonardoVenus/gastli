"""Controlador principal de la aplicación TUI en Curses."""
import curses
import os
import sys
from datetime import date
from typing import Any, List, Optional

from gastli import paths
from gastli.core import FinanceCore
from gastli.models import Movimiento, TipoCuenta, TipoMovimiento, centavos_a_str, parse_monto_a_centavos
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
    attr_topbar,
    attr_warning,
    inicializar_colores,
)
from gastli.tui.views.ajustes import AjustesView
from gastli.tui.views.cuentas import CuentasView
from gastli.tui.views.deudas import DeudasView
from gastli.tui.views.efectivo import EfectivoView
from gastli.tui.views.hormiga import HormigaView
from gastli.tui.views.movimientos import MovimientosView
from gastli.tui.views.resumen import ResumenView
from gastli.tui.widgets import ConfirmModal, FormModal, HelpModal, draw_box, safe_addstr


class TUIApp:
    def __init__(self, core: FinanceCore):
        self.core = core
        self.tab_activa = 0  # 0: Resumen, 1: Movim, 2: Cuentas, 3: Deudas, 4: Efectivo, 5: Hormiga, 6: Ajustes
        self.tabs = [
            ("1 Resumen", 0),
            ("2 Movim.", 1),
            ("3 Cuentas", 2),
            ("4 Deudas", 3),
            ("5 Efectivo", 4),
            ("6 Hormiga", 5),
            ("7 Ajustes", 6),
        ]
        self.modal_activa: Optional[Any] = None
        self.notificacion: Optional[str] = None
        self.notificacion_ticks: int = 0

        # Modo línea de comando (:)
        self.modo_comando = False
        self.comando_texto = ""

        # Modo búsqueda (/)
        self.modo_busqueda = False
        self.busqueda_texto = ""

        # Inicializar vistas
        self.views = [
            ResumenView(core),
            MovimientosView(core, self.abrir_modal, self.notificar),
            CuentasView(core, self.abrir_modal, self.notificar),
            DeudasView(core, self.abrir_modal, self.notificar),
            EfectivoView(core, self.abrir_modal, self.notificar),
            HormigaView(core, self.abrir_modal, self.notificar),
            AjustesView(core, self.abrir_modal, self.notificar),
        ]

        # Recordar última selección de categorías y cuentas
        self.ultima_cuenta_id: Optional[int] = None
        self.ultima_categoria_id: Optional[int] = None

    def abrir_modal(self, modal: Optional[Any]):
        self.modal_activa = modal

    def notificar(self, mensaje: str):
        self.notificacion = mensaje
        self.notificacion_ticks = 15

    def cambiar_tab(self, nueva_tab: int):
        if 0 <= nueva_tab < len(self.views):
            self.tab_activa = nueva_tab
            self.recargar_vista_actual()

    def recargar_vista_actual(self):
        v = self.views[self.tab_activa]
        if hasattr(v, "cargar_datos"):
            v.cargar_datos()

    def accion_nuevo_movimiento(self):
        """Abre formulario para registrar un nuevo movimiento (gasto, ingreso, transf, pago)."""
        cuentas = self.core.db.get_cuentas(incluir_archivadas=False)
        categorias = self.core.db.get_categorias(solo_activas=True)

        if not cuentas:
            self.notificar("Debes tener al menos una cuenta registrada.")
            return

        cuentas_nombres = [c.nombre for c in cuentas]
        cuentas_ids = [c.id for c in cuentas]
        cat_nombres = [cat.nombre for cat in categorias]
        cat_ids = [cat.id for cat in categorias]

        tipos_mov = ["Gasto", "Ingreso", "Transferencia", "Pago"]

        idx_orig = 0
        if self.ultima_cuenta_id in cuentas_ids:
            idx_orig = cuentas_ids.index(self.ultima_cuenta_id)

        idx_cat = 0
        if self.ultima_categoria_id in cat_ids:
            idx_cat = cat_ids.index(self.ultima_categoria_id)

        campos = [
            {"key": "tipo", "label": "Tipo de movimiento:", "type": "choice", "options": tipos_mov, "value": 0},
            {"key": "monto", "label": "Monto:", "type": "number", "value": ""},
            {"key": "fecha", "label": "Fecha (+/- días):", "type": "date", "value": date.today().strftime("%Y-%m-%d")},
            {"key": "origen", "label": "Cuenta origen:", "type": "choice", "options": cuentas_nombres, "value": idx_orig},
            {"key": "destino", "label": "Cuenta destino (transf/pago):", "type": "choice", "options": ["(Ninguna)"] + cuentas_nombres, "value": 0},
            {"key": "categoria", "label": "Categoría (gasto/ingreso):", "type": "choice", "options": cat_nombres, "value": idx_cat},
            {"key": "nota", "label": "Concepto / Nota:", "type": "text", "value": ""},
        ]

        def on_guardar(vals):
            try:
                centavos = parse_monto_a_centavos(vals["monto"])
                if centavos <= 0:
                    self.notificar("El monto debe ser mayor a cero.")
                    return

                t_idx = vals["tipo"] if isinstance(vals["tipo"], int) else tipos_mov.index(vals["tipo"])
                tipo = [TipoMovimiento.GASTO, TipoMovimiento.INGRESO, TipoMovimiento.TRANSFERENCIA, TipoMovimiento.PAGO][t_idx]

                idx_o = vals["origen"] if isinstance(vals["origen"], int) else cuentas_nombres.index(vals["origen"])
                c_origen_id = cuentas_ids[idx_o]
                self.ultima_cuenta_id = c_origen_id

                c_destino_id = None
                idx_d = vals["destino"] if isinstance(vals["destino"], int) else (["(Ninguna)"] + cuentas_nombres).index(vals["destino"])
                if idx_d > 0:
                    c_destino_id = cuentas_ids[idx_d - 1]

                idx_c = vals["categoria"] if isinstance(vals["categoria"], int) else cat_nombres.index(vals["categoria"])
                cat_id = cat_ids[idx_c]
                self.ultima_categoria_id = cat_id

                # Validaciones semánticas
                if tipo == TipoMovimiento.TRANSFERENCIA:
                    if not c_destino_id or c_origen_id == c_destino_id:
                        self.notificar("La transferencia requiere cuenta de destino diferente.")
                        return
                    cat_id = None
                elif tipo == TipoMovimiento.PAGO:
                    if not c_destino_id:
                        self.notificar("El pago requiere seleccionar la tarjeta o deuda de destino.")
                        return
                    cat_id = None
                elif tipo == TipoMovimiento.INGRESO:
                    # En ingreso el dinero entra a la cuenta elegida
                    c_destino_id = c_origen_id
                    c_origen_id = None

                mov = Movimiento(
                    id=None,
                    fecha=vals["fecha"],
                    tipo=tipo,
                    monto_centavos=centavos,
                    cuenta_origen_id=c_origen_id,
                    cuenta_destino_id=c_destino_id,
                    categoria_id=cat_id,
                    nota=vals["nota"],
                )
                self.core.db.agregar_movimiento(mov)
                self.recargar_vista_actual()
                self.abrir_modal(None)
                self.notificar(f"{tipo.capitalize()} de {centavos_a_str(centavos)} registrado.")
            except Exception as e:
                self.notificar(f"Error al guardar: {e}")

        modal = FormModal("Nuevo Movimiento", campos, on_guardar, lambda: self.abrir_modal(None), ancho=66)
        self.abrir_modal(modal)

    def ejecutar_comando_interno(self, comando: str):
        cmd = comando.strip()
        if not cmd:
            return

        if cmd in ("q", "quit", "exit"):
            sys.exit(0)
        elif cmd in ("h", "help", "ayuda"):
            self.abrir_modal(HelpModal(lambda: self.abrir_modal(None)))
        elif cmd in ("export", "exportar"):
            try:
                ruta = os.path.join(paths.exports_dir(), "finanzas_export.xlsx")
                from gastli.export.xlsx import ExcelExporter
                ExcelExporter(self.core).exportar(ruta)
                self.notificar(f"Libro Excel generado en: {ruta}")
            except Exception as e:
                self.notificar(f"Error al exportar: {e}")
        elif cmd in ("backup", "respaldo"):
            try:
                r = self.core.db.realizar_respaldo()
                self.notificar(f"Respaldo creado: {os.path.basename(r)}" if r else "Error al respaldar")
            except Exception as e:
                self.notificar(f"Error al respaldar: {e}")
        elif cmd == "g" or cmd == "gasto":
            self.notificar("Uso: :g [monto] [concepto] (ej: :g 45 tacos)")
        elif cmd.startswith("g ") or cmd.startswith("gasto "):
            try:
                partes = cmd.split(maxsplit=2)
                if len(partes) < 2:
                    self.notificar("Uso: :g [monto] [concepto] (ej: :g 45 tacos)")
                    return
                centavos = parse_monto_a_centavos(partes[1])
                if centavos <= 0:
                    self.notificar("El monto debe ser mayor a cero.")
                    return
                concepto = partes[2] if len(partes) > 2 else "Gasto rápido"
                cuentas = self.core.db.get_cuentas(incluir_archivadas=False)
                cta = None
                for c in cuentas:
                    if "cartera" in c.nombre.lower() and c.es_activo:
                        cta = c
                        break
                if not cta:
                    for c in cuentas:
                        if c.es_activo:
                            cta = c
                            break
                if not cta:
                    self.notificar("No hay cuentas activas de débito o efectivo.")
                    return
                cat_id = self.core.db.get_or_create_categoria("Varios pequeños")
                hoy_str = date.today().strftime("%Y-%m-%d")
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.GASTO,
                    monto_centavos=centavos,
                    cuenta_origen_id=cta.id,
                    categoria_id=cat_id,
                    nota=concepto,
                )
                self.core.db.agregar_movimiento(mov)
                self.recargar_vista_actual()
                self.notificar(f"Gasto de {centavos_a_str(centavos)} registrado en '{cta.nombre}' ({concepto}).")
            except Exception as e:
                self.notificar(f"Error en :g: {e}")
        elif cmd == "t" or cmd == "transfer":
            self.notificar("Uso: :t [monto] [origen] [destino] (ej: :t 200 BBVA Cartera)")
        elif cmd.startswith("t ") or cmd.startswith("transfer "):
            try:
                partes = cmd.split()
                if len(partes) < 4:
                    self.notificar("Uso: :t [monto] [origen] [destino] (ej: :t 200 BBVA Cartera)")
                    return
                centavos = parse_monto_a_centavos(partes[1])
                if centavos <= 0:
                    self.notificar("El monto debe ser mayor a cero.")
                    return
                cuentas = self.core.db.get_cuentas(incluir_archivadas=False)
                from gastli.cli import buscar_cuenta_por_texto
                cta_o = buscar_cuenta_por_texto(cuentas, partes[2])
                cta_d = buscar_cuenta_por_texto(cuentas, partes[3])
                if not cta_o:
                    self.notificar(f"Cuenta origen '{partes[2]}' no encontrada.")
                    return
                if not cta_d:
                    self.notificar(f"Cuenta destino '{partes[3]}' no encontrada.")
                    return
                if cta_o.id == cta_d.id:
                    self.notificar("Las cuentas origen y destino deben ser distintas.")
                    return
                hoy_str = date.today().strftime("%Y-%m-%d")
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.TRANSFERENCIA,
                    monto_centavos=centavos,
                    cuenta_origen_id=cta_o.id,
                    cuenta_destino_id=cta_d.id,
                    nota="Transferencia rápida",
                )
                self.core.db.agregar_movimiento(mov)
                self.recargar_vista_actual()
                self.notificar(f"Transferencia de {centavos_a_str(centavos)} de '{cta_o.nombre}' a '{cta_d.nombre}'.")
            except Exception as e:
                self.notificar(f"Error en :t: {e}")
        elif cmd == "p" or cmd == "pago":
            self.notificar("Uso: :p [monto] [destino] [origen opcional] (ej: :p 1000 Nu BBVA)")
        elif cmd.startswith("p ") or cmd.startswith("pago "):
            try:
                partes = cmd.split()
                if len(partes) < 3:
                    self.notificar("Uso: :p [monto] [destino] [origen opcional] (ej: :p 1000 Nu BBVA)")
                    return
                centavos = parse_monto_a_centavos(partes[1])
                if centavos <= 0:
                    self.notificar("El monto debe ser mayor a cero.")
                    return
                cuentas = self.core.db.get_cuentas(incluir_archivadas=False)
                from gastli.cli import buscar_cuenta_por_texto
                cta_dest = buscar_cuenta_por_texto(cuentas, partes[2])
                if not cta_dest or not cta_dest.es_pasivo:
                    self.notificar(f"Pasivo '{partes[2]}' no encontrado.")
                    return
                cta_orig = None
                if len(partes) >= 4:
                    cta_orig = buscar_cuenta_por_texto(cuentas, partes[3])
                elif cta_dest.cuenta_pago_id:
                    cta_orig = self.core.db.get_cuenta(cta_dest.cuenta_pago_id)
                if not cta_orig:
                    for c in cuentas:
                        if c.tipo == TipoCuenta.DEBITO:
                            cta_orig = c
                            break
                if not cta_orig:
                    self.notificar("No se encontró cuenta de débito para efectuar el pago.")
                    return
                self.core.registrar_pago_pasivo(
                    cuenta_pasivo_id=cta_dest.id,
                    cuenta_activo_id=cta_orig.id,
                    monto_centavos=centavos,
                    nota=f"Pago rápido a {cta_dest.nombre}",
                )
                self.recargar_vista_actual()
                self.notificar(f"Pago de {centavos_a_str(centavos)} registrado a '{cta_dest.nombre}'.")
            except Exception as e:
                self.notificar(f"Error en :p: {e}")
        else:
            self.notificar(f"Comando no reconocido: :{cmd} (escribe :help para ver ayuda)")

    def main_loop(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        inicializar_colores()

        # Activar captura de ratón (sólo clics y rueda; sin movimiento continuo)
        try:
            mascara_raton = (
                curses.BUTTON1_CLICKED
                | curses.BUTTON1_PRESSED
                | getattr(curses, "BUTTON1_RELEASED", 0)
                | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
                | getattr(curses, "BUTTON4_PRESSED", 0x10000)
                | getattr(curses, "BUTTON4_CLICKED", 0x20000)
                | getattr(curses, "BUTTON5_PRESSED", 0x200000)
                | getattr(curses, "BUTTON5_CLICKED", 0x400000)
            )
            curses.mousemask(mascara_raton)
            # Asegurar que los modos de rastreo continuo de xterm estén apagados
            sys.stdout.write("\033[?1003l\033[?1002l\033[?1000h")
            sys.stdout.flush()
        except Exception:
            pass

        stdscr.timeout(100)  # Ciclo cada 100ms para refresco y notificaciones

        self.recargar_vista_actual()

        while True:
            max_y, max_x = stdscr.getmaxyx()
            stdscr.erase()

            # Verificación de tamaño mínimo (80x24)
            if max_y < 24 or max_x < 80:
                draw_box(stdscr, 1, 2, 7, max_x - 4, title="Terminal demasiado pequeño")
                safe_addstr(stdscr, 3, 4, f"Se requiere un tamaño mínimo de terminal de 80x24.", attr_warning())
                safe_addstr(stdscr, 4, 4, f"Tamaño actual: {max_x}x{max_y}. Por favor amplía la ventana.", attr_normal())
                safe_addstr(stdscr, 5, 4, "Presiona 'q' para salir.", attr_muted())
                stdscr.refresh()
                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q")):
                    break
                continue

            # ---------------- 1. BARRA SUPERIOR DE PESTAÑAS ---------------- #
            pos_x = 1
            for nombre, idx in self.tabs:
                es_activa = idx == self.tab_activa
                c_attr = attr_tab_active() if es_activa else attr_topbar()
                tab_txt = f" {nombre} "
                safe_addstr(stdscr, 0, pos_x, tab_txt, c_attr)
                pos_x += len(tab_txt) + 1

            # Hora actual o versión al extremo derecho de la barra
            ahora_str = date.today().strftime("%d-%b-%Y")
            safe_addstr(stdscr, 0, max_x - len(ahora_str) - 2, ahora_str, attr_muted())

            # ---------------- 2. CONTENIDO DE LA VISTA ACTIVA ---------------- #
            alto_vista = max_y - 3
            ancho_vista = max_x
            self.views[self.tab_activa].render(stdscr, 1, 0, alto_vista, ancho_vista)

            # ---------------- 3. NOTIFICACIONES / STATUS ---------------- #
            if self.notificacion and self.notificacion_ticks > 0:
                safe_addstr(stdscr, max_y - 2, 2, f"• {self.notificacion}", attr_warning())
                self.notificacion_ticks -= 1
                if self.notificacion_ticks <= 0:
                    self.notificacion = None

            # ---------------- 4. PIE DE PÁGINA / COMANDO ---------------- #
            if self.modo_comando:
                guia = "Comandos: :g [monto] [nota]  :t [monto] [orig] [dest]  :p [monto] [dest] [orig]  :export  :backup  :q"
                safe_addstr(stdscr, max_y - 2, 2, guia, attr_muted())
                safe_addstr(stdscr, max_y - 1, 1, f":{self.comando_texto}█", attr_title())
            elif self.modo_busqueda:
                safe_addstr(stdscr, max_y - 1, 1, f"Buscar: {self.busqueda_texto}█", attr_title())
            else:
                pie_shortcuts = (
                    " n nuevo   : comando   / buscar   ? ayuda   u deshacer   q salir "
                )
                safe_addstr(stdscr, max_y - 1, 1, pie_shortcuts, attr_muted())

            # ---------------- 5. VENTANA MODAL (SI EXISTE) ---------------- #
            if self.modal_activa:
                self.modal_activa.render(stdscr)

            stdscr.refresh()

            # ---------------- PROCESAR ENTRADA ---------------- #
            try:
                ch = stdscr.getch()
            except curses.error:
                continue

            if ch == -1:
                continue

            if ch == curses.KEY_RESIZE:
                curses.resizeterm(*stdscr.getmaxyx())
                continue

            # Eventos de ratón
            if ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                    from gastli.tui.widgets import es_clic, es_scroll_arriba, es_scroll_abajo
                    if not (es_clic(bstate) or es_scroll_arriba(bstate) or es_scroll_abajo(bstate)):
                        continue

                    # Clic en barra de pestañas (fila 0)
                    if my == 0 and es_clic(bstate):
                        calc_x = 1
                        for _, idx in self.tabs:
                            ancho_tab = len(self.tabs[idx][0]) + 3
                            if calc_x <= mx < calc_x + ancho_tab:
                                self.cambiar_tab(idx)
                                break
                            calc_x += ancho_tab
                        continue

                    # Si hay modal activa, dirigir ratón a modal
                    if self.modal_activa and hasattr(self.modal_activa, "handle_mouse"):
                        self.modal_activa.handle_mouse(my, mx, bstate, 1, 0, alto_vista, ancho_vista)
                        continue

                    # De lo contrario, dirigir a vista activa
                    if hasattr(self.views[self.tab_activa], "handle_mouse"):
                        self.views[self.tab_activa].handle_mouse(my, mx, bstate)
                        continue
                except curses.error:
                    pass
                continue

            # Entrada en modo comando (:)
            if self.modo_comando:
                if ch in (27,):  # ESC
                    self.modo_comando = False
                    self.comando_texto = ""
                elif ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
                    cmd_ejecutar = self.comando_texto
                    self.modo_comando = False
                    self.comando_texto = ""
                    self.ejecutar_comando_interno(cmd_ejecutar)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    self.comando_texto = self.comando_texto[:-1]
                elif 32 <= ch <= 126:
                    self.comando_texto += chr(ch)
                continue

            # Entrada en modo búsqueda (/)
            if self.modo_busqueda:
                if ch in (27,):
                    self.modo_busqueda = False
                    self.busqueda_texto = ""
                elif ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
                    self.modo_busqueda = False
                    # Aplicar búsqueda en vista Movimientos
                    v_mov = self.views[1]
                    v_mov.filtro_texto = self.busqueda_texto or None
                    v_mov.cargar_datos()
                    self.cambiar_tab(1)
                    self.notificar(f"Filtro aplicado: '{self.busqueda_texto}'")
                    self.busqueda_texto = ""
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    self.busqueda_texto = self.busqueda_texto[:-1]
                elif 32 <= ch <= 126:
                    self.busqueda_texto += chr(ch)
                continue

            # Si hay modal activa, dirigir teclas a modal
            if self.modal_activa:
                if self.modal_activa.handle_key(ch):
                    continue

            # Atajos globales de cambio de pestaña (1 - 7)
            if ord("1") <= ch <= ord("7"):
                nueva_tab = ch - ord("1")
                self.cambiar_tab(nueva_tab)
                continue

            # Atajos globales generales
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (ord("n"), ord("N")):
                self.accion_nuevo_movimiento()
                continue
            elif ch in (ord(":"),):
                self.modo_comando = True
                self.comando_texto = ""
                continue
            elif ch in (ord("/"),):
                self.modo_busqueda = True
                self.busqueda_texto = ""
                continue
            elif ch in (ord("?"),):
                self.abrir_modal(HelpModal(lambda: self.abrir_modal(None)))
                continue
            elif ch in (ord("u"), ord("U")):
                msg = self.core.db.deshacer_ultima_accion()
                if msg:
                    self.recargar_vista_actual()
                    self.notificar(f"Deshecho: {msg}")
                else:
                    self.notificar("No hay acciones previas para deshacer.")
                continue

            # Delegar tecla a la vista actual
            if hasattr(self.views[self.tab_activa], "handle_key"):
                self.views[self.tab_activa].handle_key(ch)


def iniciar_tui(core: FinanceCore):
    """Punto de entrada para ejecutar la TUI dentro de curses.wrapper."""
    app = TUIApp(core)
    try:
        curses.wrapper(app.main_loop)
    finally:
        # Restaurar terminal y desactivar eventos de ratón
        try:
            sys.stdout.write("\033[?1000l\033[?1002l\033[?1003l")
            sys.stdout.flush()
        except Exception:
            pass
