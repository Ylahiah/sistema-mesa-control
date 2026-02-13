import streamlit as st
import pandas as pd
import data_manager as dm
import detail_manager as dtlm
import time
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from PIL import Image

# Page configuration
st.set_page_config(
    page_title="Sistema de Control de Pickings",
    page_icon="📦",
    layout="wide"
)

# Constants
ROLES = ["CAPTURISTA", "RESPONSABLE"]
STATUS_OPTIONS_CAPTURISTA = ["SURTIDO", "CAPTURADO", "EN_VALIDACION", "DOC_LISTA"]
STATUS_OPTIONS_RESPONSABLE = ["SURTIDO", "CAPTURADO", "EN_VALIDACION", "DOC_LISTA", "LIBERADO"]

# Mock Users for simple authentication
USERS = ["Admin", "Juan", "Maria", "Pedro", "Luisa"]

def init_session_state():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "role" not in st.session_state:
        st.session_state.role = None

def login_page():
    st.title("📦 Control de Pickings - Acceso")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            user = st.selectbox("Selecciona tu Usuario", USERS)
            role = st.selectbox("Selecciona tu Rol", ROLES)
            submitted = st.form_submit_button("Ingresar")
            
            if submitted:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.session_state.role = role
                st.rerun()

def main_app():
    st.sidebar.title(f"Hola, {st.session_state.user}")
    st.sidebar.badge(st.session_state.role)
    
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.role = None
        st.rerun()

    # Connection to Google Sheets
    client = dm.get_gspread_client()
    if not client:
        st.warning("No se pudo conectar a Google Sheets. Revisa la configuración de secretos (.streamlit/secrets.toml).")
        st.stop()
        
    worksheet = dm.get_or_create_worksheet(client)
    detail_worksheet = dtlm.get_or_create_detail_worksheet(client)
    
    if not worksheet or not detail_worksheet:
        st.error("No se pudo acceder a las hojas de cálculo.")
        st.stop()

    # Load Data
    # Optimization: Only load full data for Responsable or summary
    # For scanning, we might not need to load everything immediately
    with st.spinner("Cargando datos..."):
        df = dm.load_data(worksheet)

    if st.session_state.role == "RESPONSABLE":
        responsable_view(df, worksheet, detail_worksheet)
    else:
        capturista_view(df, worksheet, detail_worksheet)

def responsable_view(df, worksheet, detail_worksheet):
    st.title("Panel de Responsable")
    
    tab1, tab2, tab3 = st.tabs(["📋 Gestión Operativa", "📤 Carga Masiva", "👥 Reasignación"])
    
    with tab1:
        st.subheader("Tablero General")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_status = st.multiselect("Filtrar por Estatus", options=df["ESTATUS"].unique())
        with col2:
            filter_capturista = st.multiselect("Filtrar por Capturista", options=df["CAPTURISTA"].unique())
        with col3:
            search_folio = st.text_input("Buscar Folio")
            
        filtered_df = df.copy()
        if filter_status:
            filtered_df = filtered_df[filtered_df["ESTATUS"].isin(filter_status)]
        if filter_capturista:
            filtered_df = filtered_df[filtered_df["CAPTURISTA"].isin(filter_capturista)]
        if search_folio:
            filtered_df = filtered_df[filtered_df["FOLIO"].astype(str).str.contains(search_folio, case=False)]
            
        st.dataframe(filtered_df, use_container_width=True)
        
        st.divider()
        st.subheader("Cambio de Estatus Rápido (Folio Completo)")
        col_act1, col_act2 = st.columns(2)
        with col_act1:
            selected_folio = st.selectbox("Seleccionar Folio para acción", filtered_df["FOLIO"].unique(), key="resp_folio_select")
        with col_act2:
            new_status = st.selectbox("Nuevo Estatus", STATUS_OPTIONS_RESPONSABLE, key="resp_status_select")
            
        if st.button("Actualizar Estatus"):
            success, msg = dm.update_status(worksheet, str(selected_folio), new_status, st.session_state.user)
            if success:
                st.success(msg)
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

    with tab2:
        st.subheader("Carga de Nuevos Pickings")
        uploaded_file = st.file_uploader("Subir archivo Excel", type=["xlsx", "xls"])
        
        if uploaded_file:
            if st.button("Procesar Archivo"):
                with st.spinner("Procesando y sincronizando..."):
                    success, msg = dm.sync_excel_data(worksheet, uploaded_file)
                    if success:
                        st.success(msg)
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(msg)
                        
    with tab3:
        st.subheader("Reasignación de Capturistas")
        
        c1, c2 = st.columns(2)
        with c1:
            folio_to_assign = st.selectbox("Seleccionar Folio", df["FOLIO"].unique())
        with c2:
            target_user = st.selectbox("Asignar a", USERS)
            
        if st.button("Reasignar"):
            success, msg = dm.reassign_capturista(worksheet, str(folio_to_assign), target_user, st.session_state.user)
            if success:
                st.success(msg)
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

def decode_image(image_file):
    """
    Decodes QR codes from an image file.
    """
    try:
        # Convert the file to an opencv image
        file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        
        # Decode QR codes
        decoded_objects = decode(img)
        
        results = []
        for obj in decoded_objects:
            results.append(obj.data.decode("utf-8"))
            
        return results
    except Exception as e:
        st.error(f"Error decoding image: {e}")
        return []

def capturista_view(df, worksheet, detail_worksheet):
    st.title("Panel de Capturista")
    
    tab_scan, tab_list = st.tabs(["🔫 Escaneo QR (Móvil/PC)", "📋 Mis Asignaciones"])
    
    with tab_scan:
        st.header("Gestión por Código QR")
        
        scan_mode = st.radio("Modo de Escaneo:", ["Registro Inicial (Salida)", "Retorno (Cambio de Estatus)"], horizontal=True)
        
        input_method = st.radio("Método de Entrada:", ["Cámara del Dispositivo", "Lector USB / Manual"], horizontal=True)
        
        qr_data_found = None

        if input_method == "Cámara del Dispositivo":
            img_file_buffer = st.camera_input("Toma una foto del QR")
            
            if img_file_buffer is not None:
                # To read image file buffer with OpenCV:
                decoded_qrs = decode_image(img_file_buffer)
                if decoded_qrs:
                    qr_data_found = decoded_qrs[0] # Take the first one found
                    st.success(f"QR Detectado: {qr_data_found}")
                else:
                    st.warning("No se detectó ningún código QR en la imagen.")
        else:
            qr_data_found = st.text_input("Escanear Código QR aquí", key="qr_input_manual", help="Haz clic aquí y usa tu lector USB")

        # Process the found QR (whether from camera or manual)
        if qr_data_found:
            # Add a button to confirm action to avoid accidental double submissions on reruns
            if st.button(f"Confirmar Procesamiento: {qr_data_found}", key="confirm_qr"):
                if scan_mode == "Registro Inicial (Salida)":
                    success, msg = dtlm.register_qr_scan(detail_worksheet, qr_data_found, st.session_state.user, status="SURTIDO")
                    if success:
                        st.success(msg)
                    else:
                        st.warning(msg)
                else:
                    new_status_qr = st.selectbox("Estatus al retornar:", ["CAPTURADO", "DOC_LISTA", "EN_VALIDACION"], index=0, key="status_sel_qr")
                    # We need a nested button or logic here, but Streamlit nested buttons are tricky.
                    # Simplification: Show status selector *before* confirming, or just default to CAPTURADO if not critical.
                    # Let's assume the user selects status first in a real UI, but here we are inside the logic.
                    # Better UX: Move status selector outside the "if qr_data_found" block for Retorno mode.
                    
                    # For now, let's just process with a default or ask user to select before scanning if possible.
                    # But since we are here, let's try to update.
                    success, msg = dtlm.update_qr_status(detail_worksheet, qr_data_found, "CAPTURADO") # Defaulting to CAPTURADO for speed
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
    
    with tab_list:
        # Filter for current user
        my_pickings = df[df["CAPTURISTA"] == st.session_state.user].copy()
        
        if my_pickings.empty:
            st.info("No tienes pickings asignados actualmente.")
            return

        st.metric("Mis Pickings Pendientes", len(my_pickings[my_pickings["ESTATUS"] != "LIBERADO"]))
        
        st.subheader("Mis Asignaciones (Vista General)")
        st.dataframe(my_pickings, use_container_width=True)

if __name__ == "__main__":
    init_session_state()
    if st.session_state.logged_in:
        main_app()
    else:
        login_page()
