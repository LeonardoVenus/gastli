"""Widgets y componentes gráficos reutilizables para Curses."""
import curses
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from gastli.tui.theme import (
    BLOCK_CHARS,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_TL,
    BOX_TR,
    BOX_V,
    PROGRESS_EMPTY,
    PROGRESS_FULL,
    attr_border,
    attr_muted,
    attr_normal,
    attr_selected,
    attr_tab_active,
    attr_title,
)


def es_clic(bstate: int) -> bool:
    """Comprueba si el evento de ratón es un clic izquierdo válido."""
    mascara = (
        curses.BUTTON1_CLICKED
        | curses.BUTTON1_PRESSED
        | getattr(curses, "BUTTON1_RELEASED", 0)
        | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
    )
    return bool(bstate & mascara)


def es_doble_clic(bstate: int) -> bool:
    return bool(bstate & getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0))


def es_scroll_arriba(bstate: int) -> bool:
    mascara = getattr(curses, "BUTTON4_PRESSED", 0x10000) | getattr(curses, "BUTTON4_CLICKED", 0x20000)
    return bool(bstate & mascara)


def es_scroll_abajo(bstate: int) -> bool:
    mascara = getattr(curses, "BUTTON5_PRESSED", 0x200000) | getattr(curses, "BUTTON5_CLICKED", 0x400000)
    return bool(bstate & mascara)


def safe_addstr(win, y: int, x: int, text: str, attr: int = 0):
    """Escribe texto en pantalla sin generar excepciones por límites de pantalla."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    espacio = max_x - x
    if espacio <= 0:
        return
    # Truncar si excede el ancho disponible
    texto_seguro = text[:espacio]
    try:
        win.addstr(y, x, texto_seguro, attr)
    except curses.error:
        pass


def draw_box(
    win,
    y: int,
    x: int,
    h: int,
    w: int,
    title: str = "",
    color_attr: Optional[int] = None,
    title_attr: Optional[int] = None,
    clear_interior: bool = True,
):
    """Dibuja una caja con esquinas redondeadas y título opcional."""
    max_y, max_x = win.getmaxyx()
    if y >= max_y or x >= max_x or h <= 1 or w <= 1:
        return

    c_attr = color_attr if color_attr is not None else attr_border()
    t_attr = title_attr if title_attr is not None else attr_title()

    ancho_efectivo = min(w, max_x - x)
    alto_efectivo = min(h, max_y - y)
    if ancho_efectivo < 2 or alto_efectivo < 2:
        return

    # Línea superior
    top_line = BOX_TL + BOX_H * (ancho_efectivo - 2) + BOX_TR
    safe_addstr(win, y, x, top_line, c_attr)

    if title and ancho_efectivo > len(title) + 4:
        titulo_fmt = f" {title} "
        pos_x = x + 2
        safe_addstr(win, y, pos_x, titulo_fmt, t_attr)

    # Líneas intermedias con fondo limpio para que no transparenten elementos debajo
    interior_w = ancho_efectivo - 2
    espacios = " " * interior_w if (clear_interior and interior_w > 0) else None
    for row in range(y + 1, y + alto_efectivo - 1):
        safe_addstr(win, row, x, BOX_V, c_attr)
        if espacios is not None:
            safe_addstr(win, row, x + 1, espacios, attr_normal())
        safe_addstr(win, row, x + ancho_efectivo - 1, BOX_V, c_attr)

    # Línea inferior
    bot_line = BOX_BL + BOX_H * (ancho_efectivo - 2) + BOX_BR
    safe_addstr(win, y + alto_efectivo - 1, x, bot_line, c_attr)


def draw_progress_bar(pct: float, width: int = 15) -> str:
    """Genera una barra de progreso sobria [████░░░░░░] XX%."""
    pct_clamped = max(0.0, min(100.0, pct))
    inner_width = max(3, width - 2)
    llenos = int(round((pct_clamped / 100.0) * inner_width))
    vacios = inner_width - llenos
    barra = PROGRESS_FULL * llenos + PROGRESS_EMPTY * vacios
    return f"[{barra}] {pct_clamped:4.1f}%"


def draw_mini_bar_chart(
    values: List[Tuple[Any, int]], height: int = 5, max_value: Optional[int] = None
) -> List[str]:
    """Crea una gráfica de barras vertical usando bloques Unicode  ▂▃▄▅▆▇█."""
    if not values:
        return ["Sin datos"]
    nums = [v[1] for v in values]
    max_val = max_value or max(nums or [1])
    if max_val <= 0:
        max_val = 1

    lines = []
    # Generar de arriba hacia abajo
    for h in range(height, 0, -1):
        line = ""
        umbral_inferior = (h - 1) / height
        umbral_superior = h / height

        for _, val in values:
            proporcion = val / max_val
            if proporcion >= umbral_superior:
                line += "█"
            elif proporcion <= umbral_inferior:
                line += " "
            else:
                # Intermedio entre niveles
                frac = (proporcion - umbral_inferior) * height
                idx = min(len(BLOCK_CHARS) - 1, int(frac * len(BLOCK_CHARS)))
                line += BLOCK_CHARS[idx]
        lines.append(line)
    return lines


class TableWidget:
    """Tabla interactiva con scroll, selección de fila y soporte de ratón."""

    def __init__(
        self,
        headers: List[Tuple[str, int, str]],  # (Título, Ancho, Alineación 'L' o 'R')
        box_title: str = "",
    ):
        self.headers = headers
        self.box_title = box_title
        self.rows: List[List[Any]] = []
        self.row_attrs: List[int] = []  # atributos por fila
        self.selected_index: int = 0
        self.scroll_offset: int = 0
        self.y: int = 0
        self.x: int = 0
        self.h: int = 0
        self.w: int = 0

    def set_data(self, rows: List[List[Any]], row_attrs: Optional[List[int]] = None):
        self.rows = rows
        self.row_attrs = row_attrs or [0] * len(rows)
        if self.selected_index >= len(rows):
            self.selected_index = max(0, len(rows) - 1)
        self._ajustar_scroll()

    def _ajustar_scroll(self):
        altura_datos = max(1, self.h - 4)
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + altura_datos:
            self.scroll_offset = self.selected_index - altura_datos + 1

    def handle_key(self, ch: int) -> bool:
        if not self.rows:
            return False
        total = len(self.rows)
        altura_datos = max(1, self.h - 4)

        if ch in (curses.KEY_UP, ord("k")):
            self.selected_index = (self.selected_index - 1) % total
            self._ajustar_scroll()
            return True
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.selected_index = (self.selected_index + 1) % total
            self._ajustar_scroll()
            return True
        elif ch in (curses.KEY_PPAGE,):  # Page Up
            self.selected_index = max(0, self.selected_index - altura_datos)
            self._ajustar_scroll()
            return True
        elif ch in (curses.KEY_NPAGE,):  # Page Down
            self.selected_index = min(total - 1, self.selected_index + altura_datos)
            self._ajustar_scroll()
            return True
        elif ch in (curses.KEY_HOME,):
            self.selected_index = 0
            self._ajustar_scroll()
            return True
        elif ch in (curses.KEY_END,):
            self.selected_index = total - 1
            self._ajustar_scroll()
            return True
        return False

    def handle_mouse(self, my: int, mx: int, bstate: int) -> Tuple[bool, bool]:
        """Procesa evento de ratón. Devuelve (consumido, fue_doble_clic)."""
        if not (self.y <= my < self.y + self.h and self.x <= mx < self.x + self.w):
            return False, False

        # Rueda de desplazamiento
        if es_scroll_arriba(bstate):
            if self.rows:
                self.selected_index = max(0, self.selected_index - 1)
                self._ajustar_scroll()
                return True, False
        elif es_scroll_abajo(bstate):
            if self.rows:
                self.selected_index = min(len(self.rows) - 1, self.selected_index + 1)
                self._ajustar_scroll()
                return True, False

        # Sólo procesar si fue un clic real
        if not es_clic(bstate):
            return False, False

        # Clic dentro de la zona de datos
        fila_datos_y = my - (self.y + 2)
        if 0 <= fila_datos_y < max(1, self.h - 4):
            idx_clic = self.scroll_offset + fila_datos_y
            if 0 <= idx_clic < len(self.rows):
                self.selected_index = idx_clic
                doble = es_doble_clic(bstate)
                return True, doble

        return True, False

    def render(self, win, y: int, x: int, h: int, w: int, tiene_foco: bool = True):
        self.y, self.x, self.h, self.w = y, x, h, w
        if h < 4 or w < 10:
            return

        draw_box(win, y, x, h, w, title=self.box_title)

        # Encabezados
        header_y = y + 1
        pos_x = x + 2
        ancho_total_headers = w - 4

        header_str = ""
        for titulo, ancho, align in self.headers:
            if align == "R":
                col_text = f"{titulo:>{ancho}}"
            else:
                col_text = f"{titulo:<{ancho}}"
            header_str += col_text + " "
        safe_addstr(win, header_y, pos_x, header_str[:ancho_total_headers], attr_title())

        # Separador horizontal sutil
        sep = BOX_H * ancho_total_headers
        safe_addstr(win, header_y + 1, pos_x, sep, attr_muted())

        # Filas de datos
        altura_datos = h - 4
        if not self.rows:
            safe_addstr(win, y + 3, pos_x, "(No hay registros)", attr_muted())
            return

        for i in range(altura_datos):
            data_idx = self.scroll_offset + i
            if data_idx >= len(self.rows):
                break

            fila = self.rows[data_idx]
            fila_y = y + 3 + i
            es_seleccionada = data_idx == self.selected_index and tiene_foco

            # Construir texto de la fila respetando anchos
            row_str = ""
            for c_idx, val in enumerate(fila):
                if c_idx < len(self.headers):
                    _, ancho, align = self.headers[c_idx]
                    s_val = str(val if val is not None else "")
                    if align == "R":
                        col_text = f"{s_val:>{ancho}}"
                    else:
                        col_text = f"{s_val:<{ancho}}"
                    row_str += col_text + " "

            attr_fila = self.row_attrs[data_idx] if data_idx < len(self.row_attrs) else 0
            if es_seleccionada:
                # Resaltado de fila seleccionada
                espacio_fila = " " * (ancho_total_headers - len(row_str[:ancho_total_headers]))
                safe_addstr(
                    win, fila_y, pos_x, row_str[:ancho_total_headers] + espacio_fila, attr_selected()
                )
            else:
                safe_addstr(win, fila_y, pos_x, row_str[:ancho_total_headers], attr_fila or attr_normal())

        # Indicador de scroll si hay más registros
        if len(self.rows) > altura_datos:
            pct = int((self.selected_index + 1) / len(self.rows) * 100)
            ind = f" {self.selected_index + 1}/{len(self.rows)} ({pct}%) "
            safe_addstr(win, y + h - 1, x + w - len(ind) - 3, ind, attr_muted())


class FormModal:
    """Ventana modal interactiva para formularios con captura de teclado y ratón."""

    def __init__(
        self,
        titulo: str,
        campos: List[Dict[str, Any]],
        on_guardar: Callable[[Dict[str, Any]], None],
        on_cancelar: Callable[[], None],
        ancho: int = 60,
    ):
        self.titulo = titulo
        self.campos = campos  # list of dicts: key, label, type, value, options
        self.on_guardar = on_guardar
        self.on_cancelar = on_cancelar
        self.ancho = ancho
        self.foco_idx = 0  # 0..len(campos)-1 son campos; luego botones Guardar y Cancelar
        self.cursor_pos = 0
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    @property
    def total_elementos(self) -> int:
        return len(self.campos) + 2  # campos + botón Guardar + botón Cancelar

    def handle_key(self, ch: int) -> bool:
        idx_guardar = len(self.campos)
        idx_cancelar = len(self.campos) + 1

        if ch in (27,):  # ESC
            self.on_cancelar()
            return True

        if ch in (ord("\t"), curses.KEY_DOWN):  # Tab o Abajo
            self.foco_idx = (self.foco_idx + 1) % self.total_elementos
            return True
        elif ch in (curses.KEY_BTAB, curses.KEY_UP):  # Shift-Tab o Arriba
            self.foco_idx = (self.foco_idx - 1) % self.total_elementos
            return True

        # Enter
        if ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            if self.foco_idx == idx_cancelar:
                self.on_cancelar()
                return True
            else:
                # Guardar
                valores = {c["key"]: c["value"] for c in self.campos}
                self.on_guardar(valores)
                return True

        # Si el foco está en un campo
        if self.foco_idx < len(self.campos):
            campo = self.campos[self.foco_idx]
            c_type = campo.get("type", "text")

            if c_type == "choice":
                opts = campo.get("options", [])
                if opts:
                    curr_val = campo.get("value", 0)
                    if isinstance(curr_val, int):
                        idx = curr_val
                    else:
                        idx = opts.index(curr_val) if curr_val in opts else 0

                    if ch in (curses.KEY_LEFT, ord("h")):
                        idx = (idx - 1) % len(opts)
                        campo["value"] = idx
                        return True
                    elif ch in (curses.KEY_RIGHT, ord("l"), ord(" ")):
                        idx = (idx + 1) % len(opts)
                        campo["value"] = idx
                        return True

            elif c_type == "date":
                # Soporte rápido de +/- para mover días
                curr_date_str = str(campo.get("value", date.today().strftime("%Y-%m-%d")))
                try:
                    curr_d = datetime.strptime(curr_date_str, "%Y-%m-%d").date()
                except ValueError:
                    curr_d = date.today()

                if ch in (ord("+"), ord("=")):
                    nueva_d = curr_d + timedelta(days=1)
                    campo["value"] = nueva_d.strftime("%Y-%m-%d")
                    return True
                elif ch in (ord("-"), ord("_")):
                    nueva_d = curr_d - timedelta(days=1)
                    campo["value"] = nueva_d.strftime("%Y-%m-%d")
                    return True
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    val_str = str(campo.get("value", ""))
                    campo["value"] = val_str[:-1]
                    return True
                elif 32 <= ch <= 126:
                    val_str = str(campo.get("value", ""))
                    if len(val_str) < 10:
                        campo["value"] = val_str + chr(ch)
                    return True

            elif c_type in ("text", "number"):
                val_str = str(campo.get("value", ""))
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    campo["value"] = val_str[:-1]
                    return True
                elif 32 <= ch <= 126:
                    caracter = chr(ch)
                    if c_type == "number" and caracter not in "0123456789.,-":
                        return True
                    campo["value"] = val_str + caracter
                    return True

        return False

    def handle_mouse(self, my: int, mx: int, bstate: int, *args) -> bool:
        box_y = self.y if self.h > 0 else (args[0] if len(args) > 0 else 0)
        box_x = self.x if self.w > 0 else (args[1] if len(args) > 1 else 0)
        box_h = self.h if self.h > 0 else (args[2] if len(args) > 2 else 0)
        box_w = self.w if self.w > 0 else (args[3] if len(args) > 3 else 0)

        if not (box_y <= my < box_y + box_h and box_x <= mx < box_x + box_w):
            return False

        # Si no hubo clic, ignorar (evitar disparos al pasar el mouse por encima)
        if not es_clic(bstate):
            return False

        # Verificar si hizo clic en un campo
        start_y = box_y + 2
        for idx, campo in enumerate(self.campos):
            row_y = start_y + idx * 2
            if my == row_y:
                self.foco_idx = idx
                # Si es un campo choice y se hace clic en él, ciclar opción
                if campo.get("type") == "choice":
                    opts = campo.get("options", [])
                    if opts:
                        curr = campo.get("value", 0)
                        if isinstance(curr, int):
                            campo["value"] = (curr + 1) % len(opts)
                return True

        # Verificar clic en botones
        bot_y = box_y + box_h - 2
        if my == bot_y:
            # Botón Guardar vs Cancelar
            btn_guardar_x = box_x + 4
            btn_cancelar_x = box_x + 20
            if btn_guardar_x <= mx <= btn_guardar_x + 14:
                valores = {c["key"]: c["value"] for c in self.campos}
                self.on_guardar(valores)
                return True
            elif btn_cancelar_x <= mx <= btn_cancelar_x + 14:
                self.on_cancelar()
                return True

        return True

    def render(self, win):
        max_y, max_x = win.getmaxyx()
        alto = len(self.campos) * 2 + 5
        ancho = min(self.ancho, max_x - 4)
        y = max(1, (max_y - alto) // 2)
        x = max(2, (max_x - ancho) // 2)
        self.y, self.x, self.h, self.w = y, x, alto, ancho

        # Fondo y caja
        draw_box(win, y, x, alto, ancho, title=self.titulo)

        start_y = y + 2
        for idx, campo in enumerate(self.campos):
            row_y = start_y + idx * 2
            label = campo.get("label", "")
            safe_addstr(win, row_y, x + 3, f"{label:<20}", attr_muted())

            val = campo.get("value", "")
            es_foco = idx == self.foco_idx

            c_type = campo.get("type", "text")
            val_x = x + 24
            campo_ancho = ancho - 28

            if c_type == "choice":
                opts = campo.get("options", [])
                curr_idx = val if isinstance(val, int) else (opts.index(val) if val in opts else 0)
                curr_txt = opts[curr_idx] if 0 <= curr_idx < len(opts) else ""
                disp_txt = f"< {curr_txt} >"
            elif c_type == "date":
                disp_txt = f"{val}  (+/- días)"
            else:
                disp_txt = str(val)

            c_attr = attr_selected() if es_foco else attr_normal()
            # Rellenar con espacio para que se vea como input
            pad_txt = f" {disp_txt:<{campo_ancho}} "
            safe_addstr(win, row_y, val_x, pad_txt[:campo_ancho], c_attr)

        # Botones
        bot_y = y + alto - 2
        idx_guardar = len(self.campos)
        idx_cancelar = len(self.campos) + 1

        attr_g = attr_selected() if self.foco_idx == idx_guardar else attr_tab_active()
        attr_c = attr_selected() if self.foco_idx == idx_cancelar else attr_muted()

        safe_addstr(win, bot_y, x + 4, "[ Guardar ]", attr_g)
        safe_addstr(win, bot_y, x + 20, "[ Cancelar ]", attr_c)
        safe_addstr(win, bot_y, x + 36, "Tab: mover | Esc: salir", attr_muted())


class ConfirmModal:
    """Diálogo modal para confirmar acciones destructivas (ej. borrar)."""

    def __init__(
        self,
        titulo: str,
        mensaje: str,
        on_confirmar: Callable[[], None],
        on_cancelar: Callable[[], None],
    ):
        self.titulo = titulo
        self.mensaje = mensaje
        self.on_confirmar = on_confirmar
        self.on_cancelar = on_cancelar
        self.opcion_si = True
        self.y = 0
        self.x = 0
        self.h = 0
        self.w = 0

    def handle_key(self, ch: int) -> bool:
        if ch in (27,):  # ESC
            self.on_cancelar()
            return True
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("\t")):
            self.opcion_si = not self.opcion_si
            return True
        elif ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            if self.opcion_si:
                self.on_confirmar()
            else:
                self.on_cancelar()
            return True
        return False

    def render(self, win):
        max_y, max_x = win.getmaxyx()
        h, w = 8, min(56, max_x - 4)
        y = max(1, (max_y - h) // 2)
        x = max(2, (max_x - w) // 2)
        self.y, self.x, self.h, self.w = y, x, h, w

        draw_box(win, y, x, h, w, title=self.titulo)
        safe_addstr(win, y + 2, x + 4, self.mensaje[: w - 8], attr_title())

        attr_si = attr_selected() if self.opcion_si else attr_muted()
        attr_no = attr_selected() if not self.opcion_si else attr_muted()

        safe_addstr(win, y + 5, x + 8, "[ Sí, confirmar ]", attr_si)
        safe_addstr(win, y + 5, x + 30, "[ Cancelar ]", attr_no)

    def handle_mouse(self, my: int, mx: int, bstate: int, *args) -> bool:
        if not es_clic(bstate):
            return False
        btn_y = self.y + 5
        if my == btn_y:
            if self.x + 8 <= mx <= self.x + 28:
                self.on_confirmar()
                return True
            elif self.x + 30 <= mx <= self.x + 46:
                self.on_cancelar()
                return True
        self.on_cancelar()
        return True


class HelpModal:
    """Ventana modal con ayuda contextual estructurada de atajos y comandos."""

    def __init__(self, on_cerrar: Callable[[], None]):
        self.on_cerrar = on_cerrar

    def handle_key(self, ch: int) -> bool:
        self.on_cerrar()
        return True

    def handle_mouse(self, my: int, mx: int, bstate: int, *args) -> bool:
        if es_clic(bstate):
            self.on_cerrar()
            return True
        return False

    def render(self, win):
        max_y, max_x = win.getmaxyx()
        h = min(22, max_y - 2)
        w = min(74, max_x - 4)
        y = max(1, (max_y - h) // 2)
        x = max(2, (max_x - w) // 2)

        draw_box(win, y, x, h, w, title="Ayuda y Comandos del Sistema")

        lineas = [
            ("── NAVEGACIÓN Y OPERACIONES ──────────────────────────", True),
            ("1 - 7        Cambiar entre pestañas (Resumen, Movs, Cuentas, Deudas...)", False),
            ("n            Registrar nuevo movimiento (gasto, ingreso, trans, pago)", False),
            ("e / Enter    Editar / modificar movimiento, cuenta o pasivo seleccionado", False),
            ("d            Eliminar movimiento, cuenta o pasivo con confirmación", False),
            ("u            Deshacer última acción  |  /  Buscar movimientos por texto", False),
            ("Tab / Flechas Navegar tablas / campos |  q / Esc  Cerrar ventana / Salir", False),
            ("", False),
            ("── GESTIÓN DE CUENTAS Y DEUDAS (Pestañas 3 y 4) ──────", True),
            ("c            Crear nueva cuenta bancaria, tarjeta o préstamo", False),
            ("p            Registrar pago a tarjeta de crédito o deuda (Pestaña 4)", False),
            ("i / t        Depositar saldo / Transferir entre activos (Pestaña 3)", False),
            ("a / x        Ajustar saldo real / Archivar cuenta (Pestaña 3)", False),
            ("", False),
            ("── LÍNEA DE COMANDOS (Presiona ':' en cualquier momento) ─", True),
            (":g [monto] [concepto]    Registrar gasto rápido (ej: :g 45 tacos)", False),
            (":t [monto] [orig] [dest] Transferir entre cuentas (ej: :t 200 BBVA Cartera)", False),
            (":p [monto] [dest] [orig] Pagar tarjeta o deuda (ej: :p 1000 Nu BBVA)", False),
            (":export | :backup | :q   Exportar a Excel (.xlsx) | Respaldo BD | Salir", False),
        ]

        cur_y = y + 1
        for texto, es_titulo in lineas:
            if cur_y >= y + h - 2:
                break
            if texto:
                attr = attr_title() if es_titulo else attr_normal()
                safe_addstr(win, cur_y, x + 3, texto, attr)
            cur_y += 1

        safe_addstr(win, y + h - 2, x + max(2, (w - 38) // 2), "Presiona cualquier tecla para cerrar", attr_muted())
