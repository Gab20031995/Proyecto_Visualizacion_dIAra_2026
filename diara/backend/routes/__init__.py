"""Rutas HTTP de la API (FastAPI). Cada módulo define uno o más APIRouter que api.py registra:
publico (ciudadanía), sesion (login y permisos), auditor (panel por proyecto), admin (administración) y camaras (API de imágenes).
Las rutas solo validan la petición y traducen errores a HTTP; la lógica de negocio vive en src/."""
