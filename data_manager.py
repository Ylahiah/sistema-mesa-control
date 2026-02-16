import pandas as pd
import gspread
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
import time

# Scope for Google Sheets API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

REQUIRED_COLUMNS = [
    "REGION", "FECHA_ENTREGA", "RUTA", "FOLIO", 
    "CAPTURISTA", "EVENTO", "FINANCIAMIENTO", 
    "ESTATUS", "FECHA_ULTIMO_EVENTO",
    "FOLIO DOCUMENTOS POR PICKING", "# FOLIOS DOCUMENTOS", 
    "CUENTA FOLIOS", "FOLIOS SCALD", "ESTATUS FOLIOS SCALD"
]

@st.cache_resource
def get_gspread_client():
    """
    Initializes and returns a gspread client using Streamlit secrets.
    """
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("No credentials found in .streamlit/secrets.toml")
            return None
            
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        
        # Add retry with backoff for client authorization
        # Although client auth usually doesn't hit quota, operations do.
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        return None

def with_retry(func, *args, **kwargs):
    """
    Helper to retry API calls on 429 Quota Exceeded.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + 1  # Exponential backoff: 2s, 3s, 5s...
                    time.sleep(sleep_time)
                    continue
            raise e

@st.cache_resource(ttl=300) # Cache worksheet object for 5 mins to avoid re-opening constantly
def get_or_create_worksheet(client, sheet_name="pickings"):
    """
    Gets the worksheet or creates it if it doesn't exist (assuming the spreadsheet exists).
    """
    SPREADSHEET_NAME = "SISTEMA_PICKINGS_DB"
    
    try:
        try:
            # We don't cache client.open because client object is already cached
            # But we should retry the open call
            sh = with_retry(client.open, SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            service_email = client.auth.service_account_email
            error_msg = (
                f"No se encontró la hoja de cálculo '{SPREADSHEET_NAME}'.\n\n"
                f"POR FAVOR:\n"
                f"1. Crea una nueva Hoja de Cálculo en Google Sheets llamada '{SPREADSHEET_NAME}'.\n"
                f"2. Compártela con permisos de EDITOR al siguiente email:\n"
                f"   {service_email}"
            )
            st.error(error_msg)
            return None
        
        try:
            worksheet = with_retry(sh.worksheet, sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = with_retry(sh.add_worksheet, title=sheet_name, rows=1000, cols=20)
            worksheet.append_row(REQUIRED_COLUMNS)
            
        return worksheet
    except Exception as e:
        # Don't show error immediately on UI if it's just a temporary glitch, let app handle None
        # st.error(f"Error accessing worksheet: {e}")
        print(f"Error accessing worksheet: {e}")
        return None

@st.cache_data(ttl=60) # Cache data for 60 seconds to reduce read quota
def load_data(_worksheet):
    """
    Reads data from the worksheet and returns a DataFrame.
    """
    try:
        # Use with_retry for get_all_records
        data = with_retry(_worksheet.get_all_records)
        if not data:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)
        df = pd.DataFrame(data)
        # Ensure all required columns exist
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception as e:
        st.error(f"Error reading data: {e}")
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

def sync_excel_data(worksheet, uploaded_file):
    """
    Process uploaded Excel file:
    1. Validate columns
    2. Extract unique folios (check against existing)
    3. Append new records
    """
    try:
        # Read uploaded Excel
        new_df = pd.read_excel(uploaded_file)
        
        # Standardize columns to uppercase
        new_df.columns = [str(c).upper().strip() for c in new_df.columns]
        
        # Check missing columns
        missing_cols = [c for c in ["FOLIO"] if c not in new_df.columns] # Minimal requirement is FOLIO
        if missing_cols:
            return False, f"Missing required columns in Excel: {missing_cols}"
            
        # Get existing data
        existing_records = worksheet.get_all_records()
        existing_df = pd.DataFrame(existing_records)
        
        existing_folios = set()
        if not existing_df.empty and "FOLIO" in existing_df.columns:
             existing_folios = set(existing_df["FOLIO"].astype(str).str.strip())
        
        records_to_add = []
        added_count = 0
        duplicates_count = 0
        
        for _, row in new_df.iterrows():
            folio = str(row.get("FOLIO", "")).strip()
            if not folio or folio in existing_folios:
                duplicates_count += 1
                continue
            
            # Prepare record
            record = {}
            for col in REQUIRED_COLUMNS:
                val = row.get(col, "")
                # Defaults
                if col == "ESTATUS" and not val:
                    val = "PENDIENTE" # Initial status
                if col == "FECHA_ULTIMO_EVENTO" and not val:
                    val = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                record[col] = str(val) # Convert to string for Sheets
            
            records_to_add.append([record[c] for c in REQUIRED_COLUMNS])
            existing_folios.add(folio)
            added_count += 1
            
        if records_to_add:
            worksheet.append_rows(records_to_add)
            return True, f"Successfully added {added_count} new records. Skipped {duplicates_count} duplicates."
        else:
            return True, "No new records to add (all duplicates)."
            
    except Exception as e:
        return False, f"Error processing file: {e}"

def update_status(worksheet, folio, new_status, user_name):
    """
    Updates the status of a specific picking.
    """
    try:
        # We need to find the row index. 
        # For performance in large sheets, batch reading is better, but cell-finding is safer for concurrency if low volume.
        # Here we assume reasonable volume.
        cell = worksheet.find(folio)
        if not cell:
            return False, "Folio not found"
            
        row_idx = cell.row
        
        # Column indices (1-based)
        headers = worksheet.row_values(1)
        try:
            status_col = headers.index("ESTATUS") + 1
            event_col = headers.index("EVENTO") + 1
            date_col = headers.index("FECHA_ULTIMO_EVENTO") + 1
        except ValueError:
            return False, "Column headers mismatch"
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Batch update
        updates = [
            {"range": gspread.utils.rowcol_to_a1(row_idx, status_col), "values": [[new_status]]},
            {"range": gspread.utils.rowcol_to_a1(row_idx, event_col), "values": [[f"Status changed to {new_status} by {user_name}"]]},
            {"range": gspread.utils.rowcol_to_a1(row_idx, date_col), "values": [[timestamp]]}
        ]
        
        worksheet.batch_update(updates)
        return True, "Status updated successfully"
        
    except Exception as e:
        return False, f"Update failed: {e}"

def reassign_capturista(worksheet, folio, new_capturista, user_name):
    """
    Updates the CAPTURISTA of a specific picking.
    """
    try:
        cell = worksheet.find(folio)
        if not cell:
            return False, "Folio not found"
            
        row_idx = cell.row
        headers = worksheet.row_values(1)
        try:
            capturista_col = headers.index("CAPTURISTA") + 1
            event_col = headers.index("EVENTO") + 1
            date_col = headers.index("FECHA_ULTIMO_EVENTO") + 1
        except ValueError:
            return False, "Column headers mismatch"
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        updates = [
            {"range": gspread.utils.rowcol_to_a1(row_idx, capturista_col), "values": [[new_capturista]]},
            {"range": gspread.utils.rowcol_to_a1(row_idx, event_col), "values": [[f"Reassigned to {new_capturista} by {user_name}"]]},
            {"range": gspread.utils.rowcol_to_a1(row_idx, date_col), "values": [[timestamp]]}
        ]
        
        worksheet.batch_update(updates)
        return True, "Capturista updated successfully"
        
    except Exception as e:
        return False, f"Update failed: {e}"

@st.cache_resource(ttl=300)
def get_or_create_users_worksheet():
    """
    Gets or creates the 'usuarios' worksheet.
    Client is created internally to avoid hashing issues.
    """
    client = get_gspread_client()
    if not client: return None
    
    sheet_name = "usuarios"
    SPREADSHEET_NAME = "SISTEMA_PICKINGS_DB"
    try:
        sh = with_retry(client.open, SPREADSHEET_NAME)
        try:
            worksheet = with_retry(sh.worksheet, sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = with_retry(sh.add_worksheet, title=sheet_name, rows=100, cols=5)
            # Default headers
            worksheet.append_row(["USUARIO", "ROL", "FECHA_CREACION"])
            # Default Admin user
            worksheet.append_row(["Admin", "RESPONSABLE", datetime.now().strftime("%Y-%m-%d")])
        return worksheet
    except Exception as e:
        print(f"Error accessing users worksheet: {e}")
        return None

@st.cache_data(ttl=300) # Cache users for 5 mins as they don't change often
def get_all_users(_worksheet):
    """
    Returns a list of dictionaries with user info.
    """
    try:
        records = with_retry(_worksheet.get_all_records)
        if not records:
             return [{"USUARIO": "Admin", "ROL": "RESPONSABLE"}]
        return records
    except Exception as e:
        st.error(f"Error reading users: {e}")
        return []

def add_user(worksheet, name, role):
    """
    Adds a new user to the system.
    """
    try:
        # Simple check if user exists by name
        cell = worksheet.find(name)
        if cell:
            return False, "El usuario ya existe."
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.append_row([name, role, timestamp])
        return True, "Usuario creado exitosamente."
    except Exception as e:
        return False, f"Error creando usuario: {e}"

def delete_user(worksheet, name):
    """
    Deletes a user.
    """
    try:
        if name == "Admin":
            return False, "No se puede eliminar al usuario Admin."
            
        cell = worksheet.find(name)
        if not cell:
            return False, "Usuario no encontrado."
            
        worksheet.delete_rows(cell.row)
        return True, "Usuario eliminado correctamente."
    except Exception as e:
        return False, f"Error eliminando usuario: {e}"

def increment_folio_count(worksheet, folio, scanned_qr):
    """
    Adds a scanned QR to 'FOLIO DOCUMENTOS POR PICKING' and increments '# FOLIOS DOCUMENTOS'.
    This is for the Warehouse Reception scanning.
    """
    try:
        cell = worksheet.find(folio)
        if not cell:
            return False, "Folio padre no encontrado en base maestra."
        
        row_idx = cell.row
        headers = worksheet.row_values(1)
        
        try:
            docs_col = headers.index("FOLIO DOCUMENTOS POR PICKING") + 1
            count_col = headers.index("# FOLIOS DOCUMENTOS") + 1
            status_col = headers.index("ESTATUS") + 1
        except ValueError:
            return False, "Columnas requeridas no encontradas en la hoja."

        # Get current values
        current_docs = worksheet.cell(row_idx, docs_col).value or ""
        current_count = worksheet.cell(row_idx, count_col).value
        
        # Safe integer conversion
        try:
            current_count = int(current_count) if current_count else 0
        except:
            current_count = 0

        # Check duplicates in the string
        if scanned_qr in current_docs:
            return False, "Este documento ya fue escaneado para este folio."

        # Append new QR
        if current_docs:
            new_docs = f"{current_docs}\n{scanned_qr}"
        else:
            new_docs = scanned_qr
            
        new_count = current_count + 1
        
        # Batch update
        updates = [
            {"range": gspread.utils.rowcol_to_a1(row_idx, docs_col), "values": [[new_docs]]},
            {"range": gspread.utils.rowcol_to_a1(row_idx, count_col), "values": [[new_count]]},
            # Default status to IMPRESOS on first scan if empty
            # But prompt says: "al ser escaneados la primera vez debera estar en estatus impresos"
            # We can force it or check current status. Let's force it if it's PENDIENTE or empty.
        ]
        
        # Check current status to decide if update needed
        current_status = worksheet.cell(row_idx, status_col).value
        if not current_status or current_status == "PENDIENTE":
             updates.append({"range": gspread.utils.rowcol_to_a1(row_idx, status_col), "values": [["IMPRESOS"]]})
        
        worksheet.batch_update(updates)
        return True, f"Agregado correctamente. Conteo actual: {new_count}"

    except Exception as e:
        return False, f"Error en incremento: {e}"
