# ===================================================================
# FREEPORT MOMENTS - APP.PY
# Servidor para que los invitados de un evento suban fotos/videos
# desde el celular durante toda la noche, y el administrador las
# revise, apruebe/rechace y descargue el álbum filtrado.
#
# Pensado para correr en una notebook local durante horas sin
# supervisión constante, expuesto a internet mediante un túnel de
# Cloudflare (cloudflared) para que los invitados no necesiten estar
# en la misma red WiFi. Ver README.md para el paso a paso.
# ===================================================================
import asyncio
import contextlib
import mimetypes
import re
import shutil
import subprocess
import time
import uuid
import webbrowser
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
    Request, UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from config import (
    ADMIN_CONFIG, ASSETS_DIR, BASE_DIR, DATABASE_CONFIG, RATE_LIMIT_CONFIG,
    SERVER_CONFIG, UPLOAD_CONFIG, UPLOAD_DIR, get_public_config, logger,
)
import database as db

# ===================================================================
# INICIALIZACION
# ===================================================================
db.inicializar_bd()

app = FastAPI(title="Freeport Moments", version="2.0.0")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# invitados_activos: ip -> ultimo ping (para el contador "conectados ahora")
invitados_activos: dict[str, datetime] = {}
_lock_invitados = Lock()

# locks por id de subida fragmentada, para evitar carreras si llegan
# chunks fuera de orden o duplicados de una misma subida
_locks_subida_fragmentada: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# limita cuantas escrituras de archivo pesadas ocurren en simultaneo
_semaforo_uploads = asyncio.Semaphore(UPLOAD_CONFIG["max_uploads_concurrentes"])

_NOMBRE_SEGURO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ID_SUBIDA_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
ESTADOS_VALIDOS = ("pendientes", "aprobadas", "rechazadas", "descargas")


# ===================================================================
# LIMITADOR DE PETICIONES (rate limiting simple en memoria por IP)
# Primera barrera contra abuso, loops de reintento descontrolados por
# mala señal, o alguien tratando de forzar el login.
# ===================================================================
class LimitadorTasa:
    def __init__(self):
        self._registros: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def permitir(self, clave: str, limite_por_minuto: int) -> bool:
        ahora = time.time()
        with self._lock:
            ventana = self._registros[clave]
            corte = ahora - 60
            while ventana and ventana[0] < corte:
                ventana.pop(0)
            if len(ventana) >= limite_por_minuto:
                return False
            ventana.append(ahora)
            return True


_limitador = LimitadorTasa()


def limitar(nombre_endpoint: str, limite_por_minuto: int):
    async def _dependencia(request: Request):
        ip = request.client.host if request.client else "desconocido"
        if not _limitador.permitir(f"{nombre_endpoint}:{ip}", limite_por_minuto):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones en poco tiempo. Esperá un momento e intentá de nuevo.",
            )
    return _dependencia


# ===================================================================
# UTILIDADES
# ===================================================================
def es_nombre_seguro(nombre: str) -> bool:
    """Evita path traversal: solo letras, numeros, punto, guion y guion bajo."""
    return bool(nombre) and bool(_NOMBRE_SEGURO_RE.match(nombre)) and ".." not in nombre


def abrir_navegador():
    time.sleep(1.5)
    url = f"http://localhost:{SERVER_CONFIG['port']}/admin"
    logger.info(f"Abriendo el navegador en {url} ...")
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"No se pudo abrir el navegador automaticamente: {e}")


def iniciar_tunel_cloudflare():
    """
    Lanza 'cloudflared tunnel --url http://localhost:PORT' si el binario
    esta disponible, y publica en el log la URL publica (algo como
    https://xxxx-xxxx.trycloudflare.com) para compartir con los invitados.
    No requiere cuenta de Cloudflare (tunel rapido / "quick tunnel").
    """
    binario = shutil.which("cloudflared")
    if not binario:
        logger.warning(
            "cloudflared no esta instalado o no esta en el PATH. "
            "Instalalo desde https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ "
            "para poder generar un link publico sin abrir puertos en el router. "
            "Mientras tanto la app solo sera accesible dentro de la misma red WiFi."
        )
        return

    try:
        proceso = subprocess.Popen(
            [binario, "tunnel", "--url", f"http://localhost:{SERVER_CONFIG['port']}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        logger.error(f"No se pudo iniciar cloudflared: {e}")
        return

    patron_url = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    logger.info("Iniciando tunel de Cloudflare, esto puede tardar unos segundos...")

    def _leer_salida():
        for linea in proceso.stdout:
            match = patron_url.search(linea)
            if match:
                logger.info("=" * 70)
                logger.info(f"LINK PUBLICO PARA COMPARTIR CON LOS INVITADOS: {match.group(0)}")
                logger.info("=" * 70)

    import threading
    threading.Thread(target=_leer_salida, daemon=True).start()


def limpiar_invitados_inactivos():
    limite = datetime.now() - timedelta(minutes=2)
    with _lock_invitados:
        for ip in list(invitados_activos.keys()):
            if invitados_activos[ip] < limite:
                del invitados_activos[ip]


def _limpiar_temporales_huerfanos():
    """
    Borra archivos temporales de subidas fragmentadas que quedaron
    abandonados (el invitado cerro la app, se quedo sin señal a mitad
    de la subida, etc.) para que no acumulen espacio en disco toda
    la noche.
    """
    limite_horas = UPLOAD_CONFIG["horas_limpieza_temporales"]
    limite_ts = time.time() - limite_horas * 3600
    carpeta_temp = UPLOAD_DIR / "temp"
    if not carpeta_temp.exists():
        return
    for archivo in carpeta_temp.iterdir():
        try:
            if archivo.is_file() and archivo.stat().st_mtime < limite_ts:
                archivo.unlink()
                logger.info(f"Limpieza: eliminado temporal huerfano {archivo.name}")
        except OSError as e:
            logger.warning(f"No se pudo limpiar temporal {archivo.name}: {e}")


def _generar_thumbnail_sync(ruta_origen: Path, ruta_thumb: Path) -> bool:
    """Genera una miniatura liviana para que la galeria del admin cargue rapido
    incluso con cientos de fotos en alta resolucion. Si Pillow no puede leer
    el formato (por ejemplo algunos HEIC sin plugin), simplemente no se genera
    y el frontend usa la imagen original como respaldo."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False

    try:
        with Image.open(ruta_origen) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((480, 480))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            ruta_thumb.parent.mkdir(parents=True, exist_ok=True)
            ruta_tmp = ruta_thumb.with_suffix(".tmp")
            img.save(ruta_tmp, "JPEG", quality=78, optimize=True)
            ruta_tmp.replace(ruta_thumb)
        return True
    except Exception as e:
        logger.debug(f"No se pudo generar thumbnail para {ruta_origen.name}: {e}")
        return False


def _tarea_generar_thumbnail(ruta_origen: Path, nombre_guardado: str):
    ruta_thumb = UPLOAD_DIR / "thumbnails" / f"{nombre_guardado}.jpg"
    _generar_thumbnail_sync(ruta_origen, ruta_thumb)


def _escribir_stream_a_disco_sync(archivo_sync, ruta_destino: Path, max_bytes: int) -> int:
    """
    Escribe el contenido de un UploadFile (via su handle sync .file) a disco
    en bloques, sin cargar el archivo completo en memoria RAM. Escribe primero
    a un archivo temporal y al final hace un rename atomico, para que un
    corte de luz a mitad de escritura no deje un archivo corrupto a medias
    ocupando el nombre final.
    Lanza ValueError si se supera el tamaño maximo permitido.
    """
    ruta_tmp = ruta_destino.with_suffix(ruta_destino.suffix + ".part")
    tamano_total = 0
    try:
        with open(ruta_tmp, "wb") as destino:
            while True:
                bloque = archivo_sync.read(1024 * 1024)
                if not bloque:
                    break
                tamano_total += len(bloque)
                if tamano_total > max_bytes:
                    raise ValueError("archivo_demasiado_grande")
                destino.write(bloque)
            destino.flush()
            import os
            os.fsync(destino.fileno())
        ruta_tmp.replace(ruta_destino)  # rename atomico (mismo filesystem)
    except Exception:
        ruta_tmp.unlink(missing_ok=True)
        raise
    return tamano_total


def mover_archivo_reintentos(origen: Path, destino: Path):
    """
    Mueve un archivo con reintentos. En Windows, si el navegador o el
    reproductor de video todavia tiene el archivo abierto (WinError 32),
    el primer intento puede fallar; se reintenta pacientemente en segundo
    plano en vez de perder la operacion.
    """
    for intento in range(20):
        try:
            if origen.exists():
                shutil.move(str(origen), str(destino))
            return
        except PermissionError:
            time.sleep(0.5)
        except OSError as e:
            logger.error(f"Error moviendo {origen.name} -> {destino}: {e}")
            return
    logger.error(f"No se pudo mover {origen.name} despues de varios intentos.")


def _crear_zip_album_sync(estado: str, archivos: list[dict], ruta_zip: Path):
    import zipfile
    carpeta = UPLOAD_DIR / estado
    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for archivo in archivos:
            nombre = archivo.get("nombre_guardado") or archivo.get("nombre")
            if not nombre or not es_nombre_seguro(nombre):
                continue
            ruta = carpeta / nombre
            if ruta.exists():
                nombre_en_zip = archivo.get("nombre_original") or nombre
                # evita colisiones si dos originales tienen el mismo nombre
                zf.write(ruta, arcname=f"{Path(nombre).stem}_{nombre_en_zip}")


# ===================================================================
# AUTENTICACION DE ADMINISTRADOR
# ===================================================================
async def requiere_admin(request: Request) -> dict:
    """Dependencia para proteger endpoints de administrador. Antes, varias
    rutas de la API de administración no verificaban ninguna sesión: esto
    corrige ese problema de seguridad."""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")

    sesion = db.obtener_sesion(token)
    if not sesion:
        raise HTTPException(status_code=401, detail="Sesion invalida")

    if datetime.fromisoformat(sesion["expira"]) < datetime.now():
        db.eliminar_sesion(token)
        raise HTTPException(status_code=401, detail="Sesion expirada")

    return sesion


# ===================================================================
# TAREAS PERIODICAS EN SEGUNDO PLANO
# ===================================================================
async def _tarea_mantenimiento():
    while True:
        try:
            limpiar_invitados_inactivos()
            await asyncio.to_thread(db.limpiar_sesiones_expiradas)
            await asyncio.to_thread(_limpiar_temporales_huerfanos)
        except Exception as e:
            logger.error(f"Error en tarea de mantenimiento periodico: {e}")
        await asyncio.sleep(120)


async def _tarea_respaldo():
    intervalo = max(DATABASE_CONFIG["backup_cada_minutos"], 5) * 60
    while True:
        await asyncio.sleep(intervalo)
        try:
            await asyncio.to_thread(db.respaldar_base_datos)
        except Exception as e:
            logger.error(f"Error generando respaldo automatico: {e}")


_tareas_background: list[asyncio.Task] = []


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Freeport Moments iniciando...")
    _tareas_background.append(asyncio.create_task(_tarea_mantenimiento()))
    _tareas_background.append(asyncio.create_task(_tarea_respaldo()))
    yield
    logger.info("Freeport Moments deteniendose, cancelando tareas de fondo...")
    for tarea in _tareas_background:
        tarea.cancel()
    for tarea in _tareas_background:
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
    # respaldo final al apagar, por las dudas
    with contextlib.suppress(Exception):
        db.respaldar_base_datos()
    logger.info("Servidor detenido correctamente. ¡Hasta luego!")


app.router.lifespan_context = lifespan


# ===================================================================
# MANEJO GLOBAL DE ERRORES
# Evita que una excepción no prevista tire un stack trace crudo al
# cliente; siempre responde JSON prolijo y deja registro en el log.
# ===================================================================
@app.exception_handler(Exception)
async def manejador_errores_generico(request: Request, exc: Exception):
    logger.exception(f"Error no controlado en {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"ok": False, "detail": "Ocurrio un error interno. Intentá de nuevo en unos segundos."},
    )


# ===================================================================
# PAGINAS
# ===================================================================
@app.get("/", response_class=HTMLResponse)
async def pagina_root(request: Request):
    return templates.TemplateResponse("guest.html", {"request": request})


@app.get("/guest", response_class=HTMLResponse)
async def pagina_guest(request: Request):
    return templates.TemplateResponse("guest.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def pagina_login(request: Request):
    token = request.cookies.get("session_token")
    if token and db.obtener_sesion(token):
        return templates.TemplateResponse("admin.html", {"request": request})
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def pagina_admin(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return templates.TemplateResponse("login.html", {"request": request, "mensaje": "Inicia sesión"})
    sesion = db.obtener_sesion(token)
    if not sesion:
        return templates.TemplateResponse("login.html", {"request": request, "mensaje": "Inicia sesión"})
    if datetime.fromisoformat(sesion["expira"]) < datetime.now():
        db.eliminar_sesion(token)
        return templates.TemplateResponse("login.html", {"request": request, "mensaje": "Tu sesión expiró"})
    return templates.TemplateResponse("admin.html", {"request": request})


# ===================================================================
# API PUBLICA (sin autenticacion, usada por los invitados)
# ===================================================================
@app.get("/api/health")
async def api_health():
    return {"ok": True, "servicio": "freeport-moments", "hora_servidor": datetime.now().isoformat()}


@app.get("/api/configuracion/publica")
async def api_config_publica():
    return get_public_config()


@app.post("/api/guest/ping")
async def api_guest_ping(request: Request, _=Depends(limitar("ping", RATE_LIMIT_CONFIG["ping_por_minuto"]))):
    ip = request.client.host if request.client else str(uuid.uuid4())
    with _lock_invitados:
        invitados_activos[ip] = datetime.now()
    limpiar_invitados_inactivos()
    with _lock_invitados:
        conectados = len(invitados_activos)
    return {"ok": True, "conectados": conectados}


@app.post("/api/subida")
async def api_subida(
    request: Request,
    archivo: UploadFile = File(...),
    _=Depends(limitar("subida", RATE_LIMIT_CONFIG["subida_por_minuto"])),
):
    ext = Path(archivo.filename or "").suffix.lower()
    permitidas = UPLOAD_CONFIG["allowed_extensions"]["imagen"] + UPLOAD_CONFIG["allowed_extensions"]["video"]
    if ext not in permitidas:
        raise HTTPException(status_code=400, detail=f"Extensión '{ext}' no permitida")

    es_video = ext in UPLOAD_CONFIG["allowed_extensions"]["video"]
    if es_video:
        numero = await asyncio.to_thread(db.siguiente_numero_video)
        nombre_guardado = f"video_{numero}{ext}"
        tipo = mimetypes.guess_type(nombre_guardado)[0] or "video/mp4"
    else:
        nombre_guardado = f"{uuid.uuid4().hex}{ext}"
        tipo = mimetypes.guess_type(nombre_guardado)[0] or "image/jpeg"

    ruta_destino = UPLOAD_DIR / "pendientes" / nombre_guardado
    max_bytes = UPLOAD_CONFIG["max_size_bytes"]

    async with _semaforo_uploads:
        try:
            tamano = await asyncio.to_thread(
                _escribir_stream_a_disco_sync, archivo.file, ruta_destino, max_bytes
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"El archivo supera el máximo de {UPLOAD_CONFIG['max_size_mb']}MB",
            )
        except OSError as e:
            logger.error(f"Error de disco al guardar {nombre_guardado}: {e}")
            raise HTTPException(
                status_code=507,
                detail="No hay espacio suficiente en el servidor para guardar el archivo. Avisá al administrador.",
            )

    info = {
        "nombre_original": archivo.filename or nombre_guardado,
        "nombre_guardado": nombre_guardado,
        "tipo": tipo,
        "extension": ext,
        "tamano_bytes": tamano,
        "estado": "pendientes",
        "ruta": str(ruta_destino),
        "url": f"/uploads/pendientes/{nombre_guardado}",
        "metadata": {},
        "ip_origen": request.client.host if request.client else "",
    }
    await asyncio.to_thread(db.guardar_archivo, info)

    if not es_video:
        asyncio.create_task(asyncio.to_thread(_tarea_generar_thumbnail, ruta_destino, nombre_guardado))

    return {"ok": True, "archivo": nombre_guardado}


@app.post("/api/subida/fragmentada")
async def api_subida_fragmentada(
    request: Request,
    bloque: UploadFile = File(...),
    id_subida: str = Form(...),
    indice_bloque: int = Form(...),
    total_bloques: int = Form(...),
    nombre_original: str = Form(...),
    tipo_archivo: str = Form(""),
    _=Depends(limitar("subida", RATE_LIMIT_CONFIG["subida_por_minuto"])),
):
    if not _ID_SUBIDA_RE.match(id_subida):
        raise HTTPException(status_code=400, detail="Identificador de subida inválido")
    if indice_bloque < 0 or total_bloques <= 0 or indice_bloque >= total_bloques:
        raise HTTPException(status_code=400, detail="Índice de bloque inválido")

    ext = Path(nombre_original).suffix.lower()
    permitidas = UPLOAD_CONFIG["allowed_extensions"]["imagen"] + UPLOAD_CONFIG["allowed_extensions"]["video"]
    if ext not in permitidas:
        raise HTTPException(status_code=400, detail=f"Extensión '{ext}' no permitida")

    temp_file_path = UPLOAD_DIR / "temp" / f"{id_subida}.tmp"
    max_bytes = UPLOAD_CONFIG["max_size_bytes"]

    lock = _locks_subida_fragmentada[id_subida]
    async with lock:
        try:
            contenido = await bloque.read()

            def _append():
                with open(temp_file_path, "ab") as f:
                    f.write(contenido)
                return temp_file_path.stat().st_size

            tamano_actual = await asyncio.to_thread(_append)
            if tamano_actual > max_bytes:
                temp_file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail=f"El archivo supera el máximo de {UPLOAD_CONFIG['max_size_mb']}MB",
                )
        except OSError as e:
            logger.error(f"Error de disco en bloque {indice_bloque} de {id_subida}: {e}")
            raise HTTPException(status_code=507, detail="No hay espacio suficiente en el servidor.")

        if indice_bloque == total_bloques - 1:
            es_video = ext in UPLOAD_CONFIG["allowed_extensions"]["video"]
            if es_video:
                numero = await asyncio.to_thread(db.siguiente_numero_video)
                nombre_guardado = f"video_{numero}{ext}"
            else:
                nombre_guardado = f"{uuid.uuid4().hex}{ext}"

            ruta_destino = UPLOAD_DIR / "pendientes" / nombre_guardado

            async with _semaforo_uploads:
                try:
                    await asyncio.to_thread(shutil.move, str(temp_file_path), str(ruta_destino))
                except OSError as e:
                    logger.error(f"Error moviendo archivo fragmentado ensamblado: {e}")
                    raise HTTPException(status_code=500, detail="No se pudo finalizar la subida.")

            tamano_final = ruta_destino.stat().st_size
            info = {
                "nombre_original": nombre_original,
                "nombre_guardado": nombre_guardado,
                "tipo": tipo_archivo or mimetypes.guess_type(nombre_guardado)[0] or "application/octet-stream",
                "extension": ext,
                "tamano_bytes": tamano_final,
                "estado": "pendientes",
                "ruta": str(ruta_destino),
                "url": f"/uploads/pendientes/{nombre_guardado}",
                "metadata": {"fragmentada": True},
                "ip_origen": request.client.host if request.client else "",
            }
            await asyncio.to_thread(db.guardar_archivo, info)

            if not es_video:
                asyncio.create_task(asyncio.to_thread(_tarea_generar_thumbnail, ruta_destino, nombre_guardado))

            _locks_subida_fragmentada.pop(id_subida, None)
            return {"ok": True, "completado": True, "archivo": nombre_guardado}

    return {"ok": True, "completado": False}


# ===================================================================
# API DE AUTENTICACION
# ===================================================================
@app.post("/api/login")
async def api_login(
    datos: dict,
    request: Request,
    _=Depends(limitar("login", RATE_LIMIT_CONFIG["login_por_minuto"])),
):
    import secrets as _secrets

    ip = request.client.host if request.client else "desconocido"

    bloqueada, restante = await asyncio.to_thread(db.ip_esta_bloqueada, ip)
    if bloqueada:
        minutos = max(1, restante // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Probá de nuevo en {minutos} minuto(s).",
        )

    usuario = str(datos.get("usuario", ""))
    password = str(datos.get("password", ""))

    usuario_ok = _secrets.compare_digest(usuario, ADMIN_CONFIG["usuario"])
    password_ok = _secrets.compare_digest(password, ADMIN_CONFIG["password"])

    if usuario_ok and password_ok:
        await asyncio.to_thread(db.resetear_intentos_fallidos, ip)
        token = _secrets.token_urlsafe(32)
        expira = datetime.now() + timedelta(hours=ADMIN_CONFIG["session_expire_hours"])
        await asyncio.to_thread(db.crear_sesion, token, usuario, expira)

        response = JSONResponse({"ok": True, "mensaje": "Login correcto"})
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            secure=ADMIN_CONFIG["cookie_secure"],
            samesite="lax",
            max_age=ADMIN_CONFIG["session_expire_hours"] * 3600,
        )
        logger.info(f"Login exitoso de administrador desde {ip}")
        return response

    intentos = await asyncio.to_thread(
        db.registrar_intento_fallido, ip, ADMIN_CONFIG["max_intentos_fallidos"], ADMIN_CONFIG["bloqueo_minutos"]
    )
    logger.warning(f"Intento de login fallido #{intentos} desde {ip}")
    raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        await asyncio.to_thread(db.eliminar_sesion, token)
    response = JSONResponse({"ok": True})
    response.delete_cookie("session_token")
    return response


# ===================================================================
# API DE ADMINISTRACION (protegida con sesión)
# ===================================================================
@app.get("/api/estadisticas")
async def api_estadisticas(_sesion=Depends(requiere_admin)):
    limpiar_invitados_inactivos()
    stats = await asyncio.to_thread(db.obtener_estadisticas)
    with _lock_invitados:
        stats["conectados"] = len(invitados_activos)
    from config import EVENTO_CONFIG
    stats["evento"] = {
        "nombre": EVENTO_CONFIG["nombre"],
        "fecha": EVENTO_CONFIG["fecha"],
        "hora": EVENTO_CONFIG["hora"],
    }
    return stats


@app.get("/api/archivos")
async def api_listar_archivos(estado: str = "pendientes", _sesion=Depends(requiere_admin)):
    if estado not in ESTADOS_VALIDOS:
        estado = "pendientes"
    archivos = await asyncio.to_thread(db.listar_archivos, estado)

    for archivo in archivos:
        ruta_thumb = UPLOAD_DIR / "thumbnails" / f"{archivo['nombre_guardado']}.jpg"
        archivo["thumbnail_url"] = (
            f"/uploads/thumbnails/{archivo['nombre_guardado']}.jpg" if ruta_thumb.exists() else None
        )

    return {"archivos": archivos, "total": len(archivos), "estado": estado}


@app.post("/api/archivos/accion")
async def api_accion_archivo(datos: dict, background_tasks: BackgroundTasks, _sesion=Depends(requiere_admin)):
    nombre = str(datos.get("nombre", ""))
    estado_actual = str(datos.get("estado_actual", ""))
    accion = str(datos.get("accion", ""))

    if not nombre or not estado_actual or not accion:
        raise HTTPException(status_code=400, detail="Faltan datos obligatorios (nombre, estado o acción)")
    if not es_nombre_seguro(nombre):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")
    if estado_actual not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado inválido")

    origen = UPLOAD_DIR / estado_actual / nombre
    if not origen.exists():
        for carpeta in ESTADOS_VALIDOS:
            posible = UPLOAD_DIR / carpeta / nombre
            if posible.exists():
                origen = posible
                estado_actual = carpeta
                break

    if not origen.exists():
        raise HTTPException(status_code=404, detail=f"No encontrado: {nombre}")

    if accion == "aprobar":
        destino = UPLOAD_DIR / "aprobadas" / nombre
        await asyncio.to_thread(db.actualizar_estado_archivo, nombre, "aprobadas")
        background_tasks.add_task(mover_archivo_reintentos, origen, destino)
        return {"ok": True}

    if accion == "rechazar":
        destino = UPLOAD_DIR / "rechazadas" / nombre
        await asyncio.to_thread(db.actualizar_estado_archivo, nombre, "rechazadas")
        background_tasks.add_task(mover_archivo_reintentos, origen, destino)
        return {"ok": True}

    if accion == "eliminar":
        # borrado definitivo (por ejemplo, contenido inapropiado)
        await asyncio.to_thread(db.eliminar_registro_archivo, nombre)
        with contextlib.suppress(OSError):
            origen.unlink()
        ruta_thumb = UPLOAD_DIR / "thumbnails" / f"{nombre}.jpg"
        with contextlib.suppress(OSError):
            ruta_thumb.unlink()
        return {"ok": True}

    if accion == "descargar":
        if estado_actual != "descargas":
            destino = UPLOAD_DIR / "descargas" / nombre
            await asyncio.to_thread(db.actualizar_estado_archivo, nombre, "descargas")
            background_tasks.add_task(mover_archivo_reintentos, origen, destino)
            estado_actual = "descargas"
        return {"ok": True, "url": f"/api/archivos/descargar?archivo={nombre}&estado={estado_actual}"}

    raise HTTPException(status_code=400, detail="Acción no válida")


@app.get("/api/archivos/descargar")
async def api_descargar(archivo: str, estado: str = "aprobadas", _sesion=Depends(requiere_admin)):
    if not es_nombre_seguro(archivo):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")
    if estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado inválido")

    ruta = UPLOAD_DIR / estado / archivo
    if not ruta.exists():
        # El archivo puede estar todavía en tránsito (el "mover" corre en
        # segundo plano al marcarlo como descargado), así que lo buscamos
        # en las demás carpetas antes de rendirnos.
        for carpeta in ESTADOS_VALIDOS:
            posible = UPLOAD_DIR / carpeta / archivo
            if posible.exists():
                ruta = posible
                break

    if not ruta.exists():
        raise HTTPException(status_code=404, detail="No encontrado")
    return FileResponse(str(ruta), filename=archivo)


@app.get("/api/archivos/descargar-todo")
async def api_descargar_todo(estado: str = "aprobadas", _sesion=Depends(requiere_admin)):
    """Genera y descarga un ZIP con todos los archivos del estado indicado
    (por defecto, el álbum de aprobadas). Ideal para bajarse todo el álbum
    filtrado al final de la noche de una sola vez."""
    if estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado inválido")

    archivos = await asyncio.to_thread(db.listar_archivos, estado, 100000, 0)
    if not archivos:
        raise HTTPException(status_code=404, detail=f"No hay archivos en '{estado}' todavía")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_zip = f"freeport_{estado}_{timestamp}.zip"
    ruta_zip = UPLOAD_DIR / "temp" / nombre_zip

    await asyncio.to_thread(_crear_zip_album_sync, estado, archivos, ruta_zip)

    if not ruta_zip.exists():
        raise HTTPException(status_code=500, detail="No se pudo generar el archivo ZIP")

    respuesta = FileResponse(str(ruta_zip), filename=nombre_zip, media_type="application/zip")
    respuesta.background = BackgroundTask(lambda: ruta_zip.unlink(missing_ok=True))
    return respuesta


@app.post("/api/evento/nuevo")
async def api_nuevo_evento(_sesion=Depends(requiere_admin)):
    await asyncio.to_thread(db.borrar_todo_evento)
    return {"ok": True}


# ===================================================================
# PUNTO DE ENTRADA
# ===================================================================
if __name__ == "__main__":
    import threading

    import uvicorn

    if SERVER_CONFIG["abrir_navegador"]:
        threading.Thread(target=abrir_navegador, daemon=True).start()

    if SERVER_CONFIG["iniciar_tunel_cloudflare"]:
        threading.Thread(target=iniciar_tunel_cloudflare, daemon=True).start()

    try:
        uvicorn.run(
            "app:app",
            host=SERVER_CONFIG["host"],
            port=SERVER_CONFIG["port"],
            # workers=1 es intencional: el estado en memoria (invitados
            # conectados, locks de subida) asume un único proceso.
            reload=False,
            log_level="info",
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Servidor detenido por el usuario.")
