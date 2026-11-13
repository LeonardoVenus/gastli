"""Tema, paleta sobria de colores y caracteres de renderizado para Curses."""
import curses

# Caracteres de caja redondeada
BOX_TL = "╭"
BOX_TR = "╮"
BOX_BL = "╰"
BOX_BR = "╯"
BOX_H = "─"
BOX_V = "│"
BOX_T_DOWN = "┬"
BOX_T_UP = "┴"
BOX_T_RIGHT = "├"
BOX_T_LEFT = "┤"
BOX_CROSS = "┼"

# Caracteres para gráficas y barras
PROGRESS_FULL = "█"
PROGRESS_EMPTY = "░"
BLOCK_CHARS = " ▂▃▄▅▆▇█"

# Identificadores de pares de color
PAIR_NORMAL = 1
PAIR_TOPBAR = 2
PAIR_TAB_ACTIVE = 3
PAIR_BORDER = 4
PAIR_POSITIVE = 5
PAIR_NEGATIVE = 6
PAIR_WARNING = 7
PAIR_MUTED = 8
PAIR_SELECTED = 9
PAIR_BUTTON = 10
PAIR_BUTTON_FOCUS = 11
PAIR_TITLE = 12


def inicializar_colores():
    """Configura la paleta de colores de curses con degradado sobrio."""
    if not curses.has_colors():
        return

    curses.start_color()
    curses.use_default_colors()

    # Intentar definir pares
    try:
        curses.init_pair(PAIR_NORMAL, curses.COLOR_WHITE, -1)
        curses.init_pair(PAIR_TOPBAR, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(PAIR_TAB_ACTIVE, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(PAIR_BORDER, curses.COLOR_CYAN, -1)
        curses.init_pair(PAIR_POSITIVE, curses.COLOR_GREEN, -1)
        curses.init_pair(PAIR_NEGATIVE, curses.COLOR_RED, -1)
        curses.init_pair(PAIR_WARNING, curses.COLOR_YELLOW, -1)
        curses.init_pair(PAIR_MUTED, curses.COLOR_WHITE, -1)  # se combina con A_DIM
        curses.init_pair(PAIR_SELECTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(PAIR_BUTTON, curses.COLOR_CYAN, -1)
        curses.init_pair(PAIR_BUTTON_FOCUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(PAIR_TITLE, curses.COLOR_WHITE, -1)
    except Exception:
        pass


def _has_colors_safe() -> bool:
    try:
        return curses.has_colors()
    except Exception:
        return False


def attr_normal() -> int:
    return curses.color_pair(PAIR_NORMAL) if _has_colors_safe() else 0


def attr_topbar() -> int:
    return curses.color_pair(PAIR_TOPBAR) if _has_colors_safe() else curses.A_REVERSE


def attr_tab_active() -> int:
    return (
        curses.color_pair(PAIR_TAB_ACTIVE) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_REVERSE | curses.A_BOLD
    )


def attr_border() -> int:
    return curses.color_pair(PAIR_BORDER) if _has_colors_safe() else 0


def attr_positive() -> int:
    return (
        curses.color_pair(PAIR_POSITIVE) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_BOLD
    )


def attr_negative() -> int:
    return (
        curses.color_pair(PAIR_NEGATIVE) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_BOLD
    )


def attr_warning() -> int:
    return (
        curses.color_pair(PAIR_WARNING) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_BOLD
    )


def attr_muted() -> int:
    return (
        curses.color_pair(PAIR_MUTED) | curses.A_DIM
        if _has_colors_safe()
        else curses.A_DIM
    )


def attr_selected() -> int:
    return (
        curses.color_pair(PAIR_SELECTED) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_REVERSE
    )


def attr_title() -> int:
    return (
        curses.color_pair(PAIR_TITLE) | curses.A_BOLD
        if _has_colors_safe()
        else curses.A_BOLD
    )

