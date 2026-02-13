import pandas as pd
import gspread
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials

# Scope for Google Sheets API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

REQUIRED_COLUMNS = [
    "REGION", "FECHA_ENTREGA", "RUTA", "FOLIO", 
    "CAPTURISTA", "EVENTO", "FINANCIAMIENTO", 
    "ESTATUS", "FECHA_ULTIMO_EVENTO"
]

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
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        return None

def get_or_create_worksheet(client, sheet_name="pickings"):
    """
    Gets the worksheet or creates it if it doesn't exist (assuming the spreadsheet exists).
    For simplicity, we assume the user provides the Spreadsheet Name or ID in secrets, 
    or we search for a specific filename. 
    Here, we'll try to open a spreadsheet named 'SISTEMA_PICKINGS_DB' or similar, 
    or just 'pickings' if that's the file name.
    
    Let's assume the spreadsheet name is defined in secrets or hardcoded.
    """
    SPREADSHEET_NAME = "SISTEMA_PICKINGS_DB"
    
    try:
        try:
            sh = client.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            # Instead of creating, we ask the user to create and share it
            # This avoids Quota issues on Service Accounts and ensures the user owns the data
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
            worksheet = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
            # Init headers
            worksheet.append_row(REQUIRED_COLUMNS)
            
        return worksheet
    except Exception as e:
        st.error(f"Error accessing worksheet: {e}")
        return None

def load_data(worksheet):
    """
    Reads data from the worksheet and returns a DataFrame.
    """
    try:
        data = worksheet.get_all_records()
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
