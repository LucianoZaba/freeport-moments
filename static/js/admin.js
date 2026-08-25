// ===================================================================
// FREEPORT MOMENTS - ADMIN JS (Corregido)
// ===================================================================

let archivosActuales = [];
let archivoActualIndex = 0;
let seccionActual = 'pendientes';
let archivoAEliminar = null;
let fallosDeRedConsecutivos = 0;

const galeriaGrid = document.getElementById('galeriaGrid');
const galeriaTitulo = document.getElementById('galeriaTitulo');
const visorOverlay = document.getElementById('visorOverlay');
const visorImagen = document.getElementById('visorImagen');
const visorVideo = document.getElementById('visorVideo');
const visorNombre = document.getElementById('visorNombre');
const visorContador = document.getElementById('visorContador');
const bannerOffline = document.getElementById('bannerOffline');
const estadoPunto = document.getElementById('estadoPunto');
const estadoTexto = document.getElementById('estadoTexto');

document.addEventListener('DOMContentLoaded', () => {
    inicializarNavegacion();
    inicializarVisor();
    inicializarNuevoEvento();
    inicializarEliminarArchivo();
    inicializarLogout();
    inicializarDescargaAlbum();
    cargarEstadisticas();
    cargarSeccion('pendientes');
});

setInterval(() => {
    cargarEstadisticas();
    if (document.visibilityState === 'visible') {
        cargarSeccion(seccionActual, false);
    }
}, 8000);

window.addEventListener('online', () => actualizarIndicadorConexion(true));
window.addEventListener('offline', () => actualizarIndicadorConexion(false));

function actualizarIndicadorConexion(conectado) {
    bannerOffline.hidden = conectado;
    estadoPunto.classList.toggle('verde', conectado);
    estadoPunto.classList.toggle('rojo', !conectado);
    estadoTexto.textContent = conectado ? 'En línea' : 'Sin conexión';
}

// =========================================================
// FETCH CENTRALIZADO
// =========================================================
async function apiFetch(url, opciones = {}) {
    try {
        const respuesta = await fetch(url, opciones);
        fallosDeRedConsecutivos = 0;
        actualizarIndicadorConexion(true);

        if (respuesta.status === 401) {
            window.location.href = '/login';
            throw new Error('Sesión expirada');
        }
        return respuesta;
    } catch (error) {
        fallosDeRedConsecutivos++;
        if (fallosDeRedConsecutivos >= 2) {
            actualizarIndicadorConexion(false);
        }
        throw error;
    }
}

// =========================================================
// NAVEGACION
// =========================================================
function inicializarNavegacion() {
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('activo'));
            btn.classList.add('activo');
            cargarSeccion(btn.dataset.seccion);
        });
    });
    document.getElementById('btnActualizar').addEventListener('click', () => {
        cargarEstadisticas();
        cargarSeccion(seccionActual);
    });
}

// =========================================================
// LOGOUT
// =========================================================
function inicializarLogout() {
    document.getElementById('btnLogout').addEventListener('click', async () => {
        try {
            await apiFetch('/api/logout', { method: 'POST' });
        } catch { /* ignorar error de red al salir */ }
        window.location.href = '/login';
    });
}

// =========================================================
// ESTADISTICAS
// =========================================================
async function cargarEstadisticas() {
    try {
        const res = await apiFetch('/api/estadisticas');
        if (!res.ok) return;
        const stats = await res.json();

        setTexto('contadorPendientesSidebar', stats.pendientes);
        setTexto('contadorAprobadasSidebar', stats.aprobadas);
        setTexto('contadorRechazadasSidebar', stats.rechazadas);
        setTexto('contadorDescargasSidebar', stats.descargadas);

        setTexto('statConectados', stats.conectados);
        setTexto('statFotos', stats.fotos);
        setTexto('statVideos', stats.videos);
        setTexto('statPendientes', stats.pendientes);
        setTexto('statAprobadas', stats.aprobadas);
        setTexto('statRechazadas', stats.rechazadas);
        setTexto('statDescargadas', stats.descargadas);

        if (stats.evento) {
            setTexto('nombreEvento', stats.evento.nombre || 'Sin configurar');
            setTexto('fechaEvento', stats.evento.fecha || '--/--/----');
            setTexto('horaEvento', stats.evento.hora || '--:-- hs');
        }

        if (stats.espacio) {
            setTexto('espacioTexto', stats.espacio.texto);
            document.getElementById('espacioBarra').style.width = stats.espacio.porcentaje + '%';
            setTexto('espacioPorcentaje', stats.espacio.porcentaje + '%');
        }
    } catch (e) {
        console.error('Error cargando estadísticas:', e);
    }
}

function setTexto(id, valor) {
    const el = document.getElementById(id);
    if (el) el.textContent = valor ?? 0;
}

// =========================================================
// GALERIA
// =========================================================
async function cargarSeccion(seccion, mostrarCargando = true) {
    seccionActual = seccion;
    if (mostrarCargando) galeriaGrid.innerHTML = '<div class="galeria-cargando">Cargando...</div>';

    try {
        const res = await apiFetch(`/api/archivos?estado=${encodeURIComponent(seccion)}`);
        if (!res.ok) throw new Error('Respuesta no OK');
        const data = await res.json();
        archivosActuales = data.archivos || [];

        const titulos = { pendientes: 'Pendientes', aprobadas: 'Aprobadas', rechazadas: 'Rechazadas', descargas: 'Descargas' };
        galeriaTitulo.innerHTML = `${titulos[seccion] || seccion} <span class="galeria-badge naranja">${archivosActuales.length}</span>`;

        renderizarGaleria(archivosActuales);
    } catch (e) {
        if (mostrarCargando) {
            galeriaGrid.innerHTML = '<div class="galeria-vacio error"><div class="vacio-icono">⚠️</div><h3 class="vacio-titulo">No se pudo cargar</h3><p class="vacio-texto">Revisá tu conexión, reintentando automáticamente...</p></div>';
        }
    }
}

function renderizarGaleria(archivos) {
    galeriaGrid.innerHTML = '';
    if (archivos.length === 0) {
        galeriaGrid.innerHTML = `<div class="galeria-vacio"><div class="vacio-icono">📷</div><h3>Aún no hay archivos en ${seccionActual}</h3><p>Los momentos que suban tus invitados aparecerán aquí.</p></div>`;
        return;
    }
    const fragmento = document.createDocumentFragment();
    archivos.forEach((archivo, index) => {
        const card = document.createElement('div');
        card.className = 'media-card';
        const esVideo = archivo.tipo && archivo.tipo.includes('video');
        const urlOriginal = archivo.url || `/uploads/${seccionActual}/${archivo.nombre}`;
        const urlMiniatura = (!esVideo && archivo.thumbnail_url) ? archivo.thumbnail_url : urlOriginal;

        const thumb = esVideo
            ? `<video class="media-thumb" src="${urlOriginal}#t=0.5" muted preload="metadata" playsinline></video>`
            : `<img class="media-thumb" src="${urlMiniatura}" loading="lazy" alt="">`;

        const badgeVideo = esVideo ? '<span class="media-thumb-video-badge">▶ video</span>' : '';

        card.innerHTML = `${thumb}${badgeVideo}<div class="media-overlay"><span class="media-tiempo">${formatearTiempo(archivo.fecha)}</span></div>`;
        card.addEventListener('click', () => abrirVisor(index));
        fragmento.appendChild(card);
    });
    galeriaGrid.appendChild(fragmento);
}

function formatearTiempo(fechaStr) {
    if (!fechaStr) return 'Ahora';
    try {
        const fecha = new Date(fechaStr.replace(' ', 'T'));
        const diff = Date.now() - fecha.getTime();
        const minutos = Math.floor(diff / 60000);
        if (minutos < 1) return 'Ahora';
        if (minutos < 60) return `Hace ${minutos} min`;
        const horas = Math.floor(minutos / 60);
        if (horas < 24) return `Hace ${horas}h`;
        return fecha.toLocaleDateString('es-AR');
    } catch {
        return 'Hace un momento';
    }
}

// =========================================================
// VISOR CARRUSEL
// =========================================================
function inicializarVisor() {
    const btnCerrar = document.getElementById('visorCerrar');
    const btnAnterior = document.getElementById('visorAnterior');
    const btnSiguiente = document.getElementById('visorSiguiente');
    const btnAprobar = document.getElementById('visorAprobar');
    const btnRechazar = document.getElementById('visorRechazar');
    const btnDescargar = document.getElementById('visorDescargar');
    const btnEliminar = document.getElementById('visorEliminar');

    if (btnCerrar) btnCerrar.addEventListener('click', cerrarVisor);
    if (btnAnterior) btnAnterior.addEventListener('click', () => navegarVisor(-1));
    if (btnSiguiente) btnSiguiente.addEventListener('click', () => navegarVisor(1));
    
    if (btnAprobar) btnAprobar.addEventListener('click', () => accionArchivo('aprobar'));
    if (btnRechazar) btnRechazar.addEventListener('click', () => accionArchivo('rechazar'));
    if (btnDescargar) btnDescargar.addEventListener('click', () => accionArchivo('descargar'));
    
    if (btnEliminar) {
        btnEliminar.addEventListener('click', () => {
            archivoAEliminar = archivosActuales[archivoActualIndex];
            const modalEliminar = document.getElementById('modalEliminarArchivo');
            if (modalEliminar) modalEliminar.hidden = false;
        });
    }

    if (visorOverlay) {
        visorOverlay.addEventListener('click', (e) => { 
            if (e.target === visorOverlay) cerrarVisor(); 
        });
    }

    document.addEventListener('keydown', (e) => {
        if (!visorOverlay || visorOverlay.hidden) return;
        if (e.key === 'Escape') cerrarVisor();
        if (e.key === 'ArrowLeft') navegarVisor(-1);
        if (e.key === 'ArrowRight') navegarVisor(1);
    });
}

function abrirVisor(index) {
    archivoActualIndex = index;
    mostrarArchivoEnVisor();
    if (visorOverlay) visorOverlay.hidden = false;
    document.body.style.overflow = 'hidden';
}

function cerrarVisor() {
    if (visorOverlay) visorOverlay.hidden = true;
    document.body.style.overflow = '';
    if (visorImagen) visorImagen.src = '';
    if (visorVideo) {
        visorVideo.pause();
        visorVideo.src = '';
        visorVideo.load();
    }
}

function navegarVisor(dir) {
    archivoActualIndex += dir;
    if (archivoActualIndex < 0) archivoActualIndex = archivosActuales.length - 1;
    if (archivoActualIndex >= archivosActuales.length) archivoActualIndex = 0;
    mostrarArchivoEnVisor();
}

function mostrarArchivoEnVisor() {
    const archivo = archivosActuales[archivoActualIndex];
    if (!archivo) return;
    const url = archivo.url || `/uploads/${seccionActual}/${archivo.nombre}`;
    const esVideo = archivo.tipo && archivo.tipo.includes('video');
    
    if (visorNombre) visorNombre.textContent = archivo.nombre_original || archivo.nombre || 'Archivo';
    if (visorContador) visorContador.textContent = `${archivoActualIndex + 1} / ${archivosActuales.length}`;

    if (visorVideo && visorVideo.src) {
        visorVideo.pause();
        visorVideo.src = '';
        visorVideo.load();
    }

    if (esVideo) {
        if (visorImagen) visorImagen.hidden = true;
        if (visorVideo) {
            visorVideo.hidden = false;
            visorVideo.src = url;
        }
    } else {
        if (visorVideo) visorVideo.hidden = true;
        if (visorImagen) {
            visorImagen.hidden = false;
            visorImagen.src = url;
        }
    }
}

// =========================================================
// ACCIONES SOBRE ARCHIVOS (aprobar / rechazar / descargar)
// =========================================================
async function accionArchivo(accion) {
    const archivo = archivosActuales[archivoActualIndex];
    if (!archivo) return;
    try {
        if (visorVideo && !visorVideo.hidden) {
            visorVideo.pause();
            visorVideo.src = '';
            visorVideo.load();
        }
        document.querySelectorAll('video.media-thumb').forEach(v => {
            if (v.src && v.src.includes(archivo.nombre)) {
                v.pause();
                v.src = '';
                v.load();
                v.remove();
            }
        });
        await new Promise(r => setTimeout(r, 350));

        const res = await apiFetch('/api/archivos/accion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nombre: archivo.nombre, estado_actual: seccionActual, accion }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || `Error ${res.status}`);
        }

        if (accion === 'descargar') {
            window.location.href = `/api/archivos/descargar?archivo=${encodeURIComponent(archivo.nombre)}&estado=${seccionActual}`;
        } else {
            quitarArchivoDeListaActual();
            cargarEstadisticas();
        }
    } catch (e) {
        console.error('Error en la acción del archivo:', e);
        alert('Error en la acción: ' + e.message);
    }
}

function quitarArchivoDeListaActual() {
    archivosActuales.splice(archivoActualIndex, 1);
    if (archivosActuales.length === 0) {
        cerrarVisor();
        renderizarGaleria([]);
    } else {
        if (archivoActualIndex >= archivosActuales.length) archivoActualIndex = 0;
        mostrarArchivoEnVisor();
        renderizarGaleria(archivosActuales);
    }
}

// =========================================================
// ELIMINAR ARCHIVO (borrado definitivo)
// =========================================================
function inicializarEliminarArchivo() {
    const modal = document.getElementById('modalEliminarArchivo');
    const btnCancelar = document.getElementById('btnCancelarEliminar');
    const btnConfirmar = document.getElementById('btnConfirmarEliminar');

    if (btnCancelar) {
        btnCancelar.addEventListener('click', () => {
            if (modal) modal.hidden = true;
            archivoAEliminar = null;
        });
    }

    if (btnConfirmar) {
        btnConfirmar.addEventListener('click', async () => {
            if (!archivoAEliminar) return;
            if (modal) modal.hidden = true;
            try {
                const res = await apiFetch('/api/archivos/accion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nombre: archivoAEliminar.nombre, estado_actual: seccionActual, accion: 'eliminar' }),
                });
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.detail || `Error ${res.status}`);
                }
                quitarArchivoDeListaActual();
                cargarEstadisticas();
            } catch (e) {
                alert('No se pudo eliminar: ' + e.message);
            } finally {
                archivoAEliminar = null;
            }
        });
    }
}

// =========================================================
// DESCARGAR ALBUM COMPLETO (ZIP)
// =========================================================
function inicializarDescargaAlbum() {
    const btn = document.getElementById('btnDescargarAlbum');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const textoOriginal = btn.innerHTML;
        btn.innerHTML = '<span>⏳</span> Generando ZIP...';
        try {
            const res = await apiFetch('/api/archivos/descargar-todo?estado=aprobadas');
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || 'No se pudo generar el álbum');
            }
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `freeport_aprobadas_${Date.now()}.zip`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (e) {
            alert(e.message || 'No se pudo descargar el álbum');
        } finally {
            btn.disabled = false;
            btn.innerHTML = textoOriginal;
        }
    });
}

// =========================================================
// NUEVO EVENTO
// =========================================================
function inicializarNuevoEvento() {
    const modal = document.getElementById('modalNuevoEvento');
    const input = document.getElementById('inputConfirmarBorrado');
    const btnConfirmar = document.getElementById('btnConfirmarEvento');
    const btnNuevo = document.getElementById('btnNuevoEvento');
    const btnCancelar = document.getElementById('btnCancelarEvento');

    if (!modal || !input || !btnConfirmar || !btnNuevo) return;

    btnNuevo.addEventListener('click', () => {
        input.value = '';
        btnConfirmar.disabled = true;
        modal.hidden = false;
    });

    if (btnCancelar) {
        btnCancelar.addEventListener('click', () => { modal.hidden = true; });
    }

    input.addEventListener('input', () => {
        btnConfirmar.disabled = input.value.trim().toUpperCase() !== 'BORRAR';
    });

    btnConfirmar.addEventListener('click', async () => {
        if (input.value.trim().toUpperCase() !== 'BORRAR') return;
        btnConfirmar.disabled = true;
        btnConfirmar.textContent = 'Borrando...';
        try {
            const res = await apiFetch('/api/evento/nuevo', { method: 'POST' });
            if (res.ok) {
                location.reload();
            } else {
                alert('No se pudo reiniciar el evento.');
            }
        } catch (e) {
            alert('Error de conexión al reiniciar el evento.');
        } finally {
            btnConfirmar.textContent = 'Sí, borrar todo';
        }
    });
}