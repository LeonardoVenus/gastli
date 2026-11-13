"""Modelos de datos para el sistema de finanzas personales."""
from dataclasses import dataclass, field
from typing import Optional


class TipoCuenta:
    DEBITO = "debito"
    EFECTIVO = "efectivo"
    CREDITO = "credito"
    DEUDA = "deuda"

    ACTIVOS = (DEBITO, EFECTIVO)
    PASIVOS = (CREDITO, DEUDA)
    TODOS = (DEBITO, EFECTIVO, CREDITO, DEUDA)


class TipoMovimiento:
    GASTO = "gasto"
    INGRESO = "ingreso"
    TRANSFERENCIA = "transferencia"
    PAGO = "pago"
    AJUSTE = "ajuste"

    TODOS = (GASTO, INGRESO, TRANSFERENCIA, PAGO, AJUSTE)


@dataclass
class Cuenta:
    id: Optional[int]
    nombre: str
    tipo: str  # debito, efectivo, credito, deuda
    saldo_inicial_centavos: int = 0
    cuenta_pago_id: Optional[int] = None  # Para tarjetas o deudas: débito por defecto
    archivada: bool = False
    created_at: str = ""

    @property
    def es_activo(self) -> bool:
        return self.tipo in TipoCuenta.ACTIVOS

    @property
    def es_pasivo(self) -> bool:
        return self.tipo in TipoCuenta.PASIVOS


@dataclass
class TarjetaCredito:
    cuenta_id: int
    limite_centavos: int
    dia_corte: int
    dia_limite_pago: int
    pago_minimo_centavos: int = 0


@dataclass
class Deuda:
    cuenta_id: int
    monto_original_centavos: int
    cuota_centavos: int
    dia_pago: int
    fecha_inicio: str = ""


@dataclass
class Categoria:
    id: Optional[int]
    nombre: str
    es_hormiga: bool = False
    activo: bool = True


@dataclass
class Movimiento:
    id: Optional[int]
    fecha: str  # YYYY-MM-DD
    tipo: str  # gasto, ingreso, transferencia, pago, ajuste
    monto_centavos: int
    cuenta_origen_id: Optional[int] = None
    cuenta_destino_id: Optional[int] = None
    categoria_id: Optional[int] = None
    nota: str = ""
    created_at: str = ""

    # Campos enriquecidos para visualización
    cuenta_origen_nombre: str = ""
    cuenta_destino_nombre: str = ""
    categoria_nombre: str = ""


@dataclass
class Configuracion:
    moneda: str = "$"
    horizonte_dias: int = 15
    monto_efectivo_diario_centavos: int = 20000  # $200.00
    umbral_hormiga_centavos: int = 10000  # $100.00
    backups_rotacion: int = 5


def centavos_a_str(centavos: int, simbolo: str = "$", con_signo: bool = False) -> str:
    """Convierte centavos enteros a cadena formateada con separador de miles y 2 decimales."""
    negativo = centavos < 0
    centavos_abs = abs(centavos)
    enteros = centavos_abs // 100
    decimales = centavos_abs % 100
    formateado = f"{enteros:,}.{decimales:02d}"

    if con_signo:
        if negativo:
            return f"- {simbolo} {formateado}"
        elif centavos > 0:
            return f"+ {simbolo} {formateado}"
        else:
            return f"  {simbolo} {formateado}"
    else:
        if negativo:
            return f"-{simbolo} {formateado}"
        return f"{simbolo} {formateado}"


def parse_monto_a_centavos(texto: str) -> int:
    """Convierte un texto (ej. '45', '45.50', '$ 1,200.50') a centavos enteros."""
    limpio = texto.replace("$", "").replace(",", "").replace(" ", "").strip()
    if not limpio:
        return 0
    try:
        val = float(limpio)
        return int(round(val * 100))
    except ValueError:
        raise ValueError(f"Monto inválido: {texto}")
