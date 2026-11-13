# GASTLI
## Sistema de Finanzas Personales en Terminal

Un sistema de finanzas personales modular y de alto rendimiento para terminal (Linux, macOS y Windows; compatible con Bash, Fish y Zsh). Construido **exclusivamente con la biblioteca estándar de Python 3** (`curses`, `sqlite3`, `zipfile`), sin dependencias externas.

---

## Concepto Central

1. **Todo es una cuenta y todo movimiento transfiere dinero**:
   - **4 tipos de cuentas**:
     - *Activos* (dinero que tienes): `debito` y `efectivo`.
     - *Pasivos* (dinero que debes): `credito` (tarjetas de crédito) y `deuda` (préstamos personales).
   - **4 tipos de movimientos**:
     - `gasto`: sale de un activo hacia una categoría.
     - `ingreso`: entra a un activo.
     - `transferencia`: pasa de un activo a otro (ej. de Ahorro a Cartera diaria).
     - `pago`: sale de un activo y reduce un pasivo (ej. pagar la tarjeta Nu desde BBVA).
     - `ajuste`: movimiento explícito para cuadrar saldos o registrar saldos iniciales.
2. **Saldos calculados dinámicamente**: Los saldos nunca se guardan fijos; se calculan en tiempo real a partir de los movimientos. Al editar o borrar un movimiento, todos los saldos se recalculan de forma coherente.
3. **Montos en centavos enteros**: Sin errores de redondeo de punto flotante.
4. **Deshacer (`u`)**: Reversión instantánea de la última operación realizada.
5. **Cero emojis**: Interfaz sobria, bordes redondeados (`╭──╮`, `│  │`, `╰──╯`), gráficas con caracteres de bloque Unicode (` ▂▃▄▅▆▇█`) y paleta con degradado elegante.
6. **Exportación real a Excel (.xlsx)**: Generador nativo escrito mediante `zipfile` y XML puro, con 6 hojas completas y tipos numéricos reales.

---

## Instalación

GASTLI se instala como cualquier aplicación de terminal y se abre desde cualquier carpeta con un solo comando: `gastli`.

** PROXIMAMENTE Arch Linux (AUR):**
```bash
yay -S gastli
# o
paru -S gastli
```

**Cualquier sistema con pipx (recomendado):**
```bash
pipx install git+https://github.com/LeonardoVenus/gastli
```

**Con pip:**
```bash
pip install --user git+https://github.com/LeonardoVenus/gastli
```

**Script de instalación:**
```bash
curl -fsSL https://raw.githubusercontent.com/LeonardoVenus/gastli/main/install.sh | sh
```

Requisitos: Python 3.8 o superior. En Linux y macOS no necesita dependencias adicionales; en Windows instala `windows-curses` automáticamente.

## Uso

```bash
# Abrir la interfaz de terminal (TUI)
gastli

# O con Python
python3 -m gastli
```

### Modo no interactivo (CLI para scripts)
Puedes registrar operaciones o consultar saldos directamente sin abrir la TUI:

```bash
# Ver saldos actuales y widget 'Por depositar'
gastli saldo

# Registrar un gasto rápido
gastli gasto 45 "tacos al pastor"
gastli g 120 "gasolina" --cuenta "BBVA"

# Registrar un ingreso
gastli ingreso 15000 "quincena" --cuenta "BBVA"

# Transferir entre cuentas
gastli transfer 500 "BBVA" "Cartera"

# Registrar un pago a tarjeta o deuda
gastli pago 1200 "Nu" --desde "BBVA"

# Exportar datos a Excel (.xlsx) o CSV
gastli export --formato xlsx --salida ~/mi_reporte.xlsx
gastli export --formato csv

# Crear un respaldo inmediato
gastli backup
```

---

## Ventanas y Navegación (TUI)

Cambia de ventana presionando los números **`1` a `7`** o haciendo **clic con el ratón** en la barra superior:

1. **`1 Resumen`**: Saldos de activos, deuda total, gasto del mes, próximos vencimientos y el widget **"Por depositar"** (conmutable entre 7, 15 y 30 días con la tecla `h`).
2. **`2 Movim.`**: Histórico completo de movimientos con filtros en vivo por fecha (`m`), búsqueda por texto (`/`), agregar (`n`), editar (`e` o doble clic) y borrar (`d`).
3. **`3 Cuentas`**: Cuentas de débito y efectivo, saldos actuales, total acumulado y botones para depositar (`i`), transferir (`t`), ajustar saldo (`a`), crear cuenta (`c`) y archivar (`x`).
4. **`4 Deudas`**: Tarjetas de crédito (límite, disponible, barra de uso `[████░░░░░░]`, días al corte, días al pago, pago sin intereses) y préstamos. Botón **Pagar** (`p`) para amortizar pasivos desde débito.
5. **`5 Efectivo`**: Vista diaria con tres cifras destacadas (*Llevé*, *Gasté*, *Sobra*), acciones rápidas *Llevar hoy* (`l`) y *Devolver sobrante* (`s`), promedio de los últimos 7 días y desglose diario.
6. **`6 Hormiga`**: Métricas de gastos hormiga del mes, porcentaje respecto al gasto total, proyección anual, top 5 conceptos y minigráfica diaria con bloques Unicode.
7. **`7 Ajustes`**: Catálogo de categorías (conmutar marca hormiga con `Espacio`), moneda configurable, horizonte por defecto, botón de exportar y gestión de respaldos.

---

## Atajos de Teclado y Ratón

| Atajo | Acción |
|---|---|
| `1` - `7` | Cambiar entre las 7 ventanas |
| `n` | Formulario rápido de nuevo movimiento |
| `e` / `Enter` | Editar movimiento o elemento seleccionado |
| `d` | Borrar elemento con diálogo de confirmación |
| `/` | Búsqueda y filtrado por texto en movimientos |
| `u` | Deshacer la última acción (creación, edición o borrado) |
| `:` | Abrir barra de comandos (:g, :t, :p, :export, :backup, :q) |
| `?` | Ventana de ayuda y atajos |
| `Tab` / `Shift-Tab` | Cambiar entre paneles o campos de formularios |
| `q` | Salir del programa |
| **Ratón** | Clic en pestañas, botones y filas; rueda para scroll vertical; doble clic para editar |

---

## Datos y respaldos

Tus datos viven fuera del código, en un directorio propio del usuario:

| Sistema | Ubicación |
|---|---|
| Linux | `~/.local/share/gastli` (respeta `XDG_DATA_HOME`) |
| macOS | `~/Library/Application Support/gastli` |
| Windows | `%APPDATA%\gastli` |

Puedes cambiarla con la variable de entorno `GASTLI_HOME`:

```bash
GASTLI_HOME=~/Dropbox/gastli gastli
```

Dentro de esa carpeta:

- `finanzas.db`: la base de datos SQLite.
- `backups/`: respaldo automático cada vez que abres GASTLI, conservando los últimos N (rotación configurable en Ajustes).
- `exports/`: archivos generados por `gastli export` y por las opciones de exportar.

Para migrar a otra máquina, copia esa carpeta al mismo lugar en el equipo nuevo.

## Licencia

MIT. Uso libre; consulta el archivo `LICENSE`.
