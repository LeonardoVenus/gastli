"""Capa de base de datos SQLite para finanzas personales."""
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from gastli import paths
from gastli.models import (
    Categoria,
    Configuracion,
    Cuenta,
    Deuda,
    Movimiento,
    TarjetaCredito,
    TipoCuenta,
    TipoMovimiento,
)

DEFAULT_DB_PATH = paths.db_path()
DEFAULT_BACKUPS_DIR = paths.backups_dir()


class Database:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.crear_tablas()
        self.sembrar_datos_iniciales()

    def get_cursor(self) -> sqlite3.Cursor:
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def crear_tablas(self):
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL UNIQUE,
                    tipo TEXT NOT NULL,
                    saldo_inicial_centavos INTEGER NOT NULL DEFAULT 0,
                    cuenta_pago_id INTEGER,
                    archivada INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (cuenta_pago_id) REFERENCES cuentas(id)
                );

                CREATE TABLE IF NOT EXISTS tarjetas_credito (
                    cuenta_id INTEGER PRIMARY KEY,
                    limite_centavos INTEGER NOT NULL,
                    dia_corte INTEGER NOT NULL,
                    dia_limite_pago INTEGER NOT NULL,
                    pago_minimo_centavos INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (cuenta_id) REFERENCES cuentas(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS deudas (
                    cuenta_id INTEGER PRIMARY KEY,
                    monto_original_centavos INTEGER NOT NULL,
                    cuota_centavos INTEGER NOT NULL,
                    dia_pago INTEGER NOT NULL,
                    fecha_inicio TEXT,
                    FOREIGN KEY (cuenta_id) REFERENCES cuentas(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS categorias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL UNIQUE,
                    es_hormiga INTEGER NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS movimientos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    monto_centavos INTEGER NOT NULL,
                    cuenta_origen_id INTEGER,
                    cuenta_destino_id INTEGER,
                    categoria_id INTEGER,
                    nota TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (cuenta_origen_id) REFERENCES cuentas(id),
                    FOREIGN KEY (cuenta_destino_id) REFERENCES cuentas(id),
                    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
                );

                CREATE TABLE IF NOT EXISTS configuracion (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS historial_undo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operacion TEXT NOT NULL,
                    datos_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos(fecha);
                CREATE INDEX IF NOT EXISTS idx_movimientos_tipo ON movimientos(tipo);
                CREATE INDEX IF NOT EXISTS idx_movimientos_origen ON movimientos(cuenta_origen_id);
                CREATE INDEX IF NOT EXISTS idx_movimientos_destino ON movimientos(cuenta_destino_id);
                """
            )

    def sembrar_datos_iniciales(self):
        """Inserta configuraciones y catálogo base si la BD es nueva."""
        with self.conn:
            # Configuración
            config_defaults = {
                "moneda": "$",
                "horizonte_dias": "15",
                "monto_efectivo_diario": "20000",  # $200.00
                "umbral_hormiga": "10000",         # $100.00
                "backups_rotacion": "5",
            }
            for k, v in config_defaults.items():
                self.conn.execute(
                    "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)",
                    (k, v),
                )

            # Categorías por defecto si está vacía
            cur = self.conn.execute("SELECT COUNT(*) FROM categorias")
            if cur.fetchone()[0] == 0:
                cats = [
                    ("Alimentos y Supermercado", 0),
                    ("Café y Snacks", 1),
                    ("Antojos y Comida rápida", 1),
                    ("Propinas y Varios pequeños", 1),
                    ("Transporte y Taxis", 0),
                    ("Servicios (Luz, Agua,etc)", 0),
                    ("Vivienda y Renta", 0),
                    ("Salud y Farmacia", 0),
                    ("Ocio y Salidas", 0),
                    ("Educación", 0),
                    ("Ropa y Calzado", 0),
                    ("Sueldo / Nómina", 0),
                    ("Ingresos extra", 0),
                    ("Ajuste de saldo", 0),
                ]
                self.conn.executemany(
                    "INSERT INTO categorias (nombre, es_hormiga, activo) VALUES (?, ?, 1)",
                    cats,
                )

            # Cuentas iniciales si está vacía y nunca se ha sembrado
            cur_demo = self.conn.execute("SELECT valor FROM configuracion WHERE clave = 'demo_sembrado'")
            if not cur_demo.fetchone():
                cur_cuentas = self.conn.execute("SELECT COUNT(*) FROM cuentas")
                if cur_cuentas.fetchone()[0] == 0:
                    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    hoy = datetime.now().strftime("%Y-%m-%d")

                    # 1. BBVA Débito
                    cur = self.conn.execute(
                        "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, created_at) VALUES (?, ?, ?, ?)",
                        ("BBVA Débito", TipoCuenta.DEBITO, 420000, ahora),
                    )
                    bbva_id = cur.lastrowid

                    # 2. Ahorro Efectivo
                    self.conn.execute(
                        "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, created_at) VALUES (?, ?, ?, ?)",
                        ("Ahorro Efectivo", TipoCuenta.EFECTIVO, 300000, ahora),
                    )

                    # 3. Cartera Diaria
                    self.conn.execute(
                        "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, created_at) VALUES (?, ?, ?, ?)",
                        ("Cartera Diaria", TipoCuenta.EFECTIVO, 18000, ahora),
                    )

                    # 4. Tarjeta Nu (Crédito)
                    cur_nu = self.conn.execute(
                        "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        ("Tarjeta Nu", TipoCuenta.CREDITO, 0, bbva_id, ahora),
                    )
                    nu_id = cur_nu.lastrowid
                    self.conn.execute(
                        "INSERT INTO tarjetas_credito (cuenta_id, limite_centavos, dia_corte, dia_limite_pago, pago_minimo_centavos) VALUES (?, ?, ?, ?, ?)",
                        (nu_id, 1500000, 12, 2, 25000),
                    )

                    # 5. Préstamo personal (Deuda)
                    cur_deuda = self.conn.execute(
                        "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        ("Préstamo Personal", TipoCuenta.DEUDA, 0, bbva_id, ahora),
                    )
                    deuda_id = cur_deuda.lastrowid
                    self.conn.execute(
                        "INSERT INTO deudas (cuenta_id, monto_original_centavos, cuota_centavos, dia_pago, fecha_inicio) VALUES (?, ?, ?, ?, ?)",
                        (deuda_id, 1200000, 120000, 15, hoy),
                    )

                    # Movimiento inicial de ajuste/saldo para BBVA
                    cur_cat = self.conn.execute("SELECT id FROM categorias WHERE nombre = 'Ajuste de saldo'")
                    row_cat = cur_cat.fetchone()
                    if row_cat:
                        cat_ajuste = row_cat[0]
                        self.conn.execute(
                            """INSERT INTO movimientos (fecha, tipo, monto_centavos, cuenta_destino_id, categoria_id, nota, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (hoy, TipoMovimiento.AJUSTE, 420000, bbva_id, cat_ajuste, "Saldo inicial", ahora)
                        )
                self.conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('demo_sembrado', '1')")

    # ---------------- Operaciones de Configuración ---------------- #
    def get_config(self) -> Configuracion:
        cur = self.conn.execute("SELECT clave, valor FROM configuracion")
        data = {row["clave"]: row["valor"] for row in cur.fetchall()}
        return Configuracion(
            moneda=data.get("moneda", "$"),
            horizonte_dias=int(data.get("horizonte_dias", 15)),
            monto_efectivo_diario_centavos=int(data.get("monto_efectivo_diario", 20000)),
            umbral_hormiga_centavos=int(data.get("umbral_hormiga", 10000)),
            backups_rotacion=int(data.get("backups_rotacion", 5)),
        )

    def set_config(self, clave: str, valor: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO configuracion (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, valor),
            )

    # ---------------- Operaciones de Cuentas ---------------- #
    def get_cuentas(self, incluir_archivadas: bool = False) -> List[Cuenta]:
        sql = "SELECT id, nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, archivada, created_at FROM cuentas"
        if not incluir_archivadas:
            sql += " WHERE archivada = 0"
        sql += " ORDER BY CASE tipo WHEN 'debito' THEN 1 WHEN 'efectivo' THEN 2 WHEN 'credito' THEN 3 WHEN 'deuda' THEN 4 END, nombre ASC"
        cur = self.conn.execute(sql)
        return [
            Cuenta(
                id=r["id"],
                nombre=r["nombre"],
                tipo=r["tipo"],
                saldo_inicial_centavos=r["saldo_inicial_centavos"],
                cuenta_pago_id=r["cuenta_pago_id"],
                archivada=bool(r["archivada"]),
                created_at=r["created_at"],
            )
            for r in cur.fetchall()
        ]

    def get_cuenta(self, cuenta_id: int) -> Optional[Cuenta]:
        cur = self.conn.execute(
            "SELECT id, nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, archivada, created_at FROM cuentas WHERE id = ?",
            (cuenta_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return Cuenta(
            id=r["id"],
            nombre=r["nombre"],
            tipo=r["tipo"],
            saldo_inicial_centavos=r["saldo_inicial_centavos"],
            cuenta_pago_id=r["cuenta_pago_id"],
            archivada=bool(r["archivada"]),
            created_at=r["created_at"],
        )

    def crear_cuenta(
        self,
        nombre: str,
        tipo: str,
        saldo_inicial_centavos: int = 0,
        cuenta_pago_id: Optional[int] = None,
    ) -> int:
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO cuentas (nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, archivada, created_at) VALUES (?, ?, ?, ?, 0, ?)",
                (nombre, tipo, saldo_inicial_centavos, cuenta_pago_id, ahora),
            )
            cuenta_id = cur.lastrowid
            if saldo_inicial_centavos != 0 and tipo in TipoCuenta.ACTIVOS:
                hoy = datetime.now().strftime("%Y-%m-%d")
                cat_ajuste_id = self.get_or_create_categoria("Ajuste de saldo")
                self.conn.execute(
                    """INSERT INTO movimientos (fecha, tipo, monto_centavos, cuenta_destino_id, categoria_id, nota, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (hoy, TipoMovimiento.AJUSTE, saldo_inicial_centavos, cuenta_id, cat_ajuste_id, "Saldo inicial", ahora)
                )
            return cuenta_id

    def actualizar_cuenta(
        self,
        cuenta_id: int,
        nombre: str,
        cuenta_pago_id: Optional[int] = None,
        archivada: Optional[bool] = None,
        tipo: Optional[str] = None,
    ):
        with self.conn:
            campos = ["nombre = ?", "cuenta_pago_id = ?"]
            params: List[Any] = [nombre, cuenta_pago_id]
            if tipo is not None:
                campos.append("tipo = ?")
                params.append(tipo)
            if archivada is not None:
                campos.append("archivada = ?")
                params.append(1 if archivada else 0)
            params.append(cuenta_id)
            self.conn.execute(
                f"UPDATE cuentas SET {', '.join(campos)} WHERE id = ?",
                params,
            )

    def borrar_cuenta(self, cuenta_id: int):
        """Elimina una cuenta y sus movimientos asociados de forma segura."""
        with self.conn:
            # Desvincular como cuenta_pago en otras cuentas
            self.conn.execute(
                "UPDATE cuentas SET cuenta_pago_id = NULL WHERE cuenta_pago_id = ?", (cuenta_id,)
            )
            # Borrar movimientos donde sea origen o destino
            self.conn.execute(
                "DELETE FROM movimientos WHERE cuenta_origen_id = ? OR cuenta_destino_id = ?",
                (cuenta_id, cuenta_id),
            )
            # Borrar de tablas dependientes
            self.conn.execute("DELETE FROM tarjetas_credito WHERE cuenta_id = ?", (cuenta_id,))
            self.conn.execute("DELETE FROM deudas WHERE cuenta_id = ?", (cuenta_id,))
            # Borrar la cuenta
            self.conn.execute("DELETE FROM cuentas WHERE id = ?", (cuenta_id,))

    def limpiar_datos_pruebas(self):
        """Elimina todos los movimientos y cuentas de demostración, manteniendo categorías y configuración."""
        with self.conn:
            self.conn.execute("DELETE FROM movimientos")
            self.conn.execute("DELETE FROM tarjetas_credito")
            self.conn.execute("DELETE FROM deudas")
            self.conn.execute("DELETE FROM cuentas")
            self.conn.execute("DELETE FROM historial_undo")
            self.conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('demo_sembrado', '1')")

    # ---------------- Tarjetas y Deudas ---------------- #
    def get_tarjeta(self, cuenta_id: int) -> Optional[TarjetaCredito]:
        cur = self.conn.execute(
            "SELECT cuenta_id, limite_centavos, dia_corte, dia_limite_pago, pago_minimo_centavos FROM tarjetas_credito WHERE cuenta_id = ?",
            (cuenta_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return TarjetaCredito(
            cuenta_id=r["cuenta_id"],
            limite_centavos=r["limite_centavos"],
            dia_corte=r["dia_corte"],
            dia_limite_pago=r["dia_limite_pago"],
            pago_minimo_centavos=r["pago_minimo_centavos"],
        )

    def guardar_tarjeta(self, tarjeta: TarjetaCredito):
        with self.conn:
            self.conn.execute(
                """INSERT INTO tarjetas_credito (cuenta_id, limite_centavos, dia_corte, dia_limite_pago, pago_minimo_centavos)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(cuenta_id) DO UPDATE SET
                   limite_centavos = excluded.limite_centavos,
                   dia_corte = excluded.dia_corte,
                   dia_limite_pago = excluded.dia_limite_pago,
                   pago_minimo_centavos = excluded.pago_minimo_centavos""",
                (
                    tarjeta.cuenta_id,
                    tarjeta.limite_centavos,
                    tarjeta.dia_corte,
                    tarjeta.dia_limite_pago,
                    tarjeta.pago_minimo_centavos,
                ),
            )

    def get_deuda(self, cuenta_id: int) -> Optional[Deuda]:
        cur = self.conn.execute(
            "SELECT cuenta_id, monto_original_centavos, cuota_centavos, dia_pago, fecha_inicio FROM deudas WHERE cuenta_id = ?",
            (cuenta_id,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return Deuda(
            cuenta_id=r["cuenta_id"],
            monto_original_centavos=r["monto_original_centavos"],
            cuota_centavos=r["cuota_centavos"],
            dia_pago=r["dia_pago"],
            fecha_inicio=r["fecha_inicio"] or "",
        )

    def guardar_deuda(self, deuda: Deuda):
        with self.conn:
            self.conn.execute(
                """INSERT INTO deudas (cuenta_id, monto_original_centavos, cuota_centavos, dia_pago, fecha_inicio)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(cuenta_id) DO UPDATE SET
                   monto_original_centavos = excluded.monto_original_centavos,
                   cuota_centavos = excluded.cuota_centavos,
                   dia_pago = excluded.dia_pago,
                   fecha_inicio = excluded.fecha_inicio""",
                (
                    deuda.cuenta_id,
                    deuda.monto_original_centavos,
                    deuda.cuota_centavos,
                    deuda.dia_pago,
                    deuda.fecha_inicio,
                ),
            )

    # ---------------- Categorías ---------------- #
    def get_categorias(self, solo_activas: bool = True) -> List[Categoria]:
        sql = "SELECT id, nombre, es_hormiga, activo FROM categorias"
        if solo_activas:
            sql += " WHERE activo = 1"
        sql += " ORDER BY id ASC"
        cur = self.conn.execute(sql)
        return [
            Categoria(
                id=r["id"],
                nombre=r["nombre"],
                es_hormiga=bool(r["es_hormiga"]),
                activo=bool(r["activo"]),
            )
            for r in cur.fetchall()
        ]

    def get_or_create_categoria(self, nombre: str, es_hormiga: bool = False) -> int:
        cur = self.conn.execute("SELECT id FROM categorias WHERE nombre = ?", (nombre,))
        row = cur.fetchone()
        if row:
            return row["id"]
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO categorias (nombre, es_hormiga, activo) VALUES (?, ?, 1)",
                (nombre, 1 if es_hormiga else 0),
            )
            return cur.lastrowid

    def toggle_categoria_hormiga(self, categoria_id: int):
        with self.conn:
            self.conn.execute(
                "UPDATE categorias SET es_hormiga = CASE WHEN es_hormiga = 1 THEN 0 ELSE 1 END WHERE id = ?",
                (categoria_id,),
            )

    def guardar_categoria(self, nombre: str, es_hormiga: bool = False) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO categorias (nombre, es_hormiga, activo) VALUES (?, ?, 1)",
                (nombre, 1 if es_hormiga else 0),
            )
            return cur.lastrowid

    # ---------------- Movimientos ---------------- #
    def get_movimientos(
        self,
        cuenta_id: Optional[int] = None,
        categoria_id: Optional[int] = None,
        fecha_desde: Optional[str] = None,
        fecha_hasta: Optional[str] = None,
        tipo: Optional[str] = None,
        texto_busqueda: Optional[str] = None,
        limite: Optional[int] = None,
    ) -> List[Movimiento]:
        sql = """
            SELECT m.id, m.fecha, m.tipo, m.monto_centavos, m.cuenta_origen_id, m.cuenta_destino_id,
                   m.categoria_id, m.nota, m.created_at,
                   co.nombre AS cuenta_origen_nombre,
                   cd.nombre AS cuenta_destino_nombre,
                   cat.nombre AS categoria_nombre
            FROM movimientos m
            LEFT JOIN cuentas co ON m.cuenta_origen_id = co.id
            LEFT JOIN cuentas cd ON m.cuenta_destino_id = cd.id
            LEFT JOIN categorias cat ON m.categoria_id = cat.id
            WHERE 1=1
        """
        params: List[Any] = []
        if cuenta_id:
            sql += " AND (m.cuenta_origen_id = ? OR m.cuenta_destino_id = ?)"
            params.extend([cuenta_id, cuenta_id])
        if categoria_id:
            sql += " AND m.categoria_id = ?"
            params.append(categoria_id)
        if fecha_desde:
            sql += " AND m.fecha >= ?"
            params.append(fecha_desde)
        if fecha_hasta:
            sql += " AND m.fecha <= ?"
            params.append(fecha_hasta)
        if tipo:
            sql += " AND m.tipo = ?"
            params.append(tipo)
        if texto_busqueda:
            sql += " AND (m.nota LIKE ? OR cat.nombre LIKE ? OR co.nombre LIKE ? OR cd.nombre LIKE ?)"
            like = f"%{texto_busqueda}%"
            params.extend([like, like, like, like])

        sql += " ORDER BY m.fecha DESC, m.id DESC"
        if limite:
            sql += f" LIMIT {int(limite)}"

        cur = self.conn.execute(sql, params)
        return [
            Movimiento(
                id=r["id"],
                fecha=r["fecha"],
                tipo=r["tipo"],
                monto_centavos=r["monto_centavos"],
                cuenta_origen_id=r["cuenta_origen_id"],
                cuenta_destino_id=r["cuenta_destino_id"],
                categoria_id=r["categoria_id"],
                nota=r["nota"] or "",
                created_at=r["created_at"],
                cuenta_origen_nombre=r["cuenta_origen_nombre"] or "",
                cuenta_destino_nombre=r["cuenta_destino_nombre"] or "",
                categoria_nombre=r["categoria_nombre"] or "",
            )
            for r in cur.fetchall()
        ]

    def get_movimiento(self, movimiento_id: int) -> Optional[Movimiento]:
        sql = """
            SELECT m.id, m.fecha, m.tipo, m.monto_centavos, m.cuenta_origen_id, m.cuenta_destino_id,
                   m.categoria_id, m.nota, m.created_at,
                   co.nombre AS cuenta_origen_nombre,
                   cd.nombre AS cuenta_destino_nombre,
                   cat.nombre AS categoria_nombre
            FROM movimientos m
            LEFT JOIN cuentas co ON m.cuenta_origen_id = co.id
            LEFT JOIN cuentas cd ON m.cuenta_destino_id = cd.id
            LEFT JOIN categorias cat ON m.categoria_id = cat.id
            WHERE m.id = ?
        """
        cur = self.conn.execute(sql, (movimiento_id,))
        r = cur.fetchone()
        if not r:
            return None
        return Movimiento(
            id=r["id"],
            fecha=r["fecha"],
            tipo=r["tipo"],
            monto_centavos=r["monto_centavos"],
            cuenta_origen_id=r["cuenta_origen_id"],
            cuenta_destino_id=r["cuenta_destino_id"],
            categoria_id=r["categoria_id"],
            nota=r["nota"] or "",
            created_at=r["created_at"],
            cuenta_origen_nombre=r["cuenta_origen_nombre"] or "",
            cuenta_destino_nombre=r["cuenta_destino_nombre"] or "",
            categoria_nombre=r["categoria_nombre"] or "",
        )

    def agregar_movimiento(self, mov: Movimiento) -> int:
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO movimientos (fecha, tipo, monto_centavos, cuenta_origen_id, cuenta_destino_id, categoria_id, nota, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mov.fecha,
                    mov.tipo,
                    mov.monto_centavos,
                    mov.cuenta_origen_id,
                    mov.cuenta_destino_id,
                    mov.categoria_id,
                    mov.nota,
                    ahora,
                ),
            )
            mov_id = cur.lastrowid
            # Registrar en historial undo
            self._registrar_undo("crear", {"id": mov_id})
            return mov_id

    def actualizar_movimiento(self, mov: Movimiento):
        # Guardar estado previo para undo
        previo = self.get_movimiento(mov.id)
        if not previo:
            return
        with self.conn:
            self.conn.execute(
                """UPDATE movimientos SET
                   fecha = ?, tipo = ?, monto_centavos = ?, cuenta_origen_id = ?,
                   cuenta_destino_id = ?, categoria_id = ?, nota = ?
                   WHERE id = ?""",
                (
                    mov.fecha,
                    mov.tipo,
                    mov.monto_centavos,
                    mov.cuenta_origen_id,
                    mov.cuenta_destino_id,
                    mov.categoria_id,
                    mov.nota,
                    mov.id,
                ),
            )
            self._registrar_undo(
                "editar",
                {
                    "id": previo.id,
                    "fecha": previo.fecha,
                    "tipo": previo.tipo,
                    "monto_centavos": previo.monto_centavos,
                    "cuenta_origen_id": previo.cuenta_origen_id,
                    "cuenta_destino_id": previo.cuenta_destino_id,
                    "categoria_id": previo.categoria_id,
                    "nota": previo.nota,
                },
            )

    def borrar_movimiento(self, movimiento_id: int):
        previo = self.get_movimiento(movimiento_id)
        if not previo:
            return
        with self.conn:
            self.conn.execute("DELETE FROM movimientos WHERE id = ?", (movimiento_id,))
            self._registrar_undo(
                "borrar",
                {
                    "id": previo.id,
                    "fecha": previo.fecha,
                    "tipo": previo.tipo,
                    "monto_centavos": previo.monto_centavos,
                    "cuenta_origen_id": previo.cuenta_origen_id,
                    "cuenta_destino_id": previo.cuenta_destino_id,
                    "categoria_id": previo.categoria_id,
                    "nota": previo.nota,
                    "created_at": previo.created_at,
                },
            )

    # ---------------- Undo ---------------- #
    def _registrar_undo(self, operacion: str, datos: Dict[str, Any]):
        import json

        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO historial_undo (operacion, datos_json, created_at) VALUES (?, ?, ?)",
            (operacion, json.dumps(datos), ahora),
        )

    def deshacer_ultima_accion(self) -> Optional[str]:
        """Revierte la última acción y devuelve una descripción legible o None."""
        import json

        cur = self.conn.execute(
            "SELECT id, operacion, datos_json FROM historial_undo ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None

        undo_id = row["id"]
        operacion = row["operacion"]
        datos = json.loads(row["datos_json"])

        with self.conn:
            if operacion == "crear":
                # La acción fue crear un movimiento; para deshacerlo lo borramos
                self.conn.execute("DELETE FROM movimientos WHERE id = ?", (datos["id"],))
                desc = f"Se canceló la creación del movimiento #{datos['id']}"
            elif operacion == "borrar":
                # La acción fue borrar; para deshacerlo lo restauramos
                self.conn.execute(
                    """INSERT INTO movimientos (id, fecha, tipo, monto_centavos, cuenta_origen_id, cuenta_destino_id, categoria_id, nota, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        datos["id"],
                        datos["fecha"],
                        datos["tipo"],
                        datos["monto_centavos"],
                        datos.get("cuenta_origen_id"),
                        datos.get("cuenta_destino_id"),
                        datos.get("categoria_id"),
                        datos.get("nota", ""),
                        datos.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    ),
                )
                desc = f"Se restauró el movimiento #{datos['id']}"
            elif operacion == "editar":
                # La acción fue editar; restauramos valores previos
                self.conn.execute(
                    """UPDATE movimientos SET
                       fecha = ?, tipo = ?, monto_centavos = ?, cuenta_origen_id = ?,
                       cuenta_destino_id = ?, categoria_id = ?, nota = ?
                       WHERE id = ?""",
                    (
                        datos["fecha"],
                        datos["tipo"],
                        datos["monto_centavos"],
                        datos.get("cuenta_origen_id"),
                        datos.get("cuenta_destino_id"),
                        datos.get("categoria_id"),
                        datos.get("nota", ""),
                        datos["id"],
                    ),
                )
                desc = f"Se restauró el estado anterior del movimiento #{datos['id']}"
            else:
                desc = None

            # Eliminamos el registro de undo utilizado
            self.conn.execute("DELETE FROM historial_undo WHERE id = ?", (undo_id,))

        return desc

    # ---------------- Respaldos ---------------- #
    def realizar_respaldo(
        self, backups_dir: str = DEFAULT_BACKUPS_DIR, max_backups: Optional[int] = None
    ) -> Optional[str]:
        """Crea un respaldo de la base de datos con rotación automática."""
        if self.db_path == ":memory:" or not os.path.exists(self.db_path):
            return None

        if max_backups is None:
            max_backups = self.get_config().backups_rotacion

        os.makedirs(backups_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"finanzas_{timestamp}.db"
        dest_path = os.path.join(backups_dir, backup_filename)

        # Copia atómica / segura usando backup API de SQLite
        try:
            bck = sqlite3.connect(dest_path)
            with bck:
                self.conn.backup(bck)
            bck.close()
        except Exception:
            shutil.copy2(self.db_path, dest_path)

        # Rotación de respaldos: conservar los últimos max_backups
        self._rotar_respaldos(backups_dir, max_backups)
        return dest_path

    @staticmethod
    def _rotar_respaldos(backups_dir: str, max_backups: int):
        if not os.path.isdir(backups_dir) or max_backups <= 0:
            return
        archivos = [
            os.path.join(backups_dir, f)
            for f in os.listdir(backups_dir)
            if f.startswith("finanzas_") and f.endswith(".db")
        ]
        archivos.sort(key=os.path.getmtime)
        while len(archivos) > max_backups:
            antiguo = archivos.pop(0)
            try:
                os.remove(antiguo)
            except OSError:
                pass

    @staticmethod
    def listar_respaldos(backups_dir: str = DEFAULT_BACKUPS_DIR) -> List[Dict[str, Any]]:
        if not os.path.isdir(backups_dir):
            return []
        archivos = [
            f for f in os.listdir(backups_dir) if f.startswith("finanzas_") and f.endswith(".db")
        ]
        archivos.sort(reverse=True)
        res = []
        for f in archivos:
            ruta = os.path.join(backups_dir, f)
            stat = os.stat(ruta)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            res.append(
                {
                    "nombre": f,
                    "ruta": ruta,
                    "fecha": mtime,
                    "tamano_bytes": stat.st_size,
                }
            )
        return res
