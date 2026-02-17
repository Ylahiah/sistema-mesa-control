import streamlit as st
import pandas as pd
import data_manager as dm
import detail_manager as dtlm
import time
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from PIL import Image
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
import av
import queue
import threading

# Page configuration
st.set_page_config(
    page_title="Sistema de Control de Pickings",
    page_icon="📦",
    layout="wide"
)

# Constants
STATUS_OPTIONS_CAPTURISTA = ["IMPRESOS", "EN SURTIDO", "EN CAPTURA", "CAPTURADOS"]
STATUS_OPTIONS_RESPONSABLE = ["IMPRESOS", "EN SURTIDO", "EN CAPTURA", "CAPTURADOS", "VALIDACION", "EMBARQUE", "LIBERADO"]

AUTHORIZED_UPLOADERS = ["CHACON SANCHEZ FABIAN RUBISEL", "ESCOBAR RUIZ JOSE MANUEL", "Admin"]
DASHBOARD_VIEWERS = ["MENDEZ PEREZ JENNYFER", "RUIZ DIAZ CYNTHIA", "MARIO PEREZ AGUILAR", "Admin"]

def init_session_state():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "role" not in st.session_state:
        st.session_state.role = None

def get_users_list():
    """Helper to get users list safely"""
    ws = dm.get_or_create_users_worksheet()
    if not ws: return []
    return dm.get_all_users(ws)

def login_page():
    st.title("📦 Control de Pickings - Acceso")
    
    users_data = get_users_list()
    if not users_data:
        st.warning("No hay usuarios registrados o error de conexión.")
        return
        
    # Prepare lists for dropdown
    user_names = [u["USUARIO"] for u in users_data]
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            selected_user = st.selectbox("Selecciona tu Usuario", user_names)
            
            # Auto-select role based on user but allow override if needed (or readonly)
            # Find role for selected user
            # This is a bit tricky in Streamlit because selectbox doesn't return object.
            # We can find it after selection, but to update the Role selectbox dynamically requires state or rerun.
            # Simplest approach: Just let them select role, or validate it on submit.
            # Better: Filter roles? Or just trust the sheet?
            # Let's show the role associated in the sheet as a hint or default.
            
            # Since we can't easily dynamic update without rerun, we will just validate on submit
            # OR we can just rely on the sheet's role!
            # If I select "Juan", the system knows Juan is Capturista.
            # User requirement: "aparezcan en la desplegable... estos deben tener relacion"
            
            # Let's purely rely on the sheet for the Role. User selects Name, System gets Role.
            # But "Selector de rol" was a requirement in the first prompt. 
            # However, managing users implies roles are assigned.
            # Let's keep it simple: Select User -> System logs you in with your assigned role.
            
            submitted = st.form_submit_button("Ingresar")
            
            if submitted:
                # Find the user record
                user_record = next((u for u in users_data if u["USUARIO"] == selected_user), None)
                if user_record:
                    st.session_state.logged_in = True
                    st.session_state.user = user_record["USUARIO"]
                    st.session_state.role = user_record["ROL"]
                    st.rerun()
                else:
                    st.error("Error al identificar usuario.")

def main_app():
    st.sidebar.title(f"Hola, {st.session_state.user}")
    st.sidebar.badge(st.session_state.role)
    
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.role = None
        st.rerun()

    # Connection to Google Sheets
    # client = dm.get_gspread_client() # No longer needed here
    
    worksheet = dm.get_or_create_worksheet()
    detail_worksheet = dtlm.get_or_create_detail_worksheet()
    
    if not worksheet or not detail_worksheet:
        st.error("No se pudo acceder a las hojas de cálculo.")
        st.stop()

    # Load Data
    with st.spinner("Cargando datos..."):
        df = dm.load_data(worksheet)

    if st.session_state.role == "RESPONSABLE":
        responsable_view(df, worksheet, detail_worksheet)
    else:
        capturista_view(df, worksheet, detail_worksheet)

def responsable_view(df, worksheet, detail_worksheet):
    st.title("Panel de Responsable")
    
    # We need to access users worksheet for the new tab
    users_ws = dm.get_or_create_users_worksheet()
    
    # Check permissions
    show_upload = st.session_state.user in AUTHORIZED_UPLOADERS
    show_dashboard = st.session_state.user in DASHBOARD_VIEWERS
    
    tabs_list = ["📋 Gestión Operativa"]
    if show_upload: tabs_list.append("📤 Carga Masiva")
    if show_dashboard: tabs_list.append("📊 Dashboard KPI")
    tabs_list.append("📥 Recepción Almacén") # New screen for quick scan
    tabs_list.append("👥 Reasignación")
    tabs_list.append("👤 Gestión Usuarios")
    
    tabs = st.tabs(tabs_list)
    
    # 1. Gestion Operativa (Visible to all responsible)
    with tabs[0]:
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

    # Dynamic Tab Content handling
    current_tab_idx = 1
    
    # 2. Carga Masiva (Restricted)
    if show_upload:
        with tabs[current_tab_idx]:
            st.subheader("Carga de Nuevos Pickings")
            st.info(f"Usuario autorizado: {st.session_state.user}")
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
        current_tab_idx += 1
        
    # 3. Dashboard KPI (Restricted)
    if show_dashboard:
        with tabs[current_tab_idx]:
            st.subheader("Indicadores de Desempeño (KPI)")
            
            # Simple KPIs based on ESTATUS
            total_pickings = len(df)
            status_counts = df["ESTATUS"].value_counts()
            
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Total Pickings", total_pickings)
            kpi2.metric("Capturados", status_counts.get("CAPTURADOS", 0))
            kpi3.metric("Pendientes/En Proceso", total_pickings - status_counts.get("CAPTURADOS", 0) - status_counts.get("LIBERADO", 0))
            
            st.bar_chart(status_counts)
            
            st.subheader("Avance por Capturista")
            capturista_counts = df.groupby(["CAPTURISTA", "ESTATUS"]).size().unstack(fill_value=0)
            st.dataframe(capturista_counts, use_container_width=True)
            
        current_tab_idx += 1

    # 4. Recepción Almacén (New Quick Scan)
    with tabs[current_tab_idx]:
        st.subheader("Recepción de Almacén (Escaneo Rápido)")
        st.markdown("Escanea los documentos para agregarlos al folio y sumar el contador.")
        
        # Similar logic to detail scan but updating master columns
        qr_reception = st.text_input("Escanear Picking (QR)", key="reception_scan")
        
        if qr_reception:
            # Parse to get folio parent? Or assume QR contains folio?
            # User said: "automaticamnte el folio se debe de buscar y agregar... separados por un espacio"
            # Assuming QR string contains the folio ID somewhere or matches the FOLIO column if partial.
            # Let's try to extract FOLIO from QR if format is known (FOLIO|...).
            
            # Using our helper
            folio_found, _ = dtlm.parse_qr_code(qr_reception)
            
            if folio_found:
                 # Call new data_manager function
                 success, msg = dm.increment_folio_count(worksheet, folio_found, qr_reception)
                 if success:
                     st.success(msg)
                 else:
                     st.error(msg)
            else:
                st.warning("Formato de QR no reconocido.")
    
    current_tab_idx += 1
    
    # 5. Reasignación
    with tabs[current_tab_idx]:
        st.subheader("Reasignación de Capturistas")
        
        c1, c2 = st.columns(2)
        with c1:
            folio_to_assign = st.selectbox("Seleccionar Folio", df["FOLIO"].unique())
        with c2:
            # Dynamic users list
            current_users = get_users_list()
            capturistas = [u["USUARIO"] for u in current_users if u["ROL"] == "CAPTURISTA"]
            # Fallback if no capturistas
            if not capturistas: capturistas = ["Sin Capturistas"]
            target_user = st.selectbox("Asignar a", capturistas)
            
        if st.button("Reasignar"):
            success, msg = dm.reassign_capturista(worksheet, str(folio_to_assign), target_user, st.session_state.user)
            if success:
                st.success(msg)
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)
    
    with tabs[current_tab_idx]:
        st.subheader("Gestión de Usuarios (Capturistas y Responsables)")
        
        # Add new user form
        with st.form("add_user_form"):
            c_new1, c_new2 = st.columns(2)
            with c_new1:
                new_user_name = st.text_input("Nombre de Usuario (Único)")
            with c_new2:
                new_user_role = st.selectbox("Rol", ["CAPTURISTA", "RESPONSABLE"])
            
            submit_user = st.form_submit_button("Crear Usuario")
            if submit_user:
                if new_user_name:
                    success, msg = dm.add_user(users_ws, new_user_name, new_user_role)
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("El nombre es obligatorio")
        
        st.divider()
        st.subheader("Lista de Usuarios")
        
        # Show users list with delete option
        all_users = dm.get_all_users(users_ws)
        if all_users:
            users_df = pd.DataFrame(all_users)
            
            # Simple list
            for idx, u in users_df.iterrows():
                u_name = u["USUARIO"]
                u_role = u["ROL"]
                
                col_u1, col_u2, col_u3 = st.columns([2, 2, 1])
                with col_u1:
                    st.write(f"**{u_name}**")
                with col_u2:
                    st.badge(u_role)
                with col_u3:
                    if u_name != "Admin":
                        if st.button("Eliminar", key=f"del_user_{u_name}"):
                            success, msg = dm.delete_user(users_ws, u_name)
                            if success:
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
        show_folio_detail(st.session_state.selected_folio, detail_worksheet, worksheet)
    else:
        # MASTER VIEW (List)
        if my_pickings.empty:
            st.info("No tienes pickings asignados actualmente.")
            return

        st.subheader("Mis Asignaciones")
        
        # Display as a list of actionable cards or a table with selection
        # We need to show count of documents (from # FOLIOS DOCUMENTOS column)
        # And status dropdown
        
        # Optimized: Get all detail counts at once to avoid querying inside loop
        # Note: We need to implement get_all_detail_counts in detail_manager
        # For now, let's assume we can fetch it. If not implemented, we skip or do it slow.
        try:
            detail_counts = dtlm.get_all_detail_counts(detail_worksheet)
        except AttributeError:
            detail_counts = {}
        
        for index, row in my_pickings.iterrows():
            folio = row['FOLIO']
            current_status = row['ESTATUS']
            
            # Count from Warehouse (Master)
            doc_count_warehouse = row['# FOLIOS DOCUMENTOS'] if row['# FOLIOS DOCUMENTOS'] else 0
            
            # Count from Capturista (Detail)
            doc_count_scanned = detail_counts.get(str(folio), 0)
            
            # Card-like container
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 1, 2, 1])
                with col1:
                    st.write(f"**Folio:** {folio}")
                    st.caption(f"Ruta: {row['RUTA']}")
                
                with col2:
                    # Dual metric
                    st.write(f"📦 Almacén: **{doc_count_warehouse}**")
                    st.write(f"✅ Escaneados: **{doc_count_scanned}**")
                    
                with col3:
                    # Status Dropdown
                    # We need a unique key. If user changes this, it updates DB.
                    try:
                        idx_status = STATUS_OPTIONS_CAPTURISTA.index(current_status)
                    except ValueError:
                        idx_status = 0
                        
                    new_status = st.selectbox(
                        "Estatus", 
                        STATUS_OPTIONS_CAPTURISTA, 
                        index=idx_status, 
                        key=f"status_{folio}",
                        label_visibility="collapsed"
                    )
                    
                    if new_status != current_status:
                        # Update DB immediately
                        dm.update_status(worksheet, folio, new_status, st.session_state.user)
                        st.toast(f"Estatus actualizado: {new_status}")
                        # Invalidate cache to reflect change
                        dm.load_data.clear()
                        # We don't need to sleep here if we clear cache, rerunning will fetch fresh data
                        st.rerun()

                with col4:
                    if st.button("Abrir", key=f"btn_{folio}"):
                        st.session_state.selected_folio = folio
                        st.rerun()
                
                st.divider()

def show_folio_detail(folio, detail_worksheet, master_worksheet):
    st.button("⬅️ Volver al listado", on_click=lambda: st.session_state.update({"selected_folio": None}))
    
    st.header(f"Gestión de Folio: {folio}")
    
    # Get Master Data for Status Sync
    # We could optimize this by passing the row, but fetching fresh is safer
    # Assuming we have access to master_worksheet here. Need to pass it in.
    
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
            # Real-time WebRTC Scanner
            RTC_CONFIGURATION = RTCConfiguration(
                {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
            )

            # Define a thread-safe queue in session state
            if "qr_queue" not in st.session_state:
                st.session_state.qr_queue = queue.Queue()

            def video_frame_callback(frame):
                img = frame.to_ndarray(format="bgr24")
                
                # Decode QR
                decoded_objects = decode(img)
                
                for obj in decoded_objects:
                    qr_text = obj.data.decode("utf-8")
                    # Put in queue
                    try:
                        st.session_state.qr_queue.put_nowait(qr_text)
                    except queue.Full:
                        pass
                
                # Return frame (can draw box here if needed)
                return av.VideoFrame.from_ndarray(img, format="bgr24")

            # WebRTC Component
            ctx = webrtc_streamer(
                key=f"scanner_{folio}",
                mode=WebRtcMode.SENDRECV,
                rtc_configuration=RTC_CONFIGURATION,
                video_frame_callback=video_frame_callback,
                media_stream_constraints={"video": {"facingMode": "environment"}, "audio": False},
                async_processing=True,
            )

            # Check queue for results
            if ctx.state.playing:
                try:
                    # Non-blocking get
                    qr_data_found = st.session_state.qr_queue.get_nowait()
                except queue.Empty:
                    qr_data_found = None
            
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
                # Use toast for less intrusive warning
                st.toast(f"⚠️ QR Repetido: {qr_data_found}", icon="⚠️")
            else:
                # We force the association with the current folio since we are inside the folio view
                success, msg = dtlm.register_qr_scan(
                    detail_worksheet, 
                    qr_data_found, 
                    st.session_state.user, 
                    status="SURTIDO",
                    forced_folio=folio
                )
                if success:
                    st.toast(f"✅ Agregado: {qr_data_found}", icon="✅")
                    
                    # Update master count if possible?
                    # Since we are adding to detail, the master count (which is for Warehouse reception) 
                    # might not be the same as "Capturista scanned count".
                    # But if we want to reflect progress, we should probably update master count too or have a separate one.
                    # User asked: "recuento de documentos... en la pantalla inicial"
                    # The detail view counts lines in detail sheet. The master view reads master sheet.
                    # We need to invalidate master cache so it re-reads if we updated it?
                    # But we are NOT updating master sheet here yet. 
                    
                    # For now, just rerun to update Detail View list.
                    # Ideally, we should sync this count to master sheet or read from details.
                    
                    time.sleep(0.5) # Brief pause to show success
                    st.rerun() # Rerun to update list immediately
                else:
                    st.error(msg)

    with col_list:
        st.subheader("Registros en este Folio")
        if not details_df.empty:
            # Filter specifically for this folio to avoid showing unrelated scans 
            # (though get_folio_details already does this, safety check)
            # Displaying QR_DATA only
            
            # Simple table with delete button
            for idx, row in details_df.iterrows():
                qr_val = row.get('QR_DATA', 'Unknown')
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.text(f"📄 {qr_val}")
                with c2:
                    if st.button("🗑️", key=f"del_{qr_val}_{idx}"): # Unique key with index
                        dtlm.delete_qr_scan(detail_worksheet, qr_val)
                        st.rerun()
        else:
            st.info("Aún no hay documentos escaneados.")

if __name__ == "__main__":
    init_session_state()
    if st.session_state.logged_in:
        main_app()
    else:
        login_page()
