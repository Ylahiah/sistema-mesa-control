import streamlit as st
import pandas as pd
import data_manager as dm
import time

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
    if not worksheet:
        st.error("No se pudo acceder a la hoja de cálculo.")
        st.stop()

    # Load Data
    with st.spinner("Cargando datos..."):
        df = dm.load_data(worksheet)

    if st.session_state.role == "RESPONSABLE":
        responsable_view(df, worksheet)
    else:
        capturista_view(df, worksheet)

def responsable_view(df, worksheet):
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
        st.subheader("Cambio de Estatus Rápido")
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

def capturista_view(df, worksheet):
    st.title("Panel de Capturista")
    
    # Filter for current user
    my_pickings = df[df["CAPTURISTA"] == st.session_state.user].copy()
    
    if my_pickings.empty:
        st.info("No tienes pickings asignados actualmente.")
        return

    st.metric("Mis Pickings Pendientes", len(my_pickings[my_pickings["ESTATUS"] != "LIBERADO"]))
    
    st.subheader("Mis Asignaciones")
    
    # Selection mechanism
    # Using a dataframe with selection or just a selectbox
    # The prompt says: "lista desplegable o checkboxes"
    
    # Let's show the table first
    st.dataframe(my_pickings, use_container_width=True)
    
    st.divider()
    st.subheader("Acciones")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_folios = st.multiselect("Selecciona los Folios a procesar", my_pickings["FOLIO"].unique())
        
    with col2:
        st.write("Selecciona el nuevo estatus:")
        # Generate buttons for each status
        for status in STATUS_OPTIONS_CAPTURISTA:
            if st.button(f"Marcar como {status}", use_container_width=True):
                if not selected_folios:
                    st.warning("Debes seleccionar al menos un folio.")
                else:
                    progress_bar = st.progress(0)
                    errors = []
                    for idx, folio in enumerate(selected_folios):
                        success, msg = dm.update_status(worksheet, str(folio), status, st.session_state.user)
                        if not success:
                            errors.append(f"Folio {folio}: {msg}")
                        progress_bar.progress((idx + 1) / len(selected_folios))
                    
                    if not errors:
                        st.success(f"Se actualizaron {len(selected_folios)} pickings correctamente.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Errores: {'; '.join(errors)}")

if __name__ == "__main__":
    init_session_state()
    if st.session_state.logged_in:
        main_app()
    else:
        login_page()
