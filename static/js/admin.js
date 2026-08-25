// ===================================================================
// FREEPORT MOMENTS - ADMIN JS - ACTUALIZADO CON RELOJ Y EDITOR TITULO
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
    inicializarReloj();
    inicializarEdicionTitulo();
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

// ================= RELOJ EN VIVO =================
function inicializarReloj() {
    actualizarFechaHoraActual();
    setInterval(actualizarFechaHoraActual, 1000);
}

function actualizarFechaHoraActual() {
    const ahora = new Date();
    // Fecha actual siempre
    const fechaStr = ahora.toLocaleDateString('es-AR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
    // Hora reloj contando segundos
    const horaStr = ahora.toLocaleTimeString('es-AR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    }) + ' hs';

    setTexto('fechaEvento', fechaStr);
    setTexto('horaEvento', horaStr);
}

// ================= EDITAR TITULO =================
function inicializarEdicionTitulo() {
    const btnEditar = document.getElementById('btnEditarTitulo');
    const modal = document.getElementById('modalEditarTitulo');
    const input = document.getElementById('inputTituloEvento');
    const btnCancelar = document.getElementById('btnCancelarTitulo');
    const btnGuardar = document.getElementById('btnGuardarTitulo');
    const nombreEl = document.getElementById('nombreEvento');

    if (!btnEditar || !modal || !input) return;

    const abrirModal = () => {
        input.value = nombreEl.textContent.trim() === 'Sin configurar' ? '' : nombreEl.textContent.trim();
        modal.hidden = false;
        setTimeout(() => { input.focus(); input.select(); }, 50);
    };

    btnEditar.addEventListener('click', abrirModal);
    nombreEl.addEventListener('click', abrirModal);

    const cerrarModal = () => { modal.hidden = true; };

    if (btnCancelar) btnCancelar.addEventListener('click', cerrarModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) cerrarModal(); });

    document.addEventListener('keydown', (e) => {
        if (!modal.hidden && e.key === 'Escape') cerrarModal();
        if (!modal.hidden && e.key === 'Enter') btnGuardar.click();
    });

    btnGuardar.addEventListener('click', async () => {
        const nuevoNombre = input.value.trim();
        if (!nuevoNombre) { alert('El título no puede estar vacío'); return; }
        if (nuevoNombre.length < 2 || nuevoNombre.length > 100) {
            alert('El título debe tener entre 2 y 100 caracteres');
            return;
        }
        btnGuardar.disabled = true;
        const textoOrig = btnGuardar.textContent;
        btnGuardar.textContent = 'Guardando...';
        try {
            const res = await apiFetch('/api/evento/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nombre: nuevoNombre }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || 'Error al guardar');
            }
            setTexto('nombreEvento', nuevoNombre);
            modal.hidden = true;
            // Feedback visual
            nombreEl.style.transition = 'color 0.3s';
            nombreEl.style.color = '#4ade80';
            setTimeout(() => nombreEl.style.color = '', 800);
        } catch (e) {
            alert('No se pudo guardar: ' + e.message);
        } finally {
            btnGuardar.disabled = false;
            btnGuardar.textContent = textoOrig;
        }
    });
}

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
        } catch { }
        window.location.href = '/login';
    });
}

// =========================================================
// ESTADISTICAS - AHORA NO SOBRESCRIBE FECHA/HORA
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
            // Solo actualizamos nombre, fecha/hora las maneja el reloj vivo
            if (stats.evento.nombre) {
                setTexto('nombreEvento', stats.evento.nombre || 'Sin configurar');
            }
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
            galeriaGrid.innerHTML = `<div class="galeria-error">Error al cargar: ${e.message}</div>`;
        }
    }
}

function renderizarGaleria(archivos) {
    if (!archivos || archivos.length === 0) {
        galeriaGrid.innerHTML = `
            <div class="galeria-vacio">
                <div class="vacio-icono">📷</div>
                <h3 class="vacio-titulo">Aún no hay archivos</h3>
                <p class="vacio-texto">Los momentos que suban tus invitados aparecerán aquí.</p>
            </div>`;
        return;
    }

    galeriaGrid.innerHTML = '';
    archivos.forEach((archivo, idx) => {
        const card = document.createElement('div');
        card.className = 'media-card';
        const esVideo = /\.(mp4|mov|avi|mkv|webm|m4v)$/i.test(archivo.nombre);
        const thumb = archivo.thumbnail_url || `/uploads/${seccionActual}/${encodeURIComponent(archivo.nombre)}`;
        card.innerHTML = `
            ${esVideo ? `<video class="media-thumb" src="/uploads/${seccionActual}/${encodeURIComponent(archivo.nombre)}" muted></video><span class="media-badge">VIDEO</span>` : `<img class="media-thumb" src="${thumb}" alt="" loading="lazy">`}
            <div class="media-info">
                <span class="media-nombre" title="${archivo.nombre}">${archivo.nombre_original || archivo.nombre}</span>
                <span class="media-fecha">${archivo.fecha || ''}</span>
            </div>
        `;
        card.addEventListener('click', () => abrirVisor(idx));
        galeriaGrid.appendChild(card);
    });
}

// =========================================================
// VISOR
// =========================================================
function inicializarVisor() {
    document.getElementById('visorCerrar').addEventListener('click', cerrarVisor);
    document.getElementById('visorAnterior').addEventListener('click', () => navegarVisor(-1));
    document.getElementById('visorSiguiente').addEventListener('click', () => navegarVisor(1));
    document.getElementById('visorAprobar').addEventListener('click', () => accionarArchivo('aprobar'));
    document.getElementById('visorRechazar').addEventListener('click', () => accionarArchivo('rechazar'));
    document.getElementById('visorDescargar').addEventListener('click', () => accionarArchivo('descargar'));
    document.getElementById('visorEliminar').addEventListener('click', () => {
        archivoAEliminar = archivosActuales[archivoActualIndex];
        document.getElementById('modalEliminarArchivo').hidden = false;
    });
    visorOverlay.addEventListener('click', (e) => { if (e.target === visorOverlay) cerrarVisor(); });
    document.addEventListener('keydown', (e) => {
        if (visorOverlay.hidden) return;
        if (e.key === 'Escape') cerrarVisor();
        if (e.key === 'ArrowLeft') navegarVisor(-1);
        if (e.key === 'ArrowRight') navegarVisor(1);
    });
}

function abrirVisor(idx) {
    archivoActualIndex = idx;
    mostrarArchivoEnVisor();
    visorOverlay.hidden = false;
}

function cerrarVisor() {
    visorOverlay.hidden = true;
    if (visorVideo) { visorVideo.pause(); visorVideo.hidden = true; visorVideo.src = ''; }
    visorImagen.src = '';
}

function navegarVisor(dir) {
    if (!archivosActuales.length) return;
    archivoActualIndex = (archivoActualIndex + dir + archivosActuales.length) % archivosActuales.length;
    mostrarArchivoEnVisor();
}

function mostrarArchivoEnVisor() {
    const archivo = archivosActuales[archivoActualIndex];
    if (!archivo) return;
    const esVideo = /\.(mp4|mov|avi|mkv|webm|m4v)$/i.test(archivo.nombre);
    visorNombre.textContent = archivo.nombre_original || archivo.nombre;
    visorContador.textContent = `${archivoActualIndex + 1} / ${archivosActuales.length}`;

    if (esVideo) {
        visorImagen.hidden = true;
        visorVideo.hidden = false;
        visorVideo.src = `/uploads/${seccionActual}/${encodeURIComponent(archivo.nombre)}`;
        visorVideo.load();
    } else {
        visorVideo.hidden = true;
        visorVideo.pause();
        visorImagen.hidden = false;
        visorImagen.src = `/uploads/${seccionActual}/${encodeURIComponent(archivo.nombre)}`;
    }
}

async function accionarArchivo(accion) {
    const archivo = archivosActuales[archivoActualIndex];
    if (!archivo) return;
    try {
        if (visorVideo && !visorVideo.hidden) {
            visorVideo.pause();
            visorVideo.src = '';
            visorVideo.load();
        }
        await new Promise(r => setTimeout(r, 200));
        const res = await apiFetch('/api/archivos/accion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nombre: archivo.nombre, estado_actual: seccionActual, accion }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);

        if (accion === 'descargar') {
            window.location.href = `/api/archivos/descargar?archivo=${encodeURIComponent(archivo.nombre)}&estado=${seccionActual}`;
        } else {
            quitarArchivoDeListaActual();
            cargarEstadisticas();
        }
    } catch (e) {
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
    if (btnCancelar) btnCancelar.addEventListener('click', () => { modal.hidden = true; });
    input.addEventListener('input', () => {
        btnConfirmar.disabled = input.value.trim().toUpperCase() !== 'BORRAR';
    });
    btnConfirmar.addEventListener('click', async () => {
        if (input.value.trim().toUpperCase() !== 'BORRAR') return;
        btnConfirmar.disabled = true;
        btnConfirmar.textContent = 'Borrando...';
        try {
            const res = await apiFetch('/api/evento/nuevo', { method: 'POST' });
            if (res.ok) location.reload();
            else alert('No se pudo reiniciar el evento.');
        } catch (e) {
            alert('Error de conexión al reiniciar el evento.');
        } finally {
            btnConfirmar.textContent = 'Sí, borrar todo';
        }
    });
}
