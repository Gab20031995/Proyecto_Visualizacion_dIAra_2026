"""Lógica de negocio de dIAra (independiente de HTTP).

    store        base de datos SQLite: esquema, migraciones y consultas
    auth         sesión (token firmado en cookie)
    proyectos    catálogo de obras, validación y token de cámara
    imagenes     imágenes de cámara (recibidas por API + sintéticas)
    metrics      indicadores de una obra a partir de su registro diario
    alerts       alertas automáticas (A-01 a A-04)
    tablero      resumen por proyecto para las tarjetas
    clima/       clima real de varias fuentes y registro consolidado
    reporteria   reportes por correo (calendario, envío, bitácora)
    reporte_pdf  diseño del PDF del reporte
    reports      matriz de recursos en Excel"""
