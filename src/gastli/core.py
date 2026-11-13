"""Lógica de negocio, cálculos financieros y métricas."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from gastli.db import Database
from gastli.models import (
    Categoria,
    Configuracion,
    Cuenta,
    Deuda,
    Movimiento,
    TarjetaCredito,
    TipoCuenta,
    TipoMovimiento,
    centavos_a_str,
)


@dataclass
class ResumenActivosPasivos:
    saldo_debito: int = 0
    saldo_efectivo: int = 0
    total_activos: int = 0
    deuda_tarjetas: int = 0
    deuda_prestamos: int = 0
    total_pasivos: int = 0
    patrimonio_neto: int = 0


@dataclass
class DetalleTarjeta:
    cuenta: Cuenta
    tarjeta: TarjetaCredito
    saldo_actual: int
    credito_disponible: int
    porcentaje_uso: float
    proximo_corte: date
    dias_al_corte: int
    fecha_limite_pago: date
    dias_al_pago: int
    pago_para_no_intereses: int
    cuenta_pago_nombre: str


@dataclass
class DetalleDeuda:
    cuenta: Cuenta
    deuda: Deuda
    saldo_restante: int
    cuota_centavos: int
    proximo_pago: date
    dias_al_pago: int
    cuenta_pago_nombre: str


@dataclass
class CompromisoPago:
    descripcion: str
    cuenta_pago_id: int
    cuenta_pago_nombre: str
    monto_centavos: int
    fecha_vencimiento: date
    dias_restantes: int
    tipo: str  # 'tarjeta' o 'deuda'


@dataclass
class ReportePorDepositar:
    horizonte_dias: int
    compromisos: List[CompromisoPago]
    compromisos_por_cuenta: Dict[int, Dict[str, Any]]
    total_compromisos: int
    total_falta_depositar: int


@dataclass
class MetricasEfectivo:
    cuenta_id: int
    cuenta_nombre: str
    llevo_hoy: int
    gasto_hoy: int
    sobra_actual: int
    promedio_7_dias: int
    gastos_hoy_detalle: List[Movimiento]


@dataclass
class MetricasHormiga:
    mes_str: str
    total_hormiga_centavos: int
    total_gastos_centavos: int
    porcentaje_hormiga: float
    proyeccion_anual_centavos: int
    top_conceptos: List[Tuple[str, int]]  # (nombre_concepto_o_categoria, centavos)
    barras_diarias: List[Tuple[int, int]]  # (dia_del_mes, centavos)
    max_dia_centavos: int


class FinanceCore:
    def __init__(self, db: Database):
        self.db = db

    # ============================================================== #
    #                     CÁLCULO DINÁMICO DE SALDOS                #
    # ============================================================== #

    def calcular_saldo_cuenta(self, cuenta_id: int) -> int:
        """Calcula el saldo dinámico de una cuenta a partir de todos los movimientos."""
        cuenta = self.db.get_cuenta(cuenta_id)
        if not cuenta:
            return 0

        cur = self.db.get_cursor()

        if cuenta.es_activo:
            # Dinero que entra: ingresos, transferencias entrantes, ajustes entrantes
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_destino_id = ?
                     AND tipo IN (?, ?, ?)""",
                (
                    cuenta_id,
                    TipoMovimiento.INGRESO,
                    TipoMovimiento.TRANSFERENCIA,
                    TipoMovimiento.AJUSTE,
                ),
            )
            entradas = cur.fetchone()[0]

            # Dinero que sale: gastos, transferencias salientes, pagos hechos, ajustes salientes
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_origen_id = ?
                     AND tipo IN (?, ?, ?, ?)""",
                (
                    cuenta_id,
                    TipoMovimiento.GASTO,
                    TipoMovimiento.TRANSFERENCIA,
                    TipoMovimiento.PAGO,
                    TipoMovimiento.AJUSTE,
                ),
            )
            salidas = cur.fetchone()[0]
            return entradas - salidas

        elif cuenta.tipo == TipoCuenta.CREDITO:
            # Pasivo: cargos (gastos con la tarjeta) + ajustes salientes
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_origen_id = ?
                     AND tipo IN (?, ?)""",
                (cuenta_id, TipoMovimiento.GASTO, TipoMovimiento.AJUSTE),
            )
            cargos = cur.fetchone()[0]

            # Abonos / pagos a la tarjeta + ajustes entrantes
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_destino_id = ?
                     AND tipo IN (?, ?)""",
                (cuenta_id, TipoMovimiento.PAGO, TipoMovimiento.AJUSTE),
            )
            abonos = cur.fetchone()[0]
            return cargos - abonos

        elif cuenta.tipo == TipoCuenta.DEUDA:
            deuda_info = self.db.get_deuda(cuenta_id)
            monto_original = deuda_info.monto_original_centavos if deuda_info else 0

            # Abonos a la deuda + ajustes entrantes
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_destino_id = ?
                     AND tipo IN (?, ?)""",
                (cuenta_id, TipoMovimiento.PAGO, TipoMovimiento.AJUSTE),
            )
            abonos = cur.fetchone()[0]

            # Ajustes que aumentan la deuda
            cur.execute(
                """SELECT COALESCE(SUM(monto_centavos), 0)
                   FROM movimientos
                   WHERE cuenta_origen_id = ? AND tipo = ?""",
                (cuenta_id, TipoMovimiento.AJUSTE),
            )
            aumentos = cur.fetchone()[0]

            restante = monto_original + aumentos - abonos
            return max(0, restante)

        return 0

    def calcular_total_depositado(self, cuenta_id: int) -> int:
        """Calcula el total de ingresos y aportaciones que han entrado a la cuenta."""
        cur = self.db.get_cursor()
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_destino_id = ?
                 AND tipo IN (?, ?)""",
            (cuenta_id, TipoMovimiento.INGRESO, TipoMovimiento.AJUSTE),
        )
        return cur.fetchone()[0]

    def obtener_resumen_global(self) -> ResumenActivosPasivos:
        resumen = ResumenActivosPasivos()
        cuentas = self.db.get_cuentas(incluir_archivadas=False)
        for c in cuentas:
            saldo = self.calcular_saldo_cuenta(c.id)
            if c.tipo == TipoCuenta.DEBITO:
                resumen.saldo_debito += saldo
            elif c.tipo == TipoCuenta.EFECTIVO:
                resumen.saldo_efectivo += saldo
            elif c.tipo == TipoCuenta.CREDITO:
                resumen.deuda_tarjetas += saldo
            elif c.tipo == TipoCuenta.DEUDA:
                resumen.deuda_prestamos += saldo

        resumen.total_activos = resumen.saldo_debito + resumen.saldo_efectivo
        resumen.total_pasivos = resumen.deuda_tarjetas + resumen.deuda_prestamos
        resumen.patrimonio_neto = resumen.total_activos - resumen.total_pasivos
        return resumen

    def calcular_gasto_mes(self, anio: Optional[int] = None, mes: Optional[int] = None) -> int:
        """Calcula el total de gastos realizados en el mes."""
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        primer_dia = f"{anio:04d}-{mes:02d}-01"
        ultimo_dia_num = calendar.monthrange(anio, mes)[1]
        ultimo_dia = f"{anio:04d}-{mes:02d}-{ultimo_dia_num:02d}"

        cur = self.db.get_cursor()
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE tipo = ?
                 AND fecha >= ? AND fecha <= ?""",
            (TipoMovimiento.GASTO, primer_dia, ultimo_dia),
        )
        return cur.fetchone()[0]

    # ============================================================== #
    #                     TARJETAS Y DEUDAS                          #
    # ============================================================== #

    def obtener_detalles_tarjetas(self, fecha_ref: Optional[date] = None) -> List[DetalleTarjeta]:
        hoy = fecha_ref or date.today()
        cuentas = self.db.get_cuentas(incluir_archivadas=False)
        tarjetas = []

        for c in cuentas:
            if c.tipo != TipoCuenta.CREDITO:
                continue
            tc = self.db.get_tarjeta(c.id)
            if not tc:
                continue

            saldo_actual = self.calcular_saldo_cuenta(c.id)
            disponible = max(0, tc.limite_centavos - saldo_actual)
            pct = (saldo_actual / tc.limite_centavos * 100.0) if tc.limite_centavos > 0 else 0.0

            # Cálculo de fechas de corte y pago
            proximo_corte, ultimo_corte = self._calcular_fechas_corte(hoy, tc.dia_corte)
            fecha_limite = self._calcular_fecha_pago(ultimo_corte, tc.dia_limite_pago)

            # Si la fecha límite calculada del último corte ya pasó, calcular la del próximo corte
            if fecha_limite < hoy:
                fecha_limite = self._calcular_fecha_pago(proximo_corte, tc.dia_limite_pago)

            dias_al_corte = (proximo_corte - hoy).days
            dias_al_pago = (fecha_limite - hoy).days

            # Pago para no generar intereses = saldo al último corte - pagos posteriores
            pago_no_int = self._calcular_pago_para_no_generar_intereses(c.id, ultimo_corte, hoy)

            cuenta_pago_nombre = "Sin asignar"
            if c.cuenta_pago_id:
                cta_p = self.db.get_cuenta(c.cuenta_pago_id)
                if cta_p:
                    cuenta_pago_nombre = cta_p.nombre

            tarjetas.append(
                DetalleTarjeta(
                    cuenta=c,
                    tarjeta=tc,
                    saldo_actual=saldo_actual,
                    credito_disponible=disponible,
                    porcentaje_uso=pct,
                    proximo_corte=proximo_corte,
                    dias_al_corte=dias_al_corte,
                    fecha_limite_pago=fecha_limite,
                    dias_al_pago=dias_al_pago,
                    pago_para_no_intereses=pago_no_int,
                    cuenta_pago_nombre=cuenta_pago_nombre,
                )
            )

        return tarjetas

    def _calcular_fechas_corte(self, hoy: date, dia_corte: int) -> Tuple[date, date]:
        """Devuelve (proximo_corte, ultimo_corte)."""
        # Limitar día al número de días del mes
        max_dias_mes_actual = calendar.monthrange(hoy.year, hoy.month)[1]
        dia_efectivo = min(dia_corte, max_dias_mes_actual)
        corte_este_mes = date(hoy.year, hoy.month, dia_efectivo)

        if hoy <= corte_este_mes:
            proximo_corte = corte_este_mes
            # Último corte fue el mes anterior
            mes_ant = hoy.month - 1 or 12
            anio_ant = hoy.year if hoy.month > 1 else hoy.year - 1
            max_dias_ant = calendar.monthrange(anio_ant, mes_ant)[1]
            ultimo_corte = date(anio_ant, mes_ant, min(dia_corte, max_dias_ant))
        else:
            # Próximo corte es el mes siguiente
            ultimo_corte = corte_este_mes
            mes_sig = (hoy.month % 12) + 1
            anio_sig = hoy.year if hoy.month < 12 else hoy.year + 1
            max_dias_sig = calendar.monthrange(anio_sig, mes_sig)[1]
            proximo_corte = date(anio_sig, mes_sig, min(dia_corte, max_dias_sig))

        return proximo_corte, ultimo_corte

    def _calcular_fecha_pago(self, corte: date, dia_pago: int) -> date:
        """Calcula la fecha de vencimiento de pago ligada a una fecha de corte."""
        # En la convención bancaria, si dia_pago <= dia_corte, vence en el mes siguiente.
        if dia_pago <= corte.day:
            mes = (corte.month % 12) + 1
            anio = corte.year if corte.month < 12 else corte.year + 1
        else:
            mes = corte.month
            anio = corte.year
        max_d = calendar.monthrange(anio, mes)[1]
        return date(anio, mes, min(dia_pago, max_d))

    def _calcular_pago_para_no_generar_intereses(
        self, cuenta_id: int, ultimo_corte: date, hoy: date
    ) -> int:
        """Saldo acumulado al día del último corte menos abonos/pagos realizados después."""
        cur = self.db.get_cursor()
        corte_str = ultimo_corte.strftime("%Y-%m-%d")
        hoy_str = hoy.strftime("%Y-%m-%d")

        # Cargos hasta el corte
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_origen_id = ?
                 AND tipo IN (?, ?)
                 AND fecha <= ?""",
            (cuenta_id, TipoMovimiento.GASTO, TipoMovimiento.AJUSTE, corte_str),
        )
        cargos_corte = cur.fetchone()[0]

        # Pagos hasta el corte
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_destino_id = ?
                 AND tipo IN (?, ?)
                 AND fecha <= ?""",
            (cuenta_id, TipoMovimiento.PAGO, TipoMovimiento.AJUSTE, corte_str),
        )
        pagos_corte = cur.fetchone()[0]
        saldo_al_corte = cargos_corte - pagos_corte

        # Pagos realizados DESPUÉS del corte y hasta hoy
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_destino_id = ?
                 AND tipo = ?
                 AND fecha > ? AND fecha <= ?""",
            (cuenta_id, TipoMovimiento.PAGO, corte_str, hoy_str),
        )
        pagos_posteriores = cur.fetchone()[0]

        restante = saldo_al_corte - pagos_posteriores
        return max(0, restante)

    def obtener_detalles_deudas(self, fecha_ref: Optional[date] = None) -> List[DetalleDeuda]:
        hoy = fecha_ref or date.today()
        cuentas = self.db.get_cuentas(incluir_archivadas=False)
        detalles = []

        for c in cuentas:
            if c.tipo != TipoCuenta.DEUDA:
                continue
            deuda = self.db.get_deuda(c.id)
            if not deuda:
                continue

            saldo_restante = self.calcular_saldo_cuenta(c.id)
            if saldo_restante <= 0:
                continue  # Deuda saldada

            # Próxima fecha de cuota
            max_dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
            dia_efectivo = min(deuda.dia_pago, max_dias_mes)
            pago_este_mes = date(hoy.year, hoy.month, dia_efectivo)

            if hoy <= pago_este_mes:
                proximo_pago = pago_este_mes
            else:
                mes_sig = (hoy.month % 12) + 1
                anio_sig = hoy.year if hoy.month < 12 else hoy.year + 1
                max_dias_sig = calendar.monthrange(anio_sig, mes_sig)[1]
                proximo_pago = date(anio_sig, mes_sig, min(deuda.dia_pago, max_dias_sig))

            dias_al_pago = (proximo_pago - hoy).days
            cuenta_pago_nombre = "Sin asignar"
            if c.cuenta_pago_id:
                cta_p = self.db.get_cuenta(c.cuenta_pago_id)
                if cta_p:
                    cuenta_pago_nombre = cta_p.nombre

            detalles.append(
                DetalleDeuda(
                    cuenta=c,
                    deuda=deuda,
                    saldo_restante=saldo_restante,
                    cuota_centavos=min(deuda.cuota_centavos, saldo_restante),
                    proximo_pago=proximo_pago,
                    dias_al_pago=dias_al_pago,
                    cuenta_pago_nombre=cuenta_pago_nombre,
                )
            )

        return detalles

    # ============================================================== #
    #                   WIDGET "POR DEPOSITAR"                       #
    # ============================================================== #

    def calcular_por_depositar(
        self, horizonte_dias: int = 15, fecha_ref: Optional[date] = None
    ) -> ReportePorDepositar:
        """Calcula los compromisos dentro del horizonte y cuánto falta depositar por cuenta."""
        hoy = fecha_ref or date.today()
        limite_horizonte = hoy + timedelta(days=horizonte_dias)

        compromisos: List[CompromisoPago] = []

        # 1. Compromisos de tarjetas de crédito
        detalles_tarjetas = self.obtener_detalles_tarjetas(hoy)
        for dt in detalles_tarjetas:
            if hoy <= dt.fecha_limite_pago <= limite_horizonte:
                monto = dt.pago_para_no_intereses
                if monto <= 0 and dt.saldo_actual > 0:
                    monto = dt.saldo_actual
                if monto > 0 and dt.cuenta.cuenta_pago_id:
                    compromisos.append(
                        CompromisoPago(
                            descripcion=f"{dt.cuenta.nombre}, pago {dt.fecha_limite_pago.strftime('%d-%b')}",
                            cuenta_pago_id=dt.cuenta.cuenta_pago_id,
                            cuenta_pago_nombre=dt.cuenta_pago_nombre,
                            monto_centavos=monto,
                            fecha_vencimiento=dt.fecha_limite_pago,
                            dias_restantes=dt.dias_al_pago,
                            tipo="tarjeta",
                        )
                    )

        # 2. Compromisos de deudas
        detalles_deudas = self.obtener_detalles_deudas(hoy)
        for dd in detalles_deudas:
            if hoy <= dd.proximo_pago <= limite_horizonte:
                if dd.cuota_centavos > 0 and dd.cuenta.cuenta_pago_id:
                    compromisos.append(
                        CompromisoPago(
                            descripcion=f"{dd.cuenta.nombre}, cuota {dd.proximo_pago.strftime('%d-%b')}",
                            cuenta_pago_id=dd.cuenta.cuenta_pago_id,
                            cuenta_pago_nombre=dd.cuenta_pago_nombre,
                            monto_centavos=dd.cuota_centavos,
                            fecha_vencimiento=dd.proximo_pago,
                            dias_restantes=dd.dias_al_pago,
                            tipo="deuda",
                        )
                    )

        # Ordenar compromisos por fecha de vencimiento
        compromisos.sort(key=lambda x: x.fecha_vencimiento)

        # Agrupar por cuenta de débito/pago
        compromisos_por_cuenta: Dict[int, Dict[str, Any]] = {}
        for c in compromisos:
            if c.cuenta_pago_id not in compromisos_por_cuenta:
                saldo_actual = self.calcular_saldo_cuenta(c.cuenta_pago_id)
                compromisos_por_cuenta[c.cuenta_pago_id] = {
                    "nombre": c.cuenta_pago_nombre,
                    "saldo_actual": saldo_actual,
                    "total_compromisos": 0,
                    "items": [],
                }
            compromisos_por_cuenta[c.cuenta_pago_id]["total_compromisos"] += c.monto_centavos
            compromisos_por_cuenta[c.cuenta_pago_id]["items"].append(c)

        total_falta_depositar = 0
        for cta_id, datos in compromisos_por_cuenta.items():
            falta = max(0, datos["total_compromisos"] - datos["saldo_actual"])
            datos["falta_depositar"] = falta
            total_falta_depositar += falta

        total_compromisos = sum(c.monto_centavos for c in compromisos)

        return ReportePorDepositar(
            horizonte_dias=horizonte_dias,
            compromisos=compromisos,
            compromisos_por_cuenta=compromisos_por_cuenta,
            total_compromisos=total_compromisos,
            total_falta_depositar=total_falta_depositar,
        )

    # ============================================================== #
    #                     CONTROL DE EFECTIVO                        #
    # ============================================================== #

    def obtener_metricas_efectivo(
        self, cuenta_efectivo_id: Optional[int] = None, fecha_ref: Optional[date] = None
    ) -> MetricasEfectivo:
        hoy = fecha_ref or date.today()
        hoy_str = hoy.strftime("%Y-%m-%d")

        # Localizar cuenta de cartera diaria o la primera de efectivo
        cuenta = None
        if cuenta_efectivo_id:
            cuenta = self.db.get_cuenta(cuenta_efectivo_id)
        if not cuenta:
            cuentas = self.db.get_cuentas()
            for c in cuentas:
                if c.tipo == TipoCuenta.EFECTIVO and "cartera" in c.nombre.lower():
                    cuenta = c
                    break
            if not cuenta:
                for c in cuentas:
                    if c.tipo == TipoCuenta.EFECTIVO:
                        cuenta = c
                        break

        if not cuenta:
            # Fallback seguro
            return MetricasEfectivo(
                cuenta_id=0,
                cuenta_nombre="Sin cuenta efectivo",
                llevo_hoy=0,
                gasto_hoy=0,
                sobra_actual=0,
                promedio_7_dias=0,
                gastos_hoy_detalle=[],
            )

        cur = self.db.get_cursor()

        # 1. Llevé hoy: transferencias hacia esta cuenta en el día de hoy
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_destino_id = ?
                 AND tipo = ?
                 AND fecha = ?""",
            (cuenta.id, TipoMovimiento.TRANSFERENCIA, hoy_str),
        )
        llevo_hoy = cur.fetchone()[0]

        # 2. Gasté hoy: gastos salientes de esta cuenta hoy
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_origen_id = ?
                 AND tipo = ?
                 AND fecha = ?""",
            (cuenta.id, TipoMovimiento.GASTO, hoy_str),
        )
        gasto_hoy = cur.fetchone()[0]

        # 3. Sobra actual: saldo dinámico de la cuenta
        sobra_actual = self.calcular_saldo_cuenta(cuenta.id)

        # 4. Promedio de los últimos 7 días
        hace_7_dias = (hoy - timedelta(days=6)).strftime("%Y-%m-%d")
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE cuenta_origen_id = ?
                 AND tipo = ?
                 AND fecha >= ? AND fecha <= ?""",
            (cuenta.id, TipoMovimiento.GASTO, hace_7_dias, hoy_str),
        )
        total_7_dias = cur.fetchone()[0]
        promedio_7_dias = total_7_dias // 7

        # 5. Lista de gastos del día
        gastos_hoy = self.db.get_movimientos(
            cuenta_id=cuenta.id, fecha_desde=hoy_str, fecha_hasta=hoy_str, tipo=TipoMovimiento.GASTO
        )

        return MetricasEfectivo(
            cuenta_id=cuenta.id,
            cuenta_nombre=cuenta.nombre,
            llevo_hoy=llevo_hoy,
            gasto_hoy=gasto_hoy,
            sobra_actual=sobra_actual,
            promedio_7_dias=promedio_7_dias,
            gastos_hoy_detalle=gastos_hoy,
        )

    def accion_llevar_hoy(
        self, cuenta_destino_id: int, monto_centavos: Optional[int] = None
    ) -> Movimiento:
        """Transfiere dinero desde la primera cuenta de débito disponible a la cartera diaria."""
        config = self.db.get_config()
        monto = monto_centavos or config.monto_efectivo_diario_centavos

        # Buscar cuenta de débito de origen
        cuentas = self.db.get_cuentas()
        origen_id = None
        for c in cuentas:
            if c.tipo == TipoCuenta.DEBITO:
                origen_id = c.id
                break
        if not origen_id:
            for c in cuentas:
                if c.tipo == TipoCuenta.EFECTIVO and c.id != cuenta_destino_id:
                    origen_id = c.id
                    break

        hoy_str = date.today().strftime("%Y-%m-%d")
        mov = Movimiento(
            id=None,
            fecha=hoy_str,
            tipo=TipoMovimiento.TRANSFERENCIA,
            monto_centavos=monto,
            cuenta_origen_id=origen_id,
            cuenta_destino_id=cuenta_destino_id,
            categoria_id=None,
            nota="Llevar efectivo hoy",
        )
        mov_id = self.db.agregar_movimiento(mov)
        mov.id = mov_id
        return mov

    def accion_devolver_sobrante(
        self, cuenta_origen_id: int, cuenta_destino_id: Optional[int] = None
    ) -> Optional[Movimiento]:
        """Transfiere el saldo restante de la cartera a una cuenta de ahorro o débito."""
        saldo_sobrante = self.calcular_saldo_cuenta(cuenta_origen_id)
        if saldo_sobrante <= 0:
            return None

        if not cuenta_destino_id:
            cuentas = self.db.get_cuentas()
            for c in cuentas:
                if c.tipo in (TipoCuenta.EFECTIVO, TipoCuenta.DEBITO) and c.id != cuenta_origen_id:
                    if "ahorro" in c.nombre.lower() or c.tipo == TipoCuenta.DEBITO:
                        cuenta_destino_id = c.id
                        break
            if not cuenta_destino_id and cuentas:
                cuenta_destino_id = cuentas[0].id

        hoy_str = date.today().strftime("%Y-%m-%d")
        mov = Movimiento(
            id=None,
            fecha=hoy_str,
            tipo=TipoMovimiento.TRANSFERENCIA,
            monto_centavos=saldo_sobrante,
            cuenta_origen_id=cuenta_origen_id,
            cuenta_destino_id=cuenta_destino_id,
            categoria_id=None,
            nota="Devolver sobrante de efectivo",
        )
        mov_id = self.db.agregar_movimiento(mov)
        mov.id = mov_id
        return mov

    # ============================================================== #
    #                     MÉTRICAS GASTO HORMIGA                     #
    # ============================================================== #

    def obtener_metricas_hormiga(
        self, anio: Optional[int] = None, mes: Optional[int] = None
    ) -> MetricasHormiga:
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        primer_dia = f"{anio:04d}-{mes:02d}-01"
        dias_en_mes = calendar.monthrange(anio, mes)[1]
        ultimo_dia = f"{anio:04d}-{mes:02d}-{dias_en_mes:02d}"

        mes_nombre = hoy.strftime("%B %Y")
        try:
            mes_nombre = date(anio, mes, 1).strftime("%B %Y").capitalize()
        except Exception:
            pass

        cur = self.db.get_cursor()

        # Total gastos del mes
        cur.execute(
            """SELECT COALESCE(SUM(monto_centavos), 0)
               FROM movimientos
               WHERE tipo = ? AND fecha >= ? AND fecha <= ?""",
            (TipoMovimiento.GASTO, primer_dia, ultimo_dia),
        )
        total_gastos = cur.fetchone()[0]

        # Total gasto hormiga del mes: categorías marcadas con es_hormiga=1
        cur.execute(
            """SELECT COALESCE(SUM(m.monto_centavos), 0)
               FROM movimientos m
               JOIN categorias c ON m.categoria_id = c.id
               WHERE m.tipo = ?
                 AND c.es_hormiga = 1
                 AND m.fecha >= ? AND m.fecha <= ?""",
            (TipoMovimiento.GASTO, primer_dia, ultimo_dia),
        )
        total_hormiga = cur.fetchone()[0]

        pct_hormiga = (total_hormiga / total_gastos * 100.0) if total_gastos > 0 else 0.0
        proyeccion_anual = total_hormiga * 12

        # Top 5 conceptos o categorías hormiga
        cur.execute(
            """SELECT COALESCE(NULLIF(m.nota, ''), c.nombre) AS concepto,
                      SUM(m.monto_centavos) AS suma
               FROM movimientos m
               JOIN categorias c ON m.categoria_id = c.id
               WHERE m.tipo = ?
                 AND c.es_hormiga = 1
                 AND m.fecha >= ? AND m.fecha <= ?
               GROUP BY concepto
               ORDER BY suma DESC
               LIMIT 5""",
            (TipoMovimiento.GASTO, primer_dia, ultimo_dia),
        )
        top_conceptos = [(r["concepto"], r["suma"]) for r in cur.fetchall()]

        # Barras diarias del mes
        cur.execute(
            """SELECT CAST(strftime('%d', m.fecha) AS INTEGER) AS dia,
                      SUM(m.monto_centavos) AS suma
               FROM movimientos m
               JOIN categorias c ON m.categoria_id = c.id
               WHERE m.tipo = ?
                 AND c.es_hormiga = 1
                 AND m.fecha >= ? AND m.fecha <= ?
               GROUP BY dia
               ORDER BY dia ASC""",
            (TipoMovimiento.GASTO, primer_dia, ultimo_dia),
        )
        dias_dict = {r["dia"]: r["suma"] for r in cur.fetchall()}

        barras_diarias = []
        max_dia_centavos = 1
        for d in range(1, dias_en_mes + 1):
            val = dias_dict.get(d, 0)
            barras_diarias.append((d, val))
            if val > max_dia_centavos:
                max_dia_centavos = val

        return MetricasHormiga(
            mes_str=f"{mes_nombre}",
            total_hormiga_centavos=total_hormiga,
            total_gastos_centavos=total_gastos,
            porcentaje_hormiga=pct_hormiga,
            proyeccion_anual_centavos=proyeccion_anual,
            top_conceptos=top_conceptos,
            barras_diarias=barras_diarias,
            max_dia_centavos=max_dia_centavos,
        )

    # ============================================================== #
    #                     AJUSTE DE SALDO                            #
    # ============================================================== #

    def ajustar_saldo_cuenta(
        self, cuenta_id: int, nuevo_saldo_centavos: int, nota: str = "Ajuste de saldo"
    ) -> Movimiento:
        """Crea un movimiento de ajuste visible para cuadrar el saldo dinámico."""
        cuenta = self.db.get_cuenta(cuenta_id)
        if not cuenta:
            raise ValueError(f"Cuenta no encontrada: {cuenta_id}")

        saldo_actual = self.calcular_saldo_cuenta(cuenta_id)
        diferencia = nuevo_saldo_centavos - saldo_actual

        if diferencia == 0:
            raise ValueError("El saldo ya coincide con el monto indicado.")

        cat_id = self.db.get_or_create_categoria("Ajuste de saldo")
        hoy_str = date.today().strftime("%Y-%m-%d")

        if cuenta.es_activo:
            if diferencia > 0:
                # El saldo sube: entrada a la cuenta
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.AJUSTE,
                    monto_centavos=diferencia,
                    cuenta_origen_id=None,
                    cuenta_destino_id=cuenta_id,
                    categoria_id=cat_id,
                    nota=nota,
                )
            else:
                # El saldo baja: salida de la cuenta
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.AJUSTE,
                    monto_centavos=abs(diferencia),
                    cuenta_origen_id=cuenta_id,
                    cuenta_destino_id=None,
                    categoria_id=cat_id,
                    nota=nota,
                )
        else:
            # En pasivos: diferencia > 0 aumenta la deuda
            if diferencia > 0:
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.AJUSTE,
                    monto_centavos=diferencia,
                    cuenta_origen_id=cuenta_id,
                    cuenta_destino_id=None,
                    categoria_id=cat_id,
                    nota=nota,
                )
            else:
                mov = Movimiento(
                    id=None,
                    fecha=hoy_str,
                    tipo=TipoMovimiento.AJUSTE,
                    monto_centavos=abs(diferencia),
                    cuenta_origen_id=None,
                    cuenta_destino_id=cuenta_id,
                    categoria_id=cat_id,
                    nota=nota,
                )

        mov_id = self.db.agregar_movimiento(mov)
        mov.id = mov_id
        return mov

    # ============================================================== #
    #                     REGISTRO DE PAGOS                          #
    # ============================================================== #

    def registrar_pago_pasivo(
        self,
        cuenta_pasivo_id: int,
        cuenta_activo_id: int,
        monto_centavos: int,
        nota: Optional[str] = None,
        fecha: Optional[str] = None,
    ) -> Movimiento:
        """Registra un pago desde un activo hacia un pasivo (tarjeta o préstamo)."""
        cta_pasivo = self.db.get_cuenta(cuenta_pasivo_id)
        if not cta_pasivo or not cta_pasivo.es_pasivo:
            raise ValueError(f"Cuenta destino no es un pasivo válido: {cuenta_pasivo_id}")

        cta_activo = self.db.get_cuenta(cuenta_activo_id)
        if not cta_activo or not cta_activo.es_activo:
            raise ValueError(f"Cuenta origen no es un activo válido: {cuenta_activo_id}")

        if monto_centavos <= 0:
            raise ValueError("El monto a pagar debe ser mayor a cero.")

        fecha_str = fecha or date.today().strftime("%Y-%m-%d")
        desc_nota = nota or f"Pago a {cta_pasivo.nombre} desde {cta_activo.nombre}"

        mov = Movimiento(
            id=None,
            fecha=fecha_str,
            tipo=TipoMovimiento.PAGO,
            monto_centavos=monto_centavos,
            cuenta_origen_id=cuenta_activo_id,
            cuenta_destino_id=cuenta_pasivo_id,
            categoria_id=None,
            nota=desc_nota,
        )
        mov_id = self.db.agregar_movimiento(mov)
        mov.id = mov_id
        return mov
