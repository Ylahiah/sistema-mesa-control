import pandas as pd
import gspread
from datetime import datetime
import streamlit as st

# Define columns for the new 'detalle_pickings' sheet
DETAIL_COLUMNS = [
    "QR_DATA", "FOLIO_PADRE", "CAPTURISTA", 
    "ESTATUS_ITEM", "FECHA_ESCANEO", "DETALLES_EXTRA"
]

def get_or_create_detail_worksheet(client, sheet_name="detalle_pickings"):
    """
    Gets or creates the detail worksheet for individual QR tracking.
    """
    SPREADSHEET_NAME = "SISTEMA_PICKINGS_DB"
    try:
        sh = client.open(SPREADSHEET_NAME)
        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=sheet_name, rows=5000, cols=10)
            worksheet.append_row(DETAIL_COLUMNS)
        return worksheet
    except Exception as e:
        st.error(f"Error accessing detail worksheet: {e}")
        return None

def parse_qr_code(qr_string):
    """
    Parses the QR string to extract the Folio.
    Assumes format: "folio|financiamiento|piezas|..."
    Returns (folio, extra_details) or (None, None) if invalid.
    """
    if not qr_string or "|" not in qr_string:
        # Fallback: maybe the QR is just the folio?
        return qr_string.strip(), "Raw QR"
    
    parts = qr_string.split("|")
    # Assuming first element is folio. Adjust index if needed.
    folio = parts[0].strip()
    extra_details = qr_string # Store full string for reference
    return folio, extra_details

def register_qr_scan(detail_ws, qr_data, capturista, status="SURTIDO"):
    """
    Registers a scanned QR code.
    1. Checks if QR already exists (prevent duplicates).
    2. Extracts Folio.
    3. Saves to 'detalle_pickings'.
    """
    try:
        # 1. Check duplicates
        # For performance, we might want to cache existing QRs, but for now we search.
        cell = detail_ws.find(qr_data)
        if cell:
            return False, f"Este QR ya fue registrado previamente (Fila {cell.row})."

        # 2. Parse
        folio, extra = parse_qr_code(qr_data)
        if not folio:
            return False, "Formato de QR inválido o no legible."

        # 3. Save
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_row = [
            qr_data, folio, capturista, 
            status, timestamp, extra
        ]
        detail_ws.append_row(new_row)
        return True, f"QR registrado exitosamente. Folio vinculado: {folio}"

    except Exception as e:
        return False, f"Error registrando QR: {e}"

def update_qr_status(detail_ws, qr_data, new_status):
    """
    Updates the status of an existing QR (e.g., upon return from warehouse).
    """
    try:
        cell = detail_ws.find(qr_data)
        if not cell:
            return False, "QR no encontrado en el sistema. ¿Fue registrado al inicio?"
        
        row_idx = cell.row
        headers = detail_ws.row_values(1)
        try:
            status_col = headers.index("ESTATUS_ITEM") + 1
            date_col = headers.index("FECHA_ESCANEO") + 1 # Update scan time? Or maybe add a 'RETURN_DATE'?
            # Let's just update the status and keep original scan date, or maybe we need a history.
            # For simplicity, we update status.
        except ValueError:
            return False, "Error en estructura de hoja de detalles."

        detail_ws.update_cell(row_idx, status_col, new_status)
        return True, f"Estatus actualizado a {new_status}"
    except Exception as e:
        return False, f"Error actualizando QR: {e}"

def delete_qr_scan(detail_ws, qr_data):
    """
    Deletes a specific QR record (soft delete or hard delete).
    Here we'll do hard delete for simplicity in the list.
    """
    try:
        cell = detail_ws.find(qr_data)
        if not cell:
            return False, "QR no encontrado para eliminar."
        
        detail_ws.delete_rows(cell.row)
        return True, "Registro eliminado correctamente."
    except Exception as e:
        return False, f"Error eliminando registro: {e}"

def get_folio_details(detail_ws, folio):
    """
    Retrieves all QR records associated with a specific Folio.
    """
    try:
        # Get all records
        all_records = detail_ws.get_all_records()
        df = pd.DataFrame(all_records)
        
        if df.empty or "FOLIO_PADRE" not in df.columns:
            return pd.DataFrame()
            
        # Filter by Folio (convert to string to be safe)
        filtered_df = df[df["FOLIO_PADRE"].astype(str) == str(folio)]
        return filtered_df
    except Exception as e:
        st.error(f"Error fetching details: {e}")
        return pd.DataFrame()
