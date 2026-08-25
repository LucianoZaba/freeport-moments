# ===================================================================
# FREEPORT MOMENTS - CONFIG.PY - ACTUALIZADO
# Ahora el nombre del evento se guarda en data/evento.json y se puede
# cambiar desde el panel admin sin tocar .env ni reiniciar.
# ===================================================================
import json
import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ASSETS_DIR = BASE_DIR / "assets"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
EVENTO_CONFIG_FILE = DATA_DIR / "evento.json"

CARPETAS_REQUERIDAS = [
    UPLOAD_DIR / "pendientes",
    UPLOAD_DIR / "aprobadas",
    UPLOAD_DIR / "rechazadas",
    UPLOAD_DIR / "descargas",
    UPLOAD_DIR / "temp",
    UPLOAD_DIR / "thumbnails",
    ASSETS_DIR,
    LOGS_DIR,
    DATA_DIR,
    BASE_DIR / "backups",
]

for carpeta in CARPETAS_REQUERIDAS:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"[FATAL] No se pudo crear la carpeta requerida '{carpeta}': {e}")

def _configurar_logging() -> logging.Logger:
    logger = logging.getLogger("freeport")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    formato = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler_consola = logging.StreamHandler()
    handler_consola.setFormatter(formato)
    logger.addHandler(handler_consola)
    try:
        handler_archivo = RotatingFileHandler(
            LOGS_DIR / "freeport.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler_archivo.setFormatter(formato)
        logger.addHandler(handler_archivo)
    except OSError:
        logger.warning("No se pudo crear el archivo de log en disco")
    return logger

logger = _configurar_logging()

def _obtener_o_crear_secret_key() -> str:
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    archivo_key = DATA_DIR / ".secret_key"
    if archivo_key.exists():
        try:
            return archivo_key.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    nueva_key = secrets.token_hex(32)
    try:
        archivo_key.write_text(nueva_key, encoding="utf-8")
        try:
            os.chmod(archivo_key, 0o600)
        except OSError:
            pass
    except OSError:
        logger.warning("No se pudo persistir la SECRET_KEY")
    return nueva_key

SECRET_KEY = _obtener_o_crear_secret_key()

# ===================================================================
# EVENTO - AHORA DINAMICO Y PERSISTENTE
# ===================================================================
def _cargar_evento_config() -> dict:
    """Carga config desde evento.json si existe, sino desde ENV."""
    config_default = {
        "nombre": os.getenv("EVENTO_NOMBRE", "Evento de la Noche"),
        "descripcion": os.getenv("EVENTO_DESCRIPCION", "Evento sin configurar"),
        "lugar": os.getenv("EVENTO_LUGAR", ""),
        # fecha y hora ya no se usan del ENV, se generan en vivo
    }
    if EVENTO_CONFIG_FILE.exists():
        try:
            data = json.loads(EVENTO_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("nombre"):
                # merge para mantener compatibilidad
                config_default.update({k: v for k, v in data.items() if v})
                return config_default
        except Exception as e:
            logger.warning(f"No se pudo leer {EVENTO_CONFIG_FILE}: {e}")
    return config_default

def guardar_evento_config(nueva_data: dict) -> dict:
    """Guarda el config en disco y actualiza variable global."""
    global EVENTO_CONFIG
    actual = _cargar_evento_config()
    actual.update(nueva_data)
    try:
        EVENTO_CONFIG_FILE.write_text(json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8")
        EVENTO_CONFIG = actual
        logger.info(f"Evento actualizado: {actual.get('nombre')}")
    except OSError as e:
        logger.error(f"No se pudo guardar evento.json: {e}")
        raise
    return actual

def actualizar_nombre_evento(nombre: str) -> dict:
    nombre = nombre.strip()
    if not (2 <= len(nombre) <= 100):
        raise ValueError("El nombre debe tener entre 2 y 100 caracteres")
    return guardar_evento_config({"nombre": nombre})

EVENTO_CONFIG = _cargar_evento_config()

# ===================================================================
# ASSETS EDITABLES
# ===================================================================
ASSETS_CONFIG = {
    "logo_url": "/assets/logo.png",
    "logo_path": ASSETS_DIR / "logo.png",
    "favicon_url": "/assets/favicon.png",
    "favicon_path": ASSETS_DIR / "favicon.png",
    "fondo_url": "/assets/background.jpg",
    "fondo_path": ASSETS_DIR / "background.jpg",
    "google_link": os.getenv("GOOGLE_REVIEW_LINK", "https://maps.app.goo.gl/2t5QF6zabdPMSehR8"),
}

UPLOAD_CONFIG = {
    "max_size_mb": int(os.getenv("MAX_SIZE_MB", "300")),
    "max_size_bytes": int(os.getenv("MAX_SIZE_MB", "300")) * 1024 * 1024,
    "chunk_size_mb": 2,
    "umbral_fragmentado_mb": 10,
    "allowed_extensions": {
        "imagen": [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif"],
        "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"],
    },
    "max_uploads_concurrentes": int(os.getenv("MAX_UPLOADS_CONCURRENTES", "6")),
    "horas_limpieza_temporales": 6,
}

_usuario_default = "Freeport"
_password_default = "1979"

ADMIN_CONFIG = {
    "usuario": os.getenv("ADMIN_USUARIO", _usuario_default),
    "password": os.getenv("ADMIN_PASSWORD", _password_default),
    "session_expire_hours": int(os.getenv("SESSION_EXPIRE_HOURS", "24")),
    "max_intentos_fallidos": int(os.getenv("MAX_INTENTOS_LOGIN", "6")),
    "bloqueo_minutos": int(os.getenv("BLOQUEO_MINUTOS_LOGIN", "10")),
    "cookie_secure": os.getenv("COOKIE_SECURE", "false").strip().lower() == "true",
}

if ADMIN_CONFIG["usuario"] == _usuario_default and ADMIN_CONFIG["password"] == _password_default:
    logger.warning("Usando usuario/contraseña por defecto. Define ADMIN_USUARIO y ADMIN_PASSWORD en .env")

DATABASE_CONFIG = {
    "path": DATA_DIR / "freeport.db",
    "backup_enabled": True,
    "backup_dir": BASE_DIR / "backups",
    "backup_cada_minutos": int(os.getenv("BACKUP_CADA_MINUTOS", "30")),
    "backups_a_conservar": int(os.getenv("BACKUPS_A_CONSERVAR", "10")),
}

SERVER_CONFIG = {
    "host": os.getenv("HOST", "0.0.0.0"),
    "port": int(os.getenv("PORT", "8000")),
    "debug": os.getenv("DEBUG", "false").strip().lower() == "true",
    "espacio_total_gb": int(os.getenv("ESPACIO_TOTAL_GB", "50")),
    "abrir_navegador": os.getenv("ABRIR_NAVEGADOR", "true").strip().lower() == "true",
    "iniciar_tunel_cloudflare": os.getenv("INICIAR_TUNEL_CLOUDFLARE", "false").strip().lower() == "true",
}

RATE_LIMIT_CONFIG = {
    "subida_por_minuto": int(os.getenv("RATE_LIMIT_SUBIDA_MIN", "30")),
    "login_por_minuto": int(os.getenv("RATE_LIMIT_LOGIN_MIN", "10")),
    "ping_por_minuto": int(os.getenv("RATE_LIMIT_PING_MIN", "20")),
}

def get_public_config() -> dict:
    # Siempre recargar por si cambió desde admin
    evento_actual = _cargar_evento_config()
    return {
        "titulo_evento": evento_actual["nombre"],
        "fondo_url": ASSETS_CONFIG["fondo_url"],
        "logo_url": ASSETS_CONFIG["logo_url"],
        "google_link": ASSETS_CONFIG["google_link"],
        "max_size_mb": UPLOAD_CONFIG["max_size_mb"],
        "extensiones_permitidas": (
            UPLOAD_CONFIG["allowed_extensions"]["imagen"]
            + UPLOAD_CONFIG["allowed_extensions"]["video"]
        ),
    }
