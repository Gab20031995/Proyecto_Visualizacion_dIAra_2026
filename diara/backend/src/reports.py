"""Matriz de recursos en Excel. El PDF de reportes está en src/reporte_pdf.py.
La usa la descarga "⬇ Excel" del panel de un proyecto (routes/auditor.py → /matriz.xlsx)."""
import io

def matriz(d):
    """Últimos 7 días con registro: recursos detectados por la IA, horas y lluvia."""
    m = d[d.hay_registro == 1].tail(7)[["fecha", "fotos", "personas_prom", "personas_max", "maquinaria",
        "horas_sitio", "horas_efectivas", "lluvia_mm"]].copy()
    m["fecha"] = m.fecha.dt.strftime("%d-%m-%Y")
    return m

def matriz_xlsx(d):
    """Bytes del archivo .xlsx (requiere openpyxl)."""
    b = io.BytesIO(); matriz(d).to_excel(b, index=False, sheet_name="Matriz"); return b.getvalue()
