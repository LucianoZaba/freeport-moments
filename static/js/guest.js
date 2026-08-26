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
// XHR CON REINTENTOS Y PROGRESO REAL DE BYTES
// (fetch no reporta progreso de subida; XHR sí)
// =========================================================
function xhrConReintentos(url, formData, onProgresoBytes, maxIntentos = 5, onReintento = null) {
    return new Promise((resolve, reject) => {
        let intento = 0;

        const intentarUnaVez = () => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url);

            if (onProgresoBytes) {
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) onProgresoBytes(e.loaded);
                });
            }

            xhr.onload = () => {
                if (xhr.status === 429 || xhr.status >= 500) {
                    reintentar();
                    return;
                }
                let datos = null;
                try { datos = JSON.parse(xhr.responseText); } catch { /* no era JSON */ }
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(datos);
                } else {
                    reject(new Error((datos && datos.detail) || 'Error en subida'));
                }
            };

            xhr.onerror = () => reintentar();

            xhr.send(formData);
        };

        const reintentar = () => {
            if (intento >= maxIntentos - 1) {
                reject(new Error('No se pudo conectar con el servidor'));
                return;
            }
            intento++;
            if (onReintento) onReintento(intento);
            if (onProgresoBytes) onProgresoBytes(0); // este intento arranca de nuevo
            esperarConexion()
                .then(() => esperar(Math.min(1000 * 2 ** intento, 15000) + Math.random() * 400))
                .then(intentarUnaVez);
        };

        esperarConexion().then(intentarUnaVez);
    });
}


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
// La barra de arriba ahora refleja BYTES reales subidos de todo el lote,
// no cantidad de archivos, para que un video grande muestre su avance.
// =========================================================
let bytesTotalLote = 0;
let bytesConfirmados = 0;
let bytesEnVuelo = {};

function actualizarBarraGlobal() {
    const enVuelo = Object.values(bytesEnVuelo).reduce((a, b) => a + b, 0);
    const total = Math.min(bytesTotalLote, bytesConfirmados + enVuelo);
    const pct = bytesTotalLote > 0 ? Math.round((total / bytesTotalLote) * 100) : 0;
    progresoBarra.style.width = `${pct}%`;
    progresoTexto.textContent = `${pct}%`;
}

async function procesarArchivos(archivos) {
    if (archivos.length === 0) return;

    mostrarModalProgreso(archivos.length);

    bytesTotalLote = archivos.reduce((acc, a) => acc + a.size, 0);
    bytesConfirmados = 0;
    bytesEnVuelo = {};

    let completados = 0;
    let fallidos = 0;
    const fallidosDeEstaTanda = [];

    // UNICA OPTIMIZACION: Baja el umbral para que use el sistema rapido antes
    const umbralFragmentado = 5 * 1024 * 1024; // antes 10MB, ahora 5MB

    for (let i = 0; i < archivos.length; i++) {
        const archivo = archivos[i];
        try {
            actualizarProgresoItem(archivo.name, 'subiendo', `${archivo.name} (0%)`);

            const marcarReintento = () => {
                progresoNota.hidden = false;
                actualizarProgresoItem(archivo.name, 'reintentando');
            };

            if (archivo.size > umbralFragmentado) {
                await subirPorBloques(archivo, marcarReintento);
            } else {
                await subirArchivoSimple(archivo, marcarReintento);
            }

            bytesConfirmados += archivo.size;
            delete bytesEnVuelo[archivo.name];
            completados++;
            actualizarProgresoItem(archivo.name, 'ok');
        } catch (error) {
            delete bytesEnVuelo[archivo.name];
            bytesConfirmados += archivo.size; // se cuenta como "resuelto" para que la barra no se trabe
            fallidos++;
            fallidosDeEstaTanda.push(archivo);
            actualizarProgresoItem(archivo.name, 'error');
        }

        actualizarBarraGlobal();
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

    await xhrConReintentos('/api/subida', formData, (loaded) => {
        bytesEnVuelo[archivo.name] = loaded;
        const pct = Math.round((loaded / archivo.size) * 100);
        actualizarProgresoItem(archivo.name, 'subiendo', `${archivo.name} (${pct}%)`);
        actualizarBarraGlobal();
    }, 5, onReintento);
}

// =========================================================
// SUBIDA POR BLOQUES - ULTRA RAPIDA
// 8MB por bloque + 4 bloques en paralelo, con progreso real de bytes
// =========================================================
async function subirPorBloques(archivo, onReintento) {
    const tamanoBloque = 8 * 1024 * 1024; // 8MB
    const totalBloques = Math.ceil(archivo.size / tamanoBloque);
    const idSubida = `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
    const CONCURRENCIA = 4; // 4 chunks a la vez (el servidor ya los escribe en paralelo real)

    let bytesConfirmadosArchivo = 0;

    function actualizarItemArchivo() {
        const enVueloArchivo = Object.entries(bytesEnVuelo)
            .filter(([clave]) => clave.startsWith(`${archivo.name}#`))
            .reduce((a, [, v]) => a + v, 0);
        const totalArchivo = Math.min(archivo.size, bytesConfirmadosArchivo + enVueloArchivo);
        const pct = Math.round((totalArchivo / archivo.size) * 100);
        actualizarProgresoItem(archivo.name, 'subiendo', `${archivo.name} (${pct}%)`);
        bytesEnVuelo[archivo.name] = totalArchivo; // para la barra global
        actualizarBarraGlobal();
    }

    async function subirUnBloque(bloque) {
        const inicio = bloque * tamanoBloque;
        const fin = Math.min(inicio + tamanoBloque, archivo.size);
        const pedazo = archivo.slice(inicio, fin);
        const claveBloque = `${archivo.name}#${bloque}`;

        const formData = new FormData();
        formData.append('bloque', pedazo);
        formData.append('id_subida', idSubida);
        formData.append('indice_bloque', bloque);
        formData.append('total_bloques', totalBloques);
        formData.append('nombre_original', archivo.name);
        formData.append('tipo_archivo', archivo.type);

        await xhrConReintentos('/api/subida/fragmentada', formData, (loaded) => {
            bytesEnVuelo[claveBloque] = loaded;
            actualizarItemArchivo();
        }, 5, onReintento);

        delete bytesEnVuelo[claveBloque];
        bytesConfirmadosArchivo += (fin - inicio);
        actualizarItemArchivo();
    }

    // Lanza en lotes paralelos
    for (let i = 0; i < totalBloques; i += CONCURRENCIA) {
        const lote = [];
        for (let j = 0; j < CONCURRENCIA && i + j < totalBloques; j++) {
            lote.push(subirUnBloque(i + j));
        }
        await Promise.all(lote); // espera que terminen antes de seguir con el siguiente lote
    }
}

// =========================================================
// MODALES - UI
// =========================================================
function mostrarModalProgreso(total) {
    progresoBarra.style.width = '0%';
    progresoTexto.textContent = '0%';
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
