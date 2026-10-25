/* Utilidades compartidas por todas las páginas de dIAra
   Se carga antes que el resto de scripts en todas las páginas.
   JavaScript sin frameworks ni compilación: se escribe en ES5 con funciones globales, para que funcione en cualquier
   navegador y se pueda editar directo. Contenido:
     $ / $$         atajos de querySelector / querySelectorAll
     esc()          escapa texto antes de insertarlo como HTML (OBLIGATORIO para todo dato que venga de la API)
     toast()        aviso flotante breve
     api()          llamada a la API con la cookie de sesión
     graficoAvance  gráfico SVG de avance previsto vs. observado
     claseEstado    clase de color para el texto de estado de una obra */
var $ = function (s, r) { return (r || document).querySelector(s) };
var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)) };
var CON_SERVIDOR = location.protocol.indexOf("http") === 0;  /* false si se abre con doble clic */

/* Evita inyección de HTML (XSS): nombres, textos de aportes, etc. siempre pasan por esc() antes de ir a innerHTML */
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] }) }

/* Requiere un elemento <div id="toast"> en la página */
function toast(t) { var e = $("#toast"); e.textContent = t; e.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { e.classList.remove("on") }, 2800) }

/* Llamada a la API. Envía la cookie de sesión; si es 401 en el panel, vuelve al login. */
/* Uso: api("/api/..."), api(ruta, { json: {...} }) (POST con JSON), api(ruta, { method: "PATCH", json: {...} }),
   api(ruta, { method: "POST", body: formData }) (archivos). Devuelve una promesa con el JSON de respuesta;
   si la respuesta no es 2xx, la promesa se rechaza con Error(mensaje del servidor en "detail"). */
function api(ruta, opciones) {
  opciones = opciones || {};
  if (opciones.json) { opciones.method = opciones.method || "POST"; opciones.headers = { "Content-Type": "application/json" }; opciones.body = JSON.stringify(opciones.json) }
  return fetch(ruta, { method: opciones.method || "GET", headers: opciones.headers, body: opciones.body, credentials: "same-origin" })
    .then(function (r) {
      /* Sesión vencida dentro de un panel: al login. El Error("sesion") lo ignoran los .catch de las páginas */
      if (r.status === 401 && /^\/(auditor|admin|proyecto|contratista)/.test(location.pathname)) { location.href = "/login"; throw new Error("sesion") }
      return r.json().catch(function () { return {} }).then(function (j) { if (!r.ok) throw new Error(j.detail || "Error " + r.status); return j })
    })
}

/* Gráfico SVG de avance previsto vs observado a partir de la serie diaria [{f, prev, obs}] */
/* Coordenadas en un lienzo de 480x220: X reparte los días entre 40 y 460; Y convierte 0-100 % a 180-20 (el SVG crece hacia abajo).
   Los colores usan variables CSS, así el gráfico respeta el modo claro/oscuro. */
function graficoAvance(serie, brecha) {
  /* Datos reales sin medición de avance (prev/obs en null): mensaje en lugar del gráfico */
  serie = serie.filter(function (r) { return r.prev != null && r.obs != null });
  if (serie.length < 2) return '<p class="vacio-msg">⚪ El avance físico aún no se mide en esta obra: la IA actual cuenta personas y vehículos en las fotos. ' +
    "Medir el avance requiere entrenar el modelo con fotos etiquetadas de la obra.</p>";
  var n = serie.length, X = function (i) { return 40 + 420 * i / (n - 1) }, Y = function (v) { return 180 - 1.6 * v };
  var linea = function (c) { return serie.map(function (r, i) { return X(i).toFixed(1) + "," + Y(r[c]).toFixed(1) }).join(" ") };
  var et = [0, Math.floor((n - 1) / 2), n - 1].map(function (i) { return '<text x="' + (X(i) - 14) + '" y="200">' + serie[i].f.slice(8) + "/" + serie[i].f.slice(5, 7) + "</text>" }).join("");  /* 3 fechas: inicio, medio y fin */
  var u = serie[n - 1], xu = X(n - 1);
  return '<svg class="chart" viewBox="0 0 480 220" role="img" aria-label="Avance previsto frente a observado">' +
    '<g stroke="var(--bd)"><line x1="40" y1="20" x2="40" y2="180"/><line x1="40" y1="180" x2="470" y2="180"/><line x1="40" y1="100" x2="470" y2="100" stroke-dasharray="3 4"/></g>' +
    '<g font-size="10" fill="var(--mu)" font-family="sans-serif"><text x="8" y="24">100%</text><text x="14" y="104">50%</text><text x="22" y="184">0%</text>' + et + "</g>" +
    '<polyline fill="none" stroke="var(--pr)" stroke-width="3" points="' + linea("prev") + '"/>' +
    '<polyline fill="none" stroke="var(--wa)" stroke-width="3" stroke-dasharray="6 4" points="' + linea("obs") + '"/>' +
    '<line x1="' + xu + '" y1="' + Y(u.prev) + '" x2="' + xu + '" y2="' + Y(u.obs) + '" stroke="var(--al)" stroke-width="2"/>' +
    '<text x="300" y="30" font-size="12" font-weight="700" fill="var(--al)" font-family="sans-serif">Brecha: ' + brecha + " pts</text></svg>" +
    '<div class="leg"><span><i style="background:var(--pr)"></i>Previsto (cronograma)</span><span><i style="background:var(--wa)"></i>Observado (IA)</span></div>'
}

/* El backend devuelve el estado con un emoji al inicio ("🔴 Atrasada", "🟠 Con retraso leve", "🟢 Según lo previsto") */
function claseEstado(e) { return e.indexOf("🔴") === 0 ? "b-r" : e.indexOf("🟠") === 0 ? "b-o" : e.indexOf("⚪") === 0 ? "b-n" : "b-g" }  /* ⚪ = avance sin medición */
