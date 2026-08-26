// ===================================================================
// FREEPORT MOMENTS - GUEST JS - ULTRA RAPIDO
// UNICA SOLUCION MAS EFICIENTE: 8MB + 3x PARALELO
// ===================================================================

const inputArchivos = document.getElementById('inputArchivos');
const botonSubir = document.getElementById('botonSubir');
const modalProgreso = document.getElementById('modalProgreso');
const modalExito = document.getElementById('modalExito');
const modalError = document.getElementById('modalError');
const progresoBarra = document.getElementById('progresoBarra');
const progresoTexto = document.getElementById('progresoTexto');
const progresoLista = document.getElementById('progresoLista');
const progresoNota = document.getElementById('progresoNota');
const fondoImagen = document.getElementById('fondoImagen');
const botonGoogle = document.getElementById('botonGoogle');
const bannerOffline = document.getElementById('bannerOffline');
const botonReintentar = document.getElementById('botonReintentar');

let configuracionPublica = null;
let archivosFallidos = [];

// =========================================================
// INICIALIZACION
// =========================================================
document.addEventListener('DOMContentLoaded', () => {
    inicializarEventos();
    cargarConfiguracionPublica();
    iniciarContadorConectados();
    actualizarBannerConexion();
});

window.addEventListener('online', actualizarBannerConexion);
window.addEventListener('offline', actualizarBannerConexion);

function actualizarBannerConexion() {
    bannerOffline.hidden = navigator.onLine;
}

// =========================================================
// ESPERAR RECONEXION
// =========================================================
function esperarConexion() {
    if (navigator.onLine) return Promise.resolve();
    return new Promise((resolve) => {
        const handler = () => {
            window.removeEventListener('online', handler);
            resolve();
        };
        window.addEventListener('online', handler);
    });
}

function esperar(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

// =========================================================
// FETCH CON REINTENTOS Y BACKOFF EXPONENCIAL
// =========================================================
async function fetchConReintentos(url, opciones = {}, maxIntentos = 5, onReintento = null) {
    let intento = 0;
    while (true) {
        await esperarConexion();
        try {
            const respuesta = await fetch(url, opciones);

            if (respuesta.status === 429 || respuesta.status >= 500) {
                if (intento >= maxIntentos - 1) return respuesta;
                intento++;
                if (onReintento) onReintento(intento);
                await esperar(Math.min(1000 * 2 ** intento, 15000) + Math.random() * 400);
                continue;
            }

            return respuesta;
        } catch (error) {
            if (intento >= maxIntentos - 1) throw error;
            intento++;
            if (onReintento) onReintento(intento);
            await esperar(Math.min(1000 * 2 ** intento, 15000) + Math.random() * 400);
        }
    }
}

// =========================================================
// CARGAR CONFIGURACION PUBLICA
// =========================================================
async function cargarConfiguracionPublica() {
    try {
        const respuesta = await fetchConReintentos('/api/configuracion/publica', {}, 3);
        if (respuesta.ok) {
            configuracionPublica = await respuesta.json();
            aplicarConfiguracion();
        }
    } catch (error) {
        aplicarConfiguracionPorDefecto();
    }
}

function aplicarConfiguracion() {
    if (!configuracionPublica) return;

    if (configuracionPublica.fondo_url) {
        fondoImagen.style.backgroundImage = `url('${configuracionPublica.fondo_url}')`;
    }

    const logo = document.getElementById('logoImagen');
    if (logo && configuracionPublica.logo_url) {
        logo.src = configuracionPublica.logo_url;
    }

    if (configuracionPublica.google_link) {
        botonGoogle.href = configuracionPublica.google_link;
    }

    if (configuracionPublica.titulo_evento) {
        document.title = `${configuracionPublica.titulo_evento} - Freeport Moments`;
    }
}

function aplicarConfiguracionPorDefecto() {
    fondoImagen.style.backgroundImage = "url('/assets/background.jpg')";
}

// =========================================================
// EVENTOS DE LA UI
// =========================================================
function inicializarEventos() {
    botonSubir.addEventListener('click', () => inputArchivos.click());

    inputArchivos.addEventListener('change', (e) => {
        const archivos = Array.from(e.target.files);
        if (archivos.length > 0) procesarArchivos(archivos);
    });

    botonSubir.addEventListener('dragover', (e) => {
        e.preventDefault();
        botonSubir.classList.add('arrastrando');
    });
    botonSubir.addEventListener('dragleave', () => botonSubir.classList.remove('arrastrando'));
    botonSubir.addEventListener('drop', (e) => {
        e.preventDefault();
        botonSubir.classList.remove('arrastrando');
        const archivos = Array.from(e.dataTransfer.files);
        if (archivos.length > 0) procesarArchivos(archivos);
    });

    document.getElementById('botonCerrarExito').addEventListener('click', cerrarModalExito);
    document.getElementById('botonCerrarError').addEventListener('click', cerrarModalError);
    botonReintentar.addEventListener('click', () => {
        cerrarModalError();
        if (archivosFallidos.length > 0) {
            const paraReintentar = [...archivosFallidos];
            archivosFallidos = [];
            procesarArchivos(paraReintentar);
        }
    });
}

// =========================================================
// PROCESAR ARCHIVOS - COLA SECUENCIAL DE ARCHIVOS
// (cada archivo sigue siendo secuencial, pero sus bloques van en paralelo)
// =========================================================
async function procesarArchivos(archivos) {
    if (archivos.length === 0) return;

    mostrarModalProgreso(archivos.length);

    let completados = 0;
    let fallidos = 0;
    const fallidosDeEstaTanda = [];
    let huboReintentos = false;

    // UNICA OPTIMIZACION: Baja el umbral para que use el sistema rapido antes
    const umbralFragmentado = 5 * 1024 * 1024; // antes 10MB, ahora 5MB

    for (let i = 0; i < archivos.length; i++) {
        const archivo = archivos[i];
        try {
            actualizarProgresoItem(archivo.name, 'subiendo');

            const marcarReintento = () => {
                huboReintentos = true;
                progresoNota.hidden = false;
                actualizarProgresoItem(archivo.name, 'reintentando');
            };

            if (archivo.size > umbralFragmentado) {
                await subirPorBloques(archivo, marcarReintento);
            } else {
                await subirArchivoSimple(archivo, marcarReintento);
            }

            completados++;
            actualizarProgresoItem(archivo.name, 'ok');
        } catch (error) {
            fallidos++;
            fallidosDeEstaTanda.push(archivo);
            actualizarProgresoItem(archivo.name, 'error');
        }

        const porcentaje = ((completados + fallidos) / archivos.length) * 100;
        progresoBarra.style.width = `${porcentaje}%`;
        progresoTexto.textContent = `${completados + fallidos} de ${archivos.length} archivos`;
    }

    setTimeout(() => {
        cerrarModalProgreso();
        progresoNota.hidden = true;

        if (fallidos === 0) {
            mostrarModalExito(completados);
        } else if (completados === 0) {
            archivosFallidos = fallidosDeEstaTanda;
            mostrarError('No se pudo subir ningún archivo', 'Revisá tu conexión e intentá de nuevo.', true);
        } else {
            archivosFallidos = fallidosDeEstaTanda;
            mostrarError(`Se subieron ${completados} de ${archivos.length}`, `${fallidos} no se pudieron subir. Podés reintentar solo esos.`, true);
        }

        inputArchivos.value = '';
    }, 500);
}

async function subirArchivoSimple(archivo, onReintento) {
    const formData = new FormData();
    formData.append('archivo', archivo);

    const respuesta = await fetchConReintentos('/api/subida', { method: 'POST', body: formData }, 5, onReintento);

    if (!respuesta.ok) {
        let detalle = 'Error en subida';
        try {
            const error = await respuesta.json();
            detalle = error.detail || detalle;
        } catch { /* respuesta no era JSON */ }
        throw new Error(detalle);
    }
    return respuesta.json();
}

// =========================================================
// SUBIDA POR BLOQUES - ULTRA RAPIDA
// 8MB por bloque + 3 bloques en paralelo
// =========================================================
async function subirPorBloques(archivo, onReintento) {
    const tamanoBloque = 8 * 1024 * 1024; // 8MB - antes 2MB
    const totalBloques = Math.ceil(archivo.size / tamanoBloque);
    const idSubida = `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
    const CONCURRENCIA = 4; // 4 chunks a la vez (el servidor ya los escribe en paralelo real)

    let bloquesCompletados = 0;

    // Funcion interna que sube 1 bloque con reintentos
    async function subirUnBloque(bloque) {
        const inicio = bloque * tamanoBloque;
        const fin = Math.min(inicio + tamanoBloque, archivo.size);
        const pedazo = archivo.slice(inicio, fin);

        const formData = new FormData();
        formData.append('bloque', pedazo);
        formData.append('id_subida', idSubida);
        formData.append('indice_bloque', bloque);
        formData.append('total_bloques', totalBloques);
        formData.append('nombre_original', archivo.name);
        formData.append('tipo_archivo', archivo.type);

        const respuesta = await fetchConReintentos(
            '/api/subida/fragmentada', { method: 'POST', body: formData }, 5, onReintento
        );

        if (!respuesta.ok) {
            let detalle = `Error en bloque ${bloque + 1}/${totalBloques}`;
            try {
                const error = await respuesta.json();
                detalle = error.detail || detalle;
            } catch { /* no era JSON */ }
            throw new Error(detalle);
        }

        bloquesCompletados++;
        const pct = Math.round((bloquesCompletados / totalBloques) * 100);
        actualizarProgresoItem(archivo.name, 'subiendo', `${archivo.name} (${pct}%)`);
    }

    // Lanza en lotes paralelos
    for (let i = 0; i < totalBloques; i += CONCURRENCIA) {
        const lote = [];
        for (let j = 0; j < CONCURRENCIA && i + j < totalBloques; j++) {
            lote.push(subirUnBloque(i + j));
        }
        await Promise.all(lote); // espera que terminen las 3 antes de seguir
    }
}

// =========================================================
// MODALES - UI
// =========================================================
function mostrarModalProgreso(total) {
    progresoBarra.style.width = '0%';
    progresoTexto.textContent = `0 de ${total} archivos`;
    progresoLista.innerHTML = '';
    progresoNota.hidden = true;
    modalProgreso.hidden = false;
}

function cerrarModalProgreso() {
    modalProgreso.hidden = true;
}

function actualizarProgresoItem(nombre, estado, textoPersonalizado = null) {
    let item = document.getElementById(`progreso-${nombre}`);
    if (!item) {
        item = document.createElement('div');
        item.id = `progreso-${nombre}`;
        item.className = 'progreso-item';
        progresoLista.appendChild(item);
    }
    let icono = '⏳';
    if (estado === 'ok') icono = '✓';
    if (estado === 'error') icono = '✕';
    if (estado === 'reintentando') icono = '↻';

    item.textContent = `${icono} ${textoPersonalizado || nombre}`;
    item.className = `progreso-item ${estado}`;
}

function mostrarModalExito(cantidad) {
    document.getElementById('exitoSubtitulo').textContent =
        cantidad === 1 ? 'Tu momento ya está con nosotros' : `Tus ${cantidad} momentos ya están con nosotros`;
    modalExito.hidden = false;
    setTimeout(cerrarModalExito, 4000);
}

function cerrarModalExito() {
    modalExito.hidden = true;
}

function mostrarError(titulo, mensaje, permitirReintentar) {
    document.getElementById('errorTitulo').textContent = titulo;
    document.getElementById('errorMensaje').textContent = mensaje;
    botonReintentar.hidden = !permitirReintentar;
    modalError.hidden = false;
}

function cerrarModalError() {
    modalError.hidden = true;
}

// =========================================================
// PING DE CONECTADOS PARA EL ADMIN
// =========================================================
function iniciarContadorConectados() {
    const ping = () => {
        if (!navigator.onLine) return;
        fetch('/api/guest/ping', { method: 'POST' }).catch(() => { /* silencioso */ });
    };
    ping();
    setInterval(ping, 30000);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') ping();
    });
}
