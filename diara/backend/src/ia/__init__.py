"""Análisis de imágenes con IA (fase de investigación, sobre las fotos curadas del ETL; ver src/etl).

Módulos:
    actividad.py   personas y vehículos por foto (YOLO preentrenado) + índice de cambio entre fotos consecutivas,
                   resumen diario y cruce con la lluvia -> tabla ia_actividad y data/etl/<proyecto>/actividad_*.csv

Igual que el ETL, trabaja en tablas propias (ia_*) y no cambia el panel, las alertas ni los reportes de la aplicación.
Dependencias pesadas (PyTorch, Ultralytics) en requirements-ia.txt; se importan solo dentro de este paquete.

Licencia: Ultralytics y los pesos YOLO11 son AGPL-3.0. Sirven para el MVP y la investigación; antes de llevar el
modelo a producción en la CGR hay que resolver la licencia (licencia comercial de Ultralytics, o cambiar a un modelo
con licencia permisiva, p. ej. RT-DETR o Faster R-CNN de torchvision, BSD/Apache)."""
