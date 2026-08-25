// ===================================================================
// FREEPORT MOMENTS - LOGIN JS
// Manejo de autenticacion admin, con feedback claro ante mala señal,
// servidor caido, o bloqueo temporal por intentos fallidos.
// ===================================================================

const formLogin = document.getElementById('loginForm');
const inputUsuario = document.getElementById('usuario');
const inputPassword = document.getElementById('password');
const btnMostrar = document.getElementById('btnMostrarPassword');
const errorDiv = document.getElementById('loginError');
const errorTexto = document.getElementById('loginErrorTexto');
const btnLogin = document.getElementById('btnLogin');
const bannerOffline = document.getElementById('bannerOffline');
const puntoEstado = document.getElementById('puntoEstado');
const textoEstado = document.getElementById('textoEstado');

// =========================================================
// ESTADO DE CONEXION
// =========================================================
function actualizarEstadoConexion() {
    const online = navigator.onLine;
    bannerOffline.hidden = online;
    puntoEstado.classList.toggle('rojo', !online);
    puntoEstado.classList.toggle('verde', online);
    textoEstado.textContent = online ? 'Sistema activo' : 'Sin conexión';
}
window.addEventListener('online', actualizarEstadoConexion);
window.addEventListener('offline', actualizarEstadoConexion);
actualizarEstadoConexion();

// =========================================================
// MOSTRAR / OCULTAR PASSWORD
// =========================================================
btnMostrar.addEventListener('click', () => {
    const esPassword = inputPassword.type === 'password';
    inputPassword.type = esPassword ? 'text' : 'password';
    btnMostrar.textContent = esPassword ? 'Ocultar' : 'Mostrar';
});

// =========================================================
// LOGIN
// =========================================================
formLogin.addEventListener('submit', async (e) => {
    e.preventDefault();

    const usuario = inputUsuario.value.trim();
    const password = inputPassword.value.trim();

    if (!usuario || !password) {
        mostrarError('Completá ambos campos');
        return;
    }

    if (!navigator.onLine) {
        mostrarError('Sin conexión a internet. Esperá a reconectar e intentá de nuevo.');
        return;
    }

    btnLogin.disabled = true;
    btnLogin.textContent = 'Entrando...';
    ocultarError();

    try {
        const respuesta = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ usuario, password }),
        });

        let datos = {};
        try {
            datos = await respuesta.json();
        } catch {
            datos = {};
        }

        if (respuesta.ok && datos.ok) {
            window.location.href = '/admin';
            return;
        }

        if (respuesta.status === 429) {
            mostrarError(datos.detail || 'Demasiados intentos. Esperá unos minutos e intentá de nuevo.');
        } else if (respuesta.status === 401) {
            mostrarError(datos.detail || 'Usuario o contraseña incorrectos');
        } else {
            mostrarError('No se pudo iniciar sesión. Intentá de nuevo.');
        }
    } catch (error) {
        mostrarError('Error de conexión con el servidor. Verificá tu red e intentá de nuevo.');
    } finally {
        btnLogin.disabled = false;
        btnLogin.textContent = 'Entrar';
    }
});

// =========================================================
// ERRORES
// =========================================================
function mostrarError(mensaje) {
    errorTexto.textContent = mensaje;
    errorDiv.hidden = false;
}

function ocultarError() {
    errorDiv.hidden = true;
}

inputUsuario.addEventListener('input', ocultarError);
inputPassword.addEventListener('input', ocultarError);
