"""Modo CLI no interactivo para uso en terminal y scripts."""
import argparse
import os
import sys
from datetime import date
from typing import List, Optional

from gastli import paths
from gastli.core import FinanceCore
from gastli.db import Database
from gastli.export.csv_export import CsvExporter
from gastli.export.xlsx import ExcelExporter
from gastli.models import (
    Cuenta,
    Movimiento,
    TipoCuenta,
    TipoMovimiento,
    centavos_a_str,
    parse_monto_a_centavos,
)


def buscar_cuenta_por_texto(cuentas: List[Cuenta], texto: str) -> Optional[Cuenta]:
    """Busca una cuenta por coincidencia exacta o parcial de nombre."""
    t = texto.strip().lower()
    # 1. Coincidencia exacta
    for c in cuentas:
        if c.nombre.lower() == t:
            return c
    # 2. Empieza con
    for c in cuentas:
        if c.nombre.lower().startswith(t):
            return c
    # 3. Contiene
    for c in cuentas:
        if t in c.nombre.lower():
            return c
    return None


def cmd_saldo(core: FinanceCore, args: argparse.Namespace) -> int:
    config = core.db.get_config()
    resumen = core.obtener_resumen_global()
    cuentas = core.db.get_cuentas(incluir_archivadas=False)
    por_dep = core.calcular_por_depositar(horizonte_dias=config.horizonte_dias)

    print("\n╭─ Saldos de Activos " + "─" * 38 + "╮")
    for c in cuentas:
        if c.es_activo:
            saldo = core.calcular_saldo_cuenta(c.id)
            monto_str = centavos_a_str(saldo, config.moneda, con_signo=False)
            print(f"│  {c.nombre:<28} {monto_str:>26} │")
    total_act_str = centavos_a_str(resumen.total_activos, config.moneda, con_signo=False)
    print("├" + "─" * 58 + "┤")
    print(f"│  {'Total Activos':<28} {total_act_str:>26} │")
    print("╰" + "─" * 58 + "╯")

    print("\n╭─ Tarjetas y Deudas " + "─" * 38 + "╮")
    for c in cuentas:
        if c.es_pasivo:
            saldo = core.calcular_saldo_cuenta(c.id)
            monto_str = centavos_a_str(saldo, config.moneda, con_signo=False)
            print(f"│  {c.nombre:<28} {monto_str:>26} │")
    total_pas_str = centavos_a_str(resumen.total_pasivos, config.moneda, con_signo=False)
    print("├" + "─" * 58 + "┤")
    print(f"│  {'Total Pasivos':<28} {total_pas_str:>26} │")
    print("╰" + "─" * 58 + "╯")

    print(f"\n╭─ Por Depositar ({config.horizonte_dias} días) " + "─" * 33 + "╮")
    if por_dep.compromisos:
        for comp in por_dep.compromisos:
            monto_str = centavos_a_str(comp.monto_centavos, config.moneda, con_signo=False)
            print(f"│  {comp.descripcion:<34} {monto_str:>20} │")
        print("├" + "─" * 58 + "┤")
    falta_str = centavos_a_str(por_dep.total_falta_depositar, config.moneda, con_signo=False)
    print(f"│  {'Falta Depositar':<34} {falta_str:>20} │")
    print("╰" + "─" * 58 + "╯\n")
    return 0


def cmd_gasto(core: FinanceCore, args: argparse.Namespace) -> int:
    try:
        centavos = parse_monto_a_centavos(args.monto)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    concepto = " ".join(args.concepto) if isinstance(args.concepto, list) else (args.concepto or "Gasto")
    cuentas = core.db.get_cuentas(incluir_archivadas=False)

    # Identificar cuenta de origen
    cuenta_origen = None
    if getattr(args, "cuenta", None):
        cuenta_origen = buscar_cuenta_por_texto(cuentas, args.cuenta)
        if not cuenta_origen:
            print(f"Error: Cuenta '{args.cuenta}' no encontrada.", file=sys.stderr)
            return 1
    else:
        # Por defecto usar Cartera Diaria o la primera de efectivo/débito
        for c in cuentas:
            if "cartera" in c.nombre.lower():
                cuenta_origen = c
                break
        if not cuenta_origen:
            for c in cuentas:
                if c.es_activo:
                    cuenta_origen = c
                    break

    if not cuenta_origen:
        print("Error: No hay cuentas de origen disponibles.", file=sys.stderr)
        return 1

    # Identificar o crear categoría
    cat_id = None
    if getattr(args, "categoria", None):
        cat_id = core.db.get_or_create_categoria(args.categoria)
    else:
        # Clasificar automáticamente si coincide con palabras clave conocidas
        concepto_lower = concepto.lower()
        if any(w in concepto_lower for w in ["cafe", "café", "snack", "tacos", "antojo"]):
            cat_id = core.db.get_or_create_categoria("Antojos y Comida rápida", es_hormiga=True)
        else:
            cat_id = core.db.get_or_create_categoria("Alimentos y Supermercado")

    hoy_str = date.today().strftime("%Y-%m-%d")
    mov = Movimiento(
        id=None,
        fecha=hoy_str,
        tipo=TipoMovimiento.GASTO,
        monto_centavos=centavos,
        cuenta_origen_id=cuenta_origen.id,
        cuenta_destino_id=None,
        categoria_id=cat_id,
        nota=concepto,
    )
    mov_id = core.db.agregar_movimiento(mov)
    nuevo_saldo = core.calcular_saldo_cuenta(cuenta_origen.id)
    config = core.db.get_config()

    print(
        f"Gasto registrado: {centavos_a_str(centavos, config.moneda)} en '{cuenta_origen.nombre}' ({concepto}). Saldo actual: {centavos_a_str(nuevo_saldo, config.moneda)}"
    )
    return 0


def cmd_ingreso(core: FinanceCore, args: argparse.Namespace) -> int:
    try:
        centavos = parse_monto_a_centavos(args.monto)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    concepto = " ".join(args.concepto) if isinstance(args.concepto, list) else (args.concepto or "Ingreso")
    cuentas = core.db.get_cuentas(incluir_archivadas=False)

    cuenta_destino = None
    if getattr(args, "cuenta", None):
        cuenta_destino = buscar_cuenta_por_texto(cuentas, args.cuenta)
        if not cuenta_destino:
            print(f"Error: Cuenta '{args.cuenta}' no encontrada.", file=sys.stderr)
            return 1
    else:
        # Por defecto usar cuenta de débito principal
        for c in cuentas:
            if c.tipo == TipoCuenta.DEBITO:
                cuenta_destino = c
                break

    if not cuenta_destino:
        print("Error: No hay cuenta destino disponible.", file=sys.stderr)
        return 1

    cat_id = core.db.get_or_create_categoria("Ingresos extra")
    hoy_str = date.today().strftime("%Y-%m-%d")
    mov = Movimiento(
        id=None,
        fecha=hoy_str,
        tipo=TipoMovimiento.INGRESO,
        monto_centavos=centavos,
        cuenta_destino_id=cuenta_destino.id,
        categoria_id=cat_id,
        nota=concepto,
    )
    mov_id = core.db.agregar_movimiento(mov)
    nuevo_saldo = core.calcular_saldo_cuenta(cuenta_destino.id)
    config = core.db.get_config()
    print(
        f"Ingreso registrado: {centavos_a_str(centavos, config.moneda)} a '{cuenta_destino.nombre}'. Nuevo saldo: {centavos_a_str(nuevo_saldo, config.moneda)}"
    )
    return 0


def cmd_transfer(core: FinanceCore, args: argparse.Namespace) -> int:
    try:
        centavos = parse_monto_a_centavos(args.monto)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    cuentas = core.db.get_cuentas(incluir_archivadas=False)
    cta_origen = buscar_cuenta_por_texto(cuentas, args.origen)
    cta_destino = buscar_cuenta_por_texto(cuentas, args.destino)

    if not cta_origen:
        print(f"Error: Cuenta origen '{args.origen}' no encontrada.", file=sys.stderr)
        return 1
    if not cta_destino:
        print(f"Error: Cuenta destino '{args.destino}' no encontrada.", file=sys.stderr)
        return 1

    hoy_str = date.today().strftime("%Y-%m-%d")
    mov = Movimiento(
        id=None,
        fecha=hoy_str,
        tipo=TipoMovimiento.TRANSFERENCIA,
        monto_centavos=centavos,
        cuenta_origen_id=cta_origen.id,
        cuenta_destino_id=cta_destino.id,
        nota=f"Transferencia de {cta_origen.nombre} a {cta_destino.nombre}",
    )
    core.db.agregar_movimiento(mov)
    config = core.db.get_config()
    print(
        f"Transferencia completada: {centavos_a_str(centavos, config.moneda)} de '{cta_origen.nombre}' a '{cta_destino.nombre}'."
    )
    return 0


def cmd_pago(core: FinanceCore, args: argparse.Namespace) -> int:
    try:
        centavos = parse_monto_a_centavos(args.monto)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    cuentas = core.db.get_cuentas(incluir_archivadas=False)
    cta_pasivo = buscar_cuenta_por_texto(cuentas, args.destino)
    if not cta_pasivo or not cta_pasivo.es_pasivo:
        print(f"Error: Pasivo/tarjeta '{args.destino}' no encontrado.", file=sys.stderr)
        return 1

    cta_origen = None
    if getattr(args, "desde", None):
        cta_origen = buscar_cuenta_por_texto(cuentas, args.desde)
    elif cta_pasivo.cuenta_pago_id:
        cta_origen = core.db.get_cuenta(cta_pasivo.cuenta_pago_id)

    if not cta_origen or not cta_origen.es_activo:
        for c in cuentas:
            if c.tipo == TipoCuenta.DEBITO:
                cta_origen = c
                break

    if not cta_origen:
        print("Error: No hay cuenta de activo de origen disponible para pagar.", file=sys.stderr)
        return 1

    core.registrar_pago_pasivo(
        cuenta_pasivo_id=cta_pasivo.id,
        cuenta_activo_id=cta_origen.id,
        monto_centavos=centavos,
    )
    config = core.db.get_config()
    deuda_restante = core.calcular_saldo_cuenta(cta_pasivo.id)
    saldo_activo = core.calcular_saldo_cuenta(cta_origen.id)
    print(
        f"Pago registrado: {centavos_a_str(centavos, config.moneda)} a '{cta_pasivo.nombre}' desde '{cta_origen.nombre}'."
    )
    print(
        f"Saldo restante en {cta_pasivo.nombre}: {centavos_a_str(deuda_restante, config.moneda)} | Saldo en {cta_origen.nombre}: {centavos_a_str(saldo_activo, config.moneda)}"
    )
    return 0


def cmd_export(core: FinanceCore, args: argparse.Namespace) -> int:
    formato = getattr(args, "formato", "xlsx") or "xlsx"
    salida = getattr(args, "salida", None)

    if formato.lower() == "csv":
        ruta = salida or os.path.join(paths.exports_dir(), "finanzas_movimientos.csv")
        csv_exp = CsvExporter(core)
        res = csv_exp.exportar_movimientos(ruta)
        print(f"Exportación CSV generada en: {res}")
    else:
        ruta = salida or os.path.join(paths.exports_dir(), "finanzas_export.xlsx")
        xlsx_exp = ExcelExporter(core)
        res = xlsx_exp.exportar(ruta)
        print(f"Libro Excel generado exitosamente en: {res}")
    return 0


def cmd_backup(core: FinanceCore, args: argparse.Namespace) -> int:
    ruta = core.db.realizar_respaldo()
    if ruta:
        print(f"Respaldo creado exitosamente: {ruta}")
        return 0
    print("Error al crear respaldo.", file=sys.stderr)
    return 1


def ejecutar_cli(core: FinanceCore, argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gastli",
        description="Sistema de finanzas personales en terminal.",
    )
    subparsers = parser.add_subparsers(dest="subcomando")

    # saldo
    subparsers.add_parser("saldo", help="Muestra el resumen de saldos y por depositar")

    # gasto
    p_gasto = subparsers.add_parser("gasto", aliases=["g"], help="Registra un gasto")
    p_gasto.add_argument("monto", help="Monto gastado")
    p_gasto.add_argument("concepto", nargs="*", help="Concepto o descripción")
    p_gasto.add_argument("--cuenta", "-c", help="Cuenta de origen")
    p_gasto.add_argument("--categoria", "-cat", help="Categoría")

    # ingreso
    p_ingreso = subparsers.add_parser("ingreso", aliases=["i"], help="Registra un ingreso")
    p_ingreso.add_argument("monto", help="Monto ingresado")
    p_ingreso.add_argument("concepto", nargs="*", help="Concepto o descripción")
    p_ingreso.add_argument("--cuenta", "-c", help="Cuenta de destino")

    # transfer
    p_trans = subparsers.add_parser("transfer", aliases=["t"], help="Transferencia entre cuentas")
    p_trans.add_argument("monto", help="Monto a transferir")
    p_trans.add_argument("origen", help="Cuenta de origen")
    p_trans.add_argument("destino", help="Cuenta de destino")

    # pago
    p_pago = subparsers.add_parser("pago", aliases=["p"], help="Pago a tarjeta o deuda")
    p_pago.add_argument("monto", help="Monto a pagar")
    p_pago.add_argument("destino", help="Tarjeta o deuda a pagar")
    p_pago.add_argument("--desde", "-d", help="Cuenta de débito/efectivo de origen")

    # export
    p_exp = subparsers.add_parser("export", help="Exporta a Excel o CSV")
    p_exp.add_argument("--formato", choices=["xlsx", "csv"], default="xlsx", help="Formato de salida")
    p_exp.add_argument("--salida", "-o", help="Ruta del archivo de salida")

    # backup
    subparsers.add_parser("backup", help="Crea un respaldo de la base de datos")

    args = parser.parse_args(argv)

    if args.subcomando in ("saldo", None):
        return cmd_saldo(core, args)
    elif args.subcomando in ("gasto", "g"):
        return cmd_gasto(core, args)
    elif args.subcomando in ("ingreso", "i"):
        return cmd_ingreso(core, args)
    elif args.subcomando in ("transfer", "t"):
        return cmd_transfer(core, args)
    elif args.subcomando in ("pago", "p"):
        return cmd_pago(core, args)
    elif args.subcomando == "export":
        return cmd_export(core, args)
    elif args.subcomando == "backup":
        return cmd_backup(core, args)
    else:
        parser.print_help()
        return 0
