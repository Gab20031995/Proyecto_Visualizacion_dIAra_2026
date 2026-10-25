/* Landing pública: proyectos, detalle de obra, buscador y formularios ciudadanos.
   Con servidor usa datos reales (/api/resumen); abierta con doble clic usa estos datos de ejemplo. */
/* Página: frontend/index.html. API pública: routes/publico.py (no requiere sesión).
   Formato de cada obra (claves cortas, así las entrega /api/resumen):
     id, n (nombre), u (ubicación), i (institución), e (estado administrativo: En ejecución, Suspendido...),
     d (ausente si la obra aún no tiene cámara) = { obs (avance general observado, %; null si aún no se mide), f (fecha de los datos) }
     foto (ausente si no hay) = { url, fecha, hora }: última foto en versión pública (sin detecciones de la IA);
       sobre ella, el botón del time-lapse del último día (GET /api/timelapse/{id}, ver tlIniciar)
   Por diseño NO se publica el análisis de auditoría (estado atrasada/al día, brecha, previsto, alertas): ver
   backend/routes/publico.py. No agregar esos datos aquí sin revisar esa regla. */
var projects = [
  { id: "P-001", n: "Escuela Limoncito", u: "Cieneguita, Limón", i: "MEP", e: "En ejecución", d: { obs: 48, f: "14-10-2026" } },
  { id: "P-002", n: "Ruta cantonal Paraíso (ejemplo)", u: "Paraíso, Cartago", i: "Municipalidad", e: "En ejecución" }
];

/* Con servidor el acceso es /login (ruta del backend); sin servidor, login.html directo */
if (CON_SERVIDOR) $$("#ir-login, #ir-login2").forEach(function (a) { a.href = "/login" });

/* Estado administrativo de la obra (no el resultado de la auditoría) */
var CLASE_E = { "Planificado": "b-b", "En ejecución": "b-g", "Suspendido": "b-o", "Finalizado": "b-n", "Cancelado": "b-r" };
function badge(p) { return '<span class="badge ' + (CLASE_E[p.e] || "b-n") + '">' + esc(p.e || "—") + "</span>" + (p.d ? "" : ' <span class="badge b-n">⚪ Sin cámara aún</span>') }

/* Última foto de la obra (o un aviso si aún no hay); la fecha y hora van sobre la imagen.
   Con servidor, si hay foto, agrega el botón del time-lapse del último día (ver "Time-lapse" más abajo). */
function foto(p) {
  return '<div class="foto-obra">' + (p.foto ? '<img loading="lazy" src="' + esc(p.foto.url) + '" alt="Última foto de la obra ' + esc(p.n) + '"><span class="hora">📷 ' +
    esc(p.foto.fecha.split("-").reverse().join("/")) + " · " + esc(p.foto.hora) + "</span>" +
    (CON_SERVIDOR ? '<button class="tl-btn" data-tl="' + esc(p.id) + '" aria-label="Ver el time-lapse del último día de ' + esc(p.n) + '">▶ Time-lapse</button><div class="tl-barra"><i></i></div>' : "")
    : '<span class="vacia">📷 Aún sin fotos de la cámara</span>') + "</div>";
}

/* ---------- Time-lapse del último día con fotos ---------- */
/* GET /api/timelapse/{id} -> {fecha, fotos: [{hora, url}]} (solo ese día, versión pública: routes/publico.py).
   Se reproduce dentro de la misma foto de la tarjeta (o del detalle): cambia el cuadro cada TL_MS, muestra la hora y una
   barra de progreso, y al terminar espera un momento y vuelve a empezar. Un solo time-lapse a la vez; otro clic pausa. */
var TL_MS = 450, TL_PAUSA_FINAL = 1500, TL_DATOS = {}, TL = null;  /* TL = reproducción activa {pid, cont, i, t} */
function tlParar() {
  if (!TL) return;
  clearTimeout(TL.t); TL.cont.classList.remove("tl-on"); TL.cont.dataset.tlI = TL.i;  /* se continúa desde este cuadro */
  $(".tl-btn", TL.cont).textContent = "▶ Continuar"; TL = null;
}
function tlCuadro() {
  if (!document.body.contains(TL.cont)) { TL = null; return }  /* la tarjeta se volvió a pintar (buscador, filtro) */
  var d = TL_DATOS[TL.pid], f = d.fotos[TL.i], c = TL.cont;
  $("img", c).src = f.url;
  $(".hora", c).textContent = "📷 " + d.fecha.split("-").reverse().join("/") + " · " + f.hora;
  $(".tl-barra i", c).style.width = (100 * (TL.i + 1) / d.fotos.length) + "%";
  var ultimo = TL.i === d.fotos.length - 1;
  TL.i = ultimo ? 0 : TL.i + 1;
  TL.t = setTimeout(tlCuadro, ultimo ? TL_PAUSA_FINAL : TL_MS);
}
function tlIniciar(btn) {
  var cont = btn.parentNode, pid = btn.dataset.tl;
  if (TL && TL.cont === cont) return tlParar();  /* segundo clic en la misma foto: pausa */
  tlParar();
  var arrancar = function () {
    var d = TL_DATOS[pid];
    if (!d.fotos.length) { btn.textContent = "Sin fotos del día"; return }
    d.fotos.forEach(function (f) { new Image().src = f.url });  /* precarga: el navegador guarda los cuadros en caché */
    TL = { pid: pid, cont: cont, i: +(cont.dataset.tlI || 0), t: null };
    cont.classList.add("tl-on"); btn.textContent = "⏸ Pausar";  /* corto: la fecha y la hora van en la etiqueta de la derecha */
    btn.title = d.fotos.length + " fotos del " + d.fecha.split("-").reverse().join("/");
    tlCuadro();
  };
  if (TL_DATOS[pid]) return arrancar();
  btn.textContent = "Cargando…";
  fetch("/api/timelapse/" + encodeURIComponent(pid)).then(function (r) { return r.ok ? r.json() : { fotos: [] } })
    .then(function (d) { TL_DATOS[pid] = d; arrancar() }).catch(function () { btn.textContent = "No disponible" });
}
/* Delegación: los botones se crean al pintar tarjetas y el modal; un solo listener sirve para todos.
   stopPropagation: el clic no abre el detalle de la obra ni otra acción de la tarjeta. */
document.addEventListener("click", function (e) {
  var b = e.target.closest && e.target.closest("[data-tl]");
  if (b) { e.preventDefault(); e.stopPropagation(); tlIniciar(b) }
});

/* Avance general con su barra; d.obs null = la obra tiene cámara pero la IA todavía no mide su avance */
function avance(d) {
  if (d.obs == null) return '<div class="mu">Avance general: <b>en medición</b> (cámara activa)</div>';
  return '<div class="mu">Avance general observado: <b>' + d.obs + '%</b></div><div class="bar"><i style="width:' + Math.min(100, d.obs) + '%"></i></div>';
}

/* Pinta las tarjetas de obras y llena los selectores de obra de los formularios (solo obras con datos) */
function pintar() {
  $("#projs").innerHTML = projects.map(function (p, k) {
    var d = p.d;
    return '<div class="card obra">' + foto(p) + '<h3>' + esc(p.n) + '</h3><div class="mu">' + esc(p.u) + " · " + esc(p.i) + '</div><p style="margin:10px 0">' + badge(p) + "</p>" +
      (d ? avance(d) : "") +
      '<p style="margin:12px 0 0"><button ' + (d ? "" : "disabled ") + 'data-k="' + k + '" class="ver">Ver avance</button></p></div>'
  }).join("");
  $$(".obras").forEach(function (s) { s.innerHTML = projects.filter(function (p) { return p.d }).map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.n) + "</option>" }).join("") });
  $$(".ver").forEach(function (b) { b.onclick = function () { ver(+b.dataset.k) } });
}

/* Detalle de obra (modal) */
/* k: posición de la obra en `projects`. Muestra el avance general y los aportes ciudadanos ya aprobados */
function ver(k) {
  var p = projects[k], d = p.d;
  $("#mbody").innerHTML = foto(p) + "<h2>" + esc(p.n) + '</h2><p class="mu" style="margin:0 0 8px">Datos al ' + esc(d.f) + " · estimación de apoyo basada en IA; no sustituye la inspección técnica.</p>" +
    "<p>" + badge(p) + "</p>" +
    '<div style="margin:8px 0 4px">' + avance(d) + "</div>" +
    '<p class="mu" style="margin:10px 0 0">La Contraloría analiza estos datos junto con el cronograma, la bitácora y el clima. Las conclusiones (por ejemplo, si una obra está atrasada) se publican una vez concluida su revisión.</p>' +
    '<h3 style="margin-top:16px">Aportes de la comunidad</h3><div id="maps" class="mu">' + (CON_SERVIDOR ? "Cargando…" : "Disponible al abrir el sitio desde el servidor.") + "</div>" +
    '<p style="margin:14px 0 0"><button class="pri" id="mclose">Cerrar</button> <a class="btn" href="#participar" id="mpart">Aportar o suscribirme</a></p>';
  $("#modal").classList.add("on");
  $("#mclose").onclick = $("#mpart").onclick = function () { $("#modal").classList.remove("on") };
  if (CON_SERVIDOR) api("/api/aportes?proyecto=" + encodeURIComponent(p.id)).then(function (l) {
    $("#maps").innerHTML = l.length ? l.map(function (a) {
      return '<div class="card aporte" style="color:var(--tx)"><b>' + esc(a.tipo) + '</b> <span class="mu">· ' + esc(a.fecha) + " · " + esc(a.nombre) + "</span><div>" + esc(a.texto) + "</div>" +
        (a.foto ? '<img src="' + esc(a.foto) + '" alt="Foto aportada por la comunidad">' : "") + "</div>"
    }).join("") : "Aún no hay aportes revisados."
  }).catch(function () { $("#maps").textContent = "No se pudieron cargar los aportes." });
}
/* La landing no usa panel.js: cierra su ventana emergente aquí (clic fuera o Escape) */
$("#modal").onclick = function (e) { if (e.target === this) this.classList.remove("on") };
document.addEventListener("keydown", function (e) { if (e.key === "Escape") $("#modal").classList.remove("on") });

/* Buscador */
/* Filtra por nombre o ubicación mientras se escribe; elegir una obra con datos abre su detalle */
var q = $("#q"), dd = $("#dd");
function buscar(f) {
  var l = projects.map(function (p, k) { return [p, k] }).filter(function (x) { return (x[0].n + x[0].u).toLowerCase().indexOf(f.toLowerCase()) > -1 });
  dd.innerHTML = (f ? "" : "<div style='cursor:default'><small>PROYECTOS ACTIVOS</small></div>") +
    (l.map(function (x) { return "<div data-k='" + x[1] + "'><span>" + esc(x[0].n) + "</span><small>" + esc(x[0].u) + "</small></div>" }).join("") || "<div><small>Sin resultados</small></div>");
  dd.classList.add("on");
  $$("[data-k]", dd).forEach(function (r) {
    r.onclick = function () {
      var p = projects[+r.dataset.k]; q.value = p.n; dd.classList.remove("on");
      if (p.d) ver(+r.dataset.k); else { location.hash = "proyectos"; toast("Esta obra aún no tiene datos") }
    }
  })
}
q.onfocus = q.oninput = function () { buscar(q.value) };
document.addEventListener("click", function (e) { if (!e.target.closest(".search")) dd.classList.remove("on") });  /* clic fuera: cierra la lista */

/* Pestañas ciudadanas */
$$(".tabs2 button").forEach(function (b) {
  b.onclick = function () {
    $$(".tabs2 button").forEach(function (x) { x.classList.toggle("on", x === b) });
    $("#sub").classList.toggle("hide", b.dataset.t !== "sub"); $("#ap").classList.toggle("hide", b.dataset.t !== "ap")
  }
});

/* Envíos: con servidor se guardan; sin servidor se simulan */
/* Se envía FormData (multipart) porque el aporte puede incluir una foto. El servidor valida todo de nuevo. */
function enviar(ruta, datos, ok, form) {
  if (!CON_SERVIDOR) { toast("✅ " + ok + " (simulado: aún sin servidor)"); form.reset(); return }
  api(ruta, { method: "POST", body: datos }).then(function () { toast("✅ " + ok); form.reset() }).catch(function (e) { toast(e.message || "No se pudo enviar. Intente de nuevo.") })
}
$("#sub").onsubmit = function (e) {
  e.preventDefault(); var f = new FormData();
  f.append("proyecto", $("#s-o").value); f.append("nombre", $("#s-n").value); f.append("canal", $("#s-c").value); f.append("contacto", $("#s-d").value);
  enviar("/suscripciones", f, "Suscripción registrada", this)
};
$("#ap").onsubmit = function (e) {
  e.preventDefault(); var fl = $("#a-f").files[0];
  if (!$("#a-x").value.trim() && !fl) { toast("Escriba un comentario o adjunte una foto"); return }
  if (fl && fl.size > 5e6) { toast("La foto supera 5 MB"); return }  /* mismo límite que el servidor; aquí solo evita subir en vano */
  var f = new FormData(); f.append("proyecto", $("#a-o").value); f.append("tipo", $("#a-t").value); f.append("texto", $("#a-x").value); f.append("nombre", $("#a-n").value);
  if (fl) f.append("foto", fl);
  enviar("/aportes", f, "Aporte recibido; quedará pendiente de revisión", this)
};

/* Arranque: se pintan primero los datos de ejemplo y, si hay servidor, se reemplazan por los reales */
pintar();
if (CON_SERVIDOR) api("/api/resumen").then(function (j) { projects = j.proyectos; $("#nal").textContent = j.monitoreadas; pintar() }).catch(function () { toast("No se pudieron cargar los datos de las obras") });
else $("#nal").textContent = "1";
