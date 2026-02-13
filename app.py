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
    
    # State management for navigation
    if "selected_folio" not in st.session_state:
        st.session_state.selected_folio = None

    # Filter for current user
    my_pickings = df[df["CAPTURISTA"] == st.session_state.user].copy()
    
    if st.session_state.selected_folio:
        # DETAIL VIEW
        show_folio_detail(st.session_state.selected_folio, detail_worksheet)
    else:
        # MASTER VIEW (List)
        if my_pickings.empty:
            st.info("No tienes pickings asignados actualmente.")
            return

        st.subheader("Mis Asignaciones")
        
        # Display as a list of actionable cards or a table with selection
        for index, row in my_pickings.iterrows():
            folio = row['FOLIO']
            col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
            with col1:
                st.write(f"**Folio:** {folio}")
            with col2:
                st.write(f"Ruta: {row['RUTA']}")
            with col3:
                st.write(f"Estatus: {row['ESTATUS']}")
            with col4:
                if st.button("Abrir", key=f"btn_{folio}"):
                    st.session_state.selected_folio = folio
                    st.rerun()
        
        st.divider()

def show_folio_detail(folio, detail_worksheet):
    st.button("⬅️ Volver al listado", on_click=lambda: st.session_state.update({"selected_folio": None}))
    
    st.header(f"Gestión de Folio: {folio}")
    
    # Fetch existing details
    details_df = dtlm.get_folio_details(detail_worksheet, folio)
    count_scanned = len(details_df) if not details_df.empty else 0
    
    st.metric("Documentos Escaneados", count_scanned)
    
    col_scan, col_list = st.columns([1, 1])
    
    with col_scan:
        st.subheader("Agregar Nuevo QR")
        # Continuous-like scanning UI
        input_method = st.radio("Método:", ["Cámara", "Lector USB"], horizontal=True, label_visibility="collapsed")
        
        qr_data_found = None
        
        if input_method == "Cámara":
            # Camera input
            img_buffer = st.camera_input("Escanear", key=f"cam_{folio}", label_visibility="collapsed")
            if img_buffer:
                decoded = decode_image(img_buffer)
                if decoded:
                    qr_data_found = decoded[0]
                else:
                    st.warning("No se detectó QR")
        else:
            # USB Reader input - auto submit on enter
            qr_data_found = st.text_input("Haz clic y escanea", key=f"txt_{folio}")

        if qr_data_found:
            # Auto-register logic
            # Verify if it belongs to this folio? 
            # The prompt implies we attach it to this folio.
            # But we should check if the QR string *contains* the folio if possible, or just trust the user.
            # User said: "nutriendo el registro del folio... esos Qr que escanearia se agregaria"
            
            # Check if exists locally in the dataframe first to give fast feedback
            already_exists = False
            if not details_df.empty and "QR_DATA" in details_df.columns:
                 if qr_data_found in details_df["QR_DATA"].values:
                     already_exists = True
            
            if already_exists:
                st.warning(f"⚠️ El QR '{qr_data_found}' ya está registrado en este folio.")
            else:
                success, msg = dtlm.register_qr_scan(detail_worksheet, qr_data_found, st.session_state.user, status="SURTIDO")
                if success:
                    st.success(f"✅ Agregado: {qr_data_found}")
                    time.sleep(0.5) # Brief pause to show success
                    st.rerun() # Rerun to update list immediately
                else:
                    st.error(msg)

    with col_list:
        st.subheader("Registros en este Folio")
        if not details_df.empty:
            # Show simple table with delete button
            for idx, row in details_df.iterrows():
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.text(f"📄 {row.get('QR_DATA', 'Unknown')}")
                with c2:
                    if st.button("🗑️", key=f"del_{row.get('QR_DATA')}"):
                        dtlm.delete_qr_scan(detail_worksheet, row.get('QR_DATA'))
                        st.rerun()
        else:
            st.info("Aún no hay documentos escaneados.")

if __name__ == "__main__":
    init_session_state()
    if st.session_state.logged_in:
        main_app()
    else:
        login_page()
