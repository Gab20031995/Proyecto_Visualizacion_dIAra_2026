@echo off
REM Tarea programada: actualiza el clima real de todas las obras (ver backend\actualizar_clima.py).
REM Programar cada 12 horas o menos en el Programador de tareas de Windows.
REM Las claves de las fuentes (GOOGLE_MAPS_API_KEY, METEOBLUE_API_KEY, METEOSOURCE_API_KEY) deben estar
REM definidas como variables de entorno de Windows; Open-Meteo funciona sin clave.
REM Se ubica en la carpeta del proyecto (%~dp0 = carpeta de este .bat) para que las rutas relativas funcionen.
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
REM La salida (y los errores) se agregan a data\tareas.log para revisar qué pasó en cada ejecución.
python backend\actualizar_clima.py >> data\tareas.log 2>&1
