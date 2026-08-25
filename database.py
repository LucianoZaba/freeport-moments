# ===================================================================
# FREEPORT MOMENTS - DATABASE.PY
# Manejo de SQLite y persistencia de archivos.
#
# Decisiones pensadas para un evento de una noche con muchos invitados
# subiendo al mismo tiempo desde el celular:
#
#   - journal_mode = WAL: permite que se pueda leer la galeria del
#     admin mientras un invitado esta subiendo un archivo, sin
#     bloquear toda la base.
#   - synchronous = FULL: prioriza que los datos queden realmente
#     escritos en disco antes de responder, para minimizar perdida
#     de informacion ante un corte de luz o apagado inesperado del PC.
#   - busy_timeout: si dos escrituras chocan, SQLite espera en vez de
#     tirar error inmediatamente ("database is locked").
#   - reintentos con backoff en las operaciones de escritura, por si
#     el busy_timeout no alcanza bajo carga muy alta.
#   - contador atomico para la numeracion de videos (evita que dos
#     videos subidos en simultaneo terminen con el mismo numero).
#   - respaldo periodico de la base a /backups (ver tarea en app.py).
# ===================================================================
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import DATABASE_CONFIG, UPLOAD_DIR, logger

DB_PATH: Path = DATABASE_CONFIG["path"]

_MAX_REINTENTOS = 5
_ESPERA_BASE_SEGUNDOS = 0.15


@contextmanager
def conectar():
    """
    Context manager que entrega una conexion SQLite ya configurada
    para concurrencia razonable, y garantiza que se cierre siempre
    (incluso si hay una excepcion en el medio).
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
    finally:
        conn.close()


def _ejecutar_con_reintentos(func):
    """
    Ejecuta una operacion de base de datos reintentando ante errores
    transitorios de bloqueo ("database is locked"), tipicos cuando
    hay muchas escrituras simultaneas (varios invitados subiendo a
    la vez). Si despues de varios intentos sigue fallando, se
    propaga el error para que la capa superior (app.py) responda
    algo razonable al usuario.
    """
    ultimo_error = None
    for intento in range(_MAX_REINTENTOS):
        try:
            return func()
        except sqlite3.OperationalError as e:
            ultimo_error = e
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                espera = _ESPERA_BASE_SEGUNDOS * (2 ** intento)
                logger.warning(f"BD ocupada, reintentando en {espera:.2f}s (intento {intento + 1})")
                time.sleep(espera)
                continue
            raise
    logger.error(f"Operacion de BD fallo tras {_MAX_REINTENTOS} intentos: {ultimo_error}")
    raise ultimo_error


def inicializar_bd():
    """Crea las tablas necesarias y configura los PRAGMA de rendimiento/seguridad."""

    def _init():
        with conectar() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = FULL;")
            conn.execute("PRAGMA busy_timeout = 30000;")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS archivos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_original TEXT,
                    nombre_guardado TEXT UNIQUE NOT NULL,
                    tipo TEXT,
                    extension TEXT,
                    tamano_bytes INTEGER DEFAULT 0,
                    estado TEXT NOT NULL DEFAULT 'pendientes',
                    ruta TEXT,
                    url TEXT,
                    metadata TEXT,
                    ip_origen TEXT,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archivos_estado ON archivos(estado)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archivos_fecha ON archivos(fecha)")

            # Contador atomico de videos, para nombrarlos video_1, video_2, ...
            # sin condiciones de carrera cuando llegan varios al mismo tiempo.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contadores (
                    nombre TEXT PRIMARY KEY,
                    valor INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO contadores (nombre, valor) VALUES ('video', 0)"
            )

            # Sesiones de administrador persistidas en disco: si el server
            # se reinicia (corte de luz, actualizacion, etc.) la sesion
            # del admin no se pierde mientras no haya expirado.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sesiones (
                    token TEXT PRIMARY KEY,
                    usuario TEXT NOT NULL,
                    creada TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expira TIMESTAMP NOT NULL
                )
            """)

            # Intentos de login fallidos, para el bloqueo temporal anti
            # fuerza bruta (por IP).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS intentos_login (
                    ip TEXT PRIMARY KEY,
                    intentos INTEGER NOT NULL DEFAULT 0,
                    bloqueado_hasta TIMESTAMP
                )
            """)

    _ejecutar_con_reintentos(_init)
    logger.info(f"Base de datos inicializada correctamente en {DB_PATH}")


# ===================================================================
# ARCHIVOS
# ===================================================================
def guardar_archivo(info: dict):
    """Guarda o actualiza el registro de un archivo subido."""

    def _guardar():
        with conectar() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO archivos
                (nombre_original, nombre_guardado, tipo, extension, tamano_bytes,
                 estado, ruta, url, metadata, ip_origen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                info.get("nombre_original"),
                info.get("nombre_guardado"),
                info.get("tipo"),
                info.get("extension"),
                info.get("tamano_bytes", 0),
                info.get("estado", "pendientes"),
                info.get("ruta"),
                info.get("url"),
                str(info.get("metadata", {})),
                info.get("ip_origen", ""),
            ))

    _ejecutar_con_reintentos(_guardar)


def listar_archivos(estado: str, limite: int = 500, offset: int = 0):
    """Devuelve una lista de archivos filtrados por estado, mas recientes primero."""

    def _listar():
        with conectar() as conn:
            cursor = conn.execute(
                """SELECT *, nombre_guardado AS nombre FROM archivos
                   WHERE estado = ? ORDER BY fecha DESC LIMIT ? OFFSET ?""",
                (estado, limite, offset),
            )
            return [dict(fila) for fila in cursor.fetchall()]

    return _ejecutar_con_reintentos(_listar)


def obtener_archivo_por_nombre(nombre_guardado: str):
    def _obtener():
        with conectar() as conn:
            cursor = conn.execute(
                "SELECT *, nombre_guardado AS nombre FROM archivos WHERE nombre_guardado = ?",
                (nombre_guardado,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None

    return _ejecutar_con_reintentos(_obtener)


def actualizar_estado_archivo(nombre_guardado: str, nuevo_estado: str):
    """Actualiza el estado, la ruta fisica y la URL de un archivo especifico."""

    def _actualizar():
        nueva_ruta = str(UPLOAD_DIR / nuevo_estado / nombre_guardado)
        nueva_url = f"/uploads/{nuevo_estado}/{nombre_guardado}"
        with conectar() as conn:
            conn.execute("""
                UPDATE archivos
                SET estado = ?, ruta = ?, url = ?
                WHERE nombre_guardado = ?
            """, (nuevo_estado, nueva_ruta, nueva_url, nombre_guardado))

    _ejecutar_con_reintentos(_actualizar)


def eliminar_registro_archivo(nombre_guardado: str):
    def _eliminar():
        with conectar() as conn:
            conn.execute("DELETE FROM archivos WHERE nombre_guardado = ?", (nombre_guardado,))

    _ejecutar_con_reintentos(_eliminar)


def siguiente_numero_video() -> int:
    """
    Incrementa y devuelve el contador de videos de forma atomica.
    Evita colisiones de nombre cuando dos videos se terminan de subir
    en el mismo instante.
    """

    def _incrementar():
        with conectar() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "UPDATE contadores SET valor = valor + 1 WHERE nombre = 'video'"
                )
                cursor = conn.execute(
                    "SELECT valor FROM contadores WHERE nombre = 'video'"
                )
                valor = cursor.fetchone()[0]
                conn.execute("COMMIT")
                return valor
            except Exception:
                conn.execute("ROLLBACK")
                raise

    return _ejecutar_con_reintentos(_incrementar)


def obtener_estadisticas():
    """Calcula los contadores, tipos de archivos y el espacio total utilizado."""

    def _stats():
        with conectar() as conn:
            conteo = {
                row["estado"]: row["cnt"]
                for row in conn.execute(
                    "SELECT estado, COUNT(*) as cnt FROM archivos GROUP BY estado"
                ).fetchall()
            }

            pendientes = conteo.get("pendientes", 0)
            aprobadas = conteo.get("aprobadas", 0)
            rechazadas = conteo.get("rechazadas", 0)
            descargadas = conteo.get("descargas", 0)

            tipos_conteo = {
                row["tipo"]: row["cnt"]
                for row in conn.execute(
                    "SELECT tipo, COUNT(*) as cnt FROM archivos GROUP BY tipo"
                ).fetchall()
            }
            fotos = sum(v for k, v in tipos_conteo.items() if k and "image" in k)
            videos = sum(v for k, v in tipos_conteo.items() if k and "video" in k)

            resultado_espacio = conn.execute(
                "SELECT SUM(tamano_bytes) as total FROM archivos"
            ).fetchone()
            espacio_bytes = resultado_espacio["total"] if resultado_espacio and resultado_espacio["total"] else 0

            return pendientes, aprobadas, rechazadas, descargadas, fotos, videos, espacio_bytes

    pendientes, aprobadas, rechazadas, descargadas, fotos, videos, espacio_bytes = _ejecutar_con_reintentos(_stats)

    limite_bytes = 5 * 1024 * 1024 * 1024  # barra de progreso referencial de 5 GB
    porcentaje_espacio = round((espacio_bytes / limite_bytes) * 100, 1) if limite_bytes > 0 else 0.0

    def formatear_tamano(b):
        if b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB"
        else:
            return f"{b / (1024 * 1024 * 1024):.2f} GB"

    return {
        "pendientes": pendientes,
        "aprobadas": aprobadas,
        "rechazadas": rechazadas,
        "descargadas": descargadas,
        "fotos": fotos,
        "videos": videos,
        "espacio": {
            "bytes": espacio_bytes,
            "texto": f"{formatear_tamano(espacio_bytes)} / 5.0 GB",
            "porcentaje": min(porcentaje_espacio, 100.0),
        },
    }


def borrar_todo_evento():
    """Limpia la base de datos y elimina fisicamente todos los archivos multimedia."""

    def _borrar():
        with conectar() as conn:
            conn.execute("DELETE FROM archivos")
            conn.execute("UPDATE contadores SET valor = 0 WHERE nombre = 'video'")
            conn.execute("DELETE FROM sesiones")
            conn.execute("DELETE FROM intentos_login")

    _ejecutar_con_reintentos(_borrar)

    for carpeta in ["pendientes", "aprobadas", "rechazadas", "descargas", "temp", "thumbnails"]:
        carpeta_path = UPLOAD_DIR / carpeta
        if not carpeta_path.exists():
            continue
        for archivo in carpeta_path.iterdir():
            if archivo.is_file():
                try:
                    archivo.unlink()
                except OSError as e:
                    logger.warning(f"No se pudo eliminar el archivo fisico {archivo.name}: {e}")

    logger.info("Evento reiniciado: base de datos y archivos fisicos eliminados.")


def contar_videos() -> int:
    def _contar():
        with conectar() as conn:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM archivos WHERE tipo LIKE 'video/%'")
            return cursor.fetchone()["cnt"]

    return _ejecutar_con_reintentos(_contar)


# ===================================================================
# SESIONES DE ADMINISTRADOR (persistidas para sobrevivir reinicios)
# ===================================================================
def crear_sesion(token: str, usuario: str, expira: datetime):
    def _crear():
        with conectar() as conn:
            conn.execute(
                "INSERT INTO sesiones (token, usuario, expira) VALUES (?, ?, ?)",
                (token, usuario, expira.isoformat()),
            )

    _ejecutar_con_reintentos(_crear)


def obtener_sesion(token: str):
    def _obtener():
        with conectar() as conn:
            cursor = conn.execute("SELECT * FROM sesiones WHERE token = ?", (token,))
            fila = cursor.fetchone()
            return dict(fila) if fila else None

    return _ejecutar_con_reintentos(_obtener)


def eliminar_sesion(token: str):
    def _eliminar():
        with conectar() as conn:
            conn.execute("DELETE FROM sesiones WHERE token = ?", (token,))

    _ejecutar_con_reintentos(_eliminar)


def limpiar_sesiones_expiradas():
    def _limpiar():
        with conectar() as conn:
            conn.execute("DELETE FROM sesiones WHERE expira < ?", (datetime.now().isoformat(),))

    _ejecutar_con_reintentos(_limpiar)


# ===================================================================
# PROTECCION ANTI FUERZA BRUTA EN LOGIN
# ===================================================================
def registrar_intento_fallido(ip: str, max_intentos: int, bloqueo_minutos: int) -> int:
    """Suma un intento fallido para la IP y bloquea temporalmente si supera el maximo."""
    from datetime import timedelta

    def _registrar():
        with conectar() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute("SELECT intentos FROM intentos_login WHERE ip = ?", (ip,))
                fila = cursor.fetchone()
                intentos_actuales = (fila["intentos"] if fila else 0) + 1

                bloqueado_hasta = None
                if intentos_actuales >= max_intentos:
                    bloqueado_hasta = (datetime.now() + timedelta(minutes=bloqueo_minutos)).isoformat()

                conn.execute(
                    """INSERT INTO intentos_login (ip, intentos, bloqueado_hasta)
                       VALUES (?, ?, ?)
                       ON CONFLICT(ip) DO UPDATE SET intentos = ?, bloqueado_hasta = ?""",
                    (ip, intentos_actuales, bloqueado_hasta, intentos_actuales, bloqueado_hasta),
                )
                conn.execute("COMMIT")
                return intentos_actuales
            except Exception:
                conn.execute("ROLLBACK")
                raise

    return _ejecutar_con_reintentos(_registrar)


def resetear_intentos_fallidos(ip: str):
    def _resetear():
        with conectar() as conn:
            conn.execute("DELETE FROM intentos_login WHERE ip = ?", (ip,))

    _ejecutar_con_reintentos(_resetear)


def ip_esta_bloqueada(ip: str) -> tuple[bool, int]:
    """Devuelve (bloqueada, segundos_restantes)."""

    def _consultar():
        with conectar() as conn:
            cursor = conn.execute(
                "SELECT bloqueado_hasta FROM intentos_login WHERE ip = ?", (ip,)
            )
            fila = cursor.fetchone()
            if not fila or not fila["bloqueado_hasta"]:
                return False, 0
            bloqueado_hasta = datetime.fromisoformat(fila["bloqueado_hasta"])
            restante = (bloqueado_hasta - datetime.now()).total_seconds()
            if restante <= 0:
                return False, 0
            return True, int(restante)

    return _ejecutar_con_reintentos(_consultar)


# ===================================================================
# RESPALDO AUTOMATICO
# ===================================================================
def respaldar_base_datos():
    """
    Copia la base de datos actual a /backups con timestamp, usando la
    API de respaldo online de SQLite (segura de usar con la BD en uso,
    a diferencia de copiar el archivo .db directamente).
    Tambien elimina respaldos viejos para no llenar el disco.
    """
    if not DATABASE_CONFIG["backup_enabled"]:
        return

    destino_dir: Path = DATABASE_CONFIG["backup_dir"]
    destino_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = destino_dir / f"freeport_{timestamp}.db"

    try:
        with conectar() as origen:
            destino_conn = sqlite3.connect(str(destino))
            with destino_conn:
                origen.backup(destino_conn)
            destino_conn.close()
        logger.info(f"Respaldo de base de datos creado: {destino.name}")
    except (sqlite3.Error, OSError) as e:
        logger.error(f"No se pudo crear el respaldo de la base de datos: {e}")
        return

    # Limpieza de respaldos antiguos, se conservan los N mas recientes
    try:
        respaldos = sorted(destino_dir.glob("freeport_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        conservar = DATABASE_CONFIG["backups_a_conservar"]
        for viejo in respaldos[conservar:]:
            viejo.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"No se pudieron limpiar respaldos antiguos: {e}")
