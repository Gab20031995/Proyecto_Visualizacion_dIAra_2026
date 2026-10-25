"""Envía los reportes por correo pendientes (o un correo de prueba). Complementa al programador interno.

Con el servidor encendido y REPORTES_AUTOMATICOS=1 (por defecto) los envíos ya ocurren solos (src/programador.py):
este script NO es necesario. Úselo si el programador está apagado (REPORTES_AUTOMATICOS=0) o como respaldo,
programado una vez al día en el Programador de tareas de Windows o en cron. Puede convivir con el programador:
comparten un bloqueo en la base y nunca se repite un período ya enviado.
Sin SMTP_HOST configurado, los reportes se generan y guardan en data/reportes/ como "simulado".
Uso:
    python backend/enviar_reportes.py                      envía lo pendiente      (Windows: tareas\\enviar_reportes.bat)
    python backend/enviar_reportes.py --prueba correo@x    solo envía un correo de prueba (verifica la configuración SMTP)
La lógica completa está en src/reporteria.py; este script solo la dispara e imprime el resultado.
Código de salida: 1 si algún envío terminó en error o la prueba falló (útil para monitoreo)."""
import sys
from src import reporteria, programador

if len(sys.argv) == 3 and sys.argv[1] == "--prueba":
    try: r = reporteria.correo_prueba(sys.argv[2]); print(f"OK: correo de prueba enviado a {r['destino']} por {r['servidor']}"); sys.exit(0)
    except reporteria.ErrorCorreo as e: print(f"ERROR: {e}"); sys.exit(1)
try: res = programador.ejecutar("programado")
except programador.Ocupado as e: print(e); sys.exit(0)
print(f"Correo: {'configurado' if reporteria.smtp_configurado() else 'NO configurado (modo simulado)'} | Hoy: {reporteria.hoy_cr()}")
for r in res:
    print(f"   {r['correo']:<32} {r['frecuencia']:<10} {r['desde']} a {r['hasta']}  ->  {r['estado']}: {r['detalle']}")
if not res: print("   No hay reportes pendientes.")
sys.exit(1 if any(r["estado"] == "error" for r in res) else 0)
