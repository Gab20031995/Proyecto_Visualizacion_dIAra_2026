@echo off
REM Respaldo del programador interno: envía los reportes pendientes (ver backend\enviar_reportes.py).
REM Solo es necesaria si el servidor no está siempre encendido o si REPORTES_AUTOMATICOS=0.
REM Programar UNA vez al día (p. ej. 6:00 a. m.) en el Programador de tareas de Windows.
REM La configuración de correo (SMTP_*) se lee de diara\.env (sin ella: modo simulado).
REM Ejecutarla más de una vez el mismo día es seguro: no repite períodos ya enviados.
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
REM La salida (y los errores) se agregan a data\tareas.log.
python backend\enviar_reportes.py >> data\tareas.log 2>&1
