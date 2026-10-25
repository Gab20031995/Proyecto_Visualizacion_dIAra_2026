/* Utilidades compartidas por los paneles (auditor y administración). Requiere common.js */
/* La usan auditor.html, proyecto.html, admin.html y contratista.html. Al cargarse ya enlaza el botón #salir, la ventana #modal y la tecla
   Escape, así que esas páginas deben tener elementos con esos id. */
var DOW = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
var MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
/* "2026-10-24" -> "24/10/2026" (se trabaja con texto para no depender de la zona horaria del navegador) */
function fmtFecha(f) { var p = String(f).slice(0, 10).split("-"); return p[2] + "/" + p[1] + "/" + p[0] }
/* "T12:00" evita que, según la zona horaria, la fecha caiga en el día anterior */
function diaSemana(f) { return DOW[new Date(f + "T12:00").getDay()] }
/* Tarjeta de indicador. tono: "mal" (rojo), "bien" (verde) o vacío; ayuda: texto al pasar el mouse */
function kpi(t, v, tono, ayuda) { return '<div class="card kpi' + (tono ? " " + tono : "") + '"' + (ayuda ? ' title="' + esc(ayuda) + '"' : "") + "><b>" + esc(v) + '</b><span class="mu">' + esc(t) + "</span></div>" }

/* Altura real del encabezado (en móvil puede ocupar dos líneas) para ubicar el menú pegajoso */
/* Se guarda en la variable CSS --cab (panel.css la usa para .subnav y para el margen de scroll de las secciones) */
function medirCabecera() { document.body.style.setProperty("--cab", $("header").offsetHeight + "px") }
addEventListener("resize", medirCabecera); medirCabecera();

/* Ventana emergente */
/* abrirModal(html): agrega un botón "Cerrar". abrirModal(html, true): sin botón (el html trae los suyos;
   cualquier elemento con el atributo data-cerrar cierra la ventana). También cierra con clic fuera o Escape. */
function abrirModal(html, sinCerrar) {
  $("#mbody").innerHTML = html + (sinCerrar ? "" : '<p style="margin:14px 0 0"><button class="pri" data-cerrar>Cerrar</button></p>');
  $("#modal").classList.add("on");
  $$("[data-cerrar]", $("#mbody")).forEach(function (b) { b.onclick = cerrarModal });
}
function cerrarModal() { $("#modal").classList.remove("on") }
$("#modal").onclick = function (e) { if (e.target === this) cerrarModal() };
document.addEventListener("keydown", function (e) { if (e.key === "Escape") cerrarModal() });

/* Salir */
$("#salir").onclick = function () { api("/api/logout", { method: "POST" }).then(function () { location.href = "/login" }) };

/* Menú que sigue el scroll: marca la sección visible y la mantiene a la vista en móvil */
/* Cada enlace de .subnav apunta a una sección por su id (href="#clima"). La sección "activa" es la última cuyo borde
   superior ya pasó 40px por debajo del menú; al llegar al final de la página se marca la última.
   Llamarla después de pintar el contenido (las alturas de las secciones deben ser las definitivas). */
function seguirScroll() {
  var links = $$(".subnav a"), secciones = links.map(function (a) { return $(a.getAttribute("href")) }).filter(Boolean), actual = null;
  function marcar() {
    var limite = $(".subnav").getBoundingClientRect().bottom + 40;
    secciones.forEach(function (s) { if (s.getBoundingClientRect().top <= limite) actual = s.id });
    if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) actual = secciones[secciones.length - 1].id;  /* al final */
    links.forEach(function (a) {
      var on = a.getAttribute("href") === "#" + (actual || secciones[0].id);
      /* En móvil el menú se desplaza horizontalmente: se centra el enlace activo */
      if (on && !a.classList.contains("on")) { var nav = a.parentNode; nav.scrollLeft = a.offsetLeft - nav.clientWidth / 2 + a.clientWidth / 2 }
      a.classList.toggle("on", on);
    });
  }
  addEventListener("scroll", marcar, { passive: true }); addEventListener("resize", marcar); marcar();
}
