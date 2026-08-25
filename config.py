# ===================================================================
# FREEPORT MOMENTS - CONFIG.PY
# Configuracion central de la aplicacion.
#
# Todo lo que normalmente cambia entre un evento y otro (usuario/clave
# de administrador, nombre del evento, link de Google, etc.) se puede
# definir por variable de entorno (archivo .env) SIN tocar el codigo.
#
# Si una variable de entorno no esta definida, se usa un valor por
# defecto razonable, pero se deja aviso en el log para que el
# administrador sepa que deberia configurarla antes del evento real.
# ===================================================================
import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

# python-dotenv es opcional: si no esta instalado, seguimos funcionando
# solo con las variables de entorno del sistema operativo.
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

# ===================================================================
# CREACION DE CARPETAS NECESARIAS (con manejo de errores: si el disco
# esta lleno o sin permisos, preferimos avisar claro antes de arrancar)
# ===================================================================
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
        raise SystemExit(
            f"[FATAL] No se pudo crear la carpeta requerida '{carpeta}': {e}\n"
            f"Revisa permisos de escritura o espacio en disco antes de continuar."
        )

# ===================================================================
# LOGGING
# Se loguea a consola y a archivo rotativo (evita que el log crezca
# sin limite durante toda una noche de evento).
# ===================================================================
def _configurar_logging() -> logging.Logger:
    logger = logging.getLogger("freeport")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger  # evita duplicar handlers si config.py se importa mas de una vez

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
            maxBytes=5 * 1024 * 1024,  # 5 MB por archivo
            backupCount=5,
            encoding="utf-8",
        )
        handler_archivo.setFormatter(formato)
        logger.addHandler(handler_archivo)
    except OSError:
        logger.warning("No se pudo crear el archivo de log en disco; solo se logueara en consola.")

    return logger


logger = _configurar_logging()

# ===================================================================
# SECRET KEY PERSISTENTE
# Se usa para firmar/identificar cosas internas. Si no existe, se
# genera una vez y se guarda en disco para que sobreviva a reinicios
# del servidor (por ejemplo, un corte de luz breve durante la noche).
# ===================================================================
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
        logger.warning("No se pudo persistir la SECRET_KEY en disco; se regenerara en cada reinicio.")

    return nueva_key


SECRET_KEY = _obtener_o_crear_secret_key()

# ===================================================================
# EVENTO - EDITABLE por variables de entorno o directamente aca
# ===================================================================
EVENTO_CONFIG = {
    "nombre": os.getenv("EVENTO_NOMBRE", "Evento de la Noche"),
    "fecha": os.getenv("EVENTO_FECHA", "--/--/----"),
    "hora": os.getenv("EVENTO_HORA", "--:-- hs"),
    "descripcion": os.getenv("EVENTO_DESCRIPCION", "Evento sin configurar"),
    "lugar": os.getenv("EVENTO_LUGAR", ""),
}

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
    "google_link": os.getenv(
        "GOOGLE_REVIEW_LINK", "https://maps.app.goo.gl/2t5QF6zabdPMSehR8"
    ),
}

# ===================================================================
# SUBIDA DE ARCHIVOS
# ===================================================================
UPLOAD_CONFIG = {
    "max_size_mb": int(os.getenv("MAX_SIZE_MB", "300")),
    "max_size_bytes": int(os.getenv("MAX_SIZE_MB", "300")) * 1024 * 1024,
    "chunk_size_mb": 2,
    "umbral_fragmentado_mb": 10,  # a partir de este tamaño el cliente sube en bloques
    "allowed_extensions": {
        "imagen": [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif"],
        "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"],
    },
    # Cuantos uploads simultaneos como maximo se procesan en paralelo.
    # Protege el disco y la memoria cuando muchos invitados suben a la vez.
    "max_uploads_concurrentes": int(os.getenv("MAX_UPLOADS_CONCURRENTES", "6")),
    # Antiguedad maxima (horas) de un archivo temporal fragmentado antes
    # de considerarlo huerfano (el invitado cerro la app a mitad de subida)
    # y elegible para limpieza automatica.
    "horas_limpieza_temporales": 6,
}

# ===================================================================
# SEGURIDAD / ADMIN
#
# IMPORTANTE: en produccion definir ADMIN_USUARIO y ADMIN_PASSWORD
# como variables de entorno (o en el archivo .env). Si no se definen,
# se usan valores por defecto SOLO PARA DESARROLLO y se avisa en el
# log al arrancar.
# ===================================================================
_usuario_default = "Freeport"
_password_default = "1979"

ADMIN_CONFIG = {
    "usuario": os.getenv("ADMIN_USUARIO", _usuario_default),
    "password": os.getenv("ADMIN_PASSWORD", _password_default),
    "session_expire_hours": int(os.getenv("SESSION_EXPIRE_HOURS", "24")),
    # Proteccion basica contra fuerza bruta en /api/login
    "max_intentos_fallidos": int(os.getenv("MAX_INTENTOS_LOGIN", "6")),
    "bloqueo_minutos": int(os.getenv("BLOQUEO_MINUTOS_LOGIN", "10")),
    # Cookie "secure" solo debe ir en True si la app se sirve por HTTPS
    # (por ejemplo detras de un tunel de Cloudflare). En localhost/HTTP
    # dejarlo en False o el navegador ignorara la cookie de sesion.
    "cookie_secure": os.getenv("COOKIE_SECURE", "false").strip().lower() == "true",
}

if ADMIN_CONFIG["usuario"] == _usuario_default and ADMIN_CONFIG["password"] == _password_default:
    logger.warning(
        "Estas usando el usuario/contraseña de administrador por defecto. "
        "Se recomienda definir ADMIN_USUARIO y ADMIN_PASSWORD en un archivo .env antes del evento."
    )

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

# Limite simple de peticiones por IP para endpoints sensibles
# (subida y login), como primera barrera ante abuso o loops de errores
# de clientes con mala señal reintentando sin control.
RATE_LIMIT_CONFIG = {
    "subida_por_minuto": int(os.getenv("RATE_LIMIT_SUBIDA_MIN", "30")),
    "login_por_minuto": int(os.getenv("RATE_LIMIT_LOGIN_MIN", "10")),
    "ping_por_minuto": int(os.getenv("RATE_LIMIT_PING_MIN", "20")),
}


def get_public_config() -> dict:
    """Configuracion segura para exponer al invitado (sin datos sensibles)."""
    return {
        "titulo_evento": EVENTO_CONFIG["nombre"],
        "fondo_url": ASSETS_CONFIG["fondo_url"],
        "logo_url": ASSETS_CONFIG["logo_url"],
        "google_link": ASSETS_CONFIG["google_link"],
        "max_size_mb": UPLOAD_CONFIG["max_size_mb"],
        "extensiones_permitidas": (
            UPLOAD_CONFIG["allowed_extensions"]["imagen"]
            + UPLOAD_CONFIG["allowed_extensions"]["video"]
        ),
    }
