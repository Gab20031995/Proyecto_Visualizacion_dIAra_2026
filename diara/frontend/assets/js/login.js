/* Login de auditores, administradores y empresas ejecutoras: valida en el servidor (/api/login), que deja una cookie de sesión y redirige al panel. */
/* La página nunca guarda la contraseña ni el token: el servidor responde con una cookie HttpOnly y el destino según el rol
   (/admin, /auditor o /contratista). Las validaciones de aquí son solo de comodidad; las reales están en el servidor. */
if (!CON_SERVIDOR) {
  /* Abierto con doble clic (file://): no hay API, se deshabilita el formulario y se explica cómo levantar el servidor */
  $$("#ir-inicio, #ir-inicio2").forEach(function (a) { a.href = "index.html" });
  $("#err").textContent = "El acceso al sistema requiere el servidor. Ejecute: uvicorn api:app --app-dir backend --port 8000";
  $("#btn").disabled = true;
}

$("#f").onsubmit = function (e) {
  e.preventDefault();
  var correo = $("#em").value.trim(), clave = $("#pw").value, err = $("#err");
  if (!correo || !clave) { err.textContent = "Ingrese correo y contraseña."; return }
  if (correo.indexOf("@") < 0) { err.textContent = "Ingrese un correo válido."; return }
  err.textContent = ""; $("#btn").disabled = true; $("#btn").textContent = "Verificando…";
  api("/api/login", { json: { correo: correo, clave: clave } })
    .then(function (j) { location.href = j.destino || "/auditor" })
    .catch(function (x) { err.textContent = x.message; $("#pw").value = ""; $("#pw").focus() })  /* error: se borra solo la contraseña */
    .then(function () { $("#btn").disabled = false; $("#btn").textContent = "Ingresar al panel" });
};
