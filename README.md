# Sistema de Control de Pickings 📦

Este es un sistema de gestión de pickings desarrollado en Python con Streamlit y Google Sheets como base de datos. Permite conectar los procesos físicos con el control digital en tiempo real.

## Características Principales

- **Roles Definidos:** Responsable (Administrador) y Capturista (Operativo).
- **Base de Datos en la Nube:** Usa Google Sheets para almacenamiento y persistencia.
- **Validaciones:** Evita duplicidad de folios y restringe permisos por rol.
- **Interfaz Web:** Accesible desde cualquier navegador vía Streamlit.

## Estructura del Proyecto

```
/
├── app.py              # Aplicación principal Streamlit
├── data_manager.py     # Módulo de conexión y lógica con Google Sheets
├── requirements.txt    # Dependencias del proyecto
└── README.md           # Instrucciones
```

## Configuración Previa (Google Cloud Platform)

Para que la aplicación funcione, necesitas una cuenta de servicio de Google:

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un nuevo proyecto.
3. Habilita las siguientes APIs:
   - **Google Sheets API**
   - **Google Drive API**
4. Crea una **Cuenta de Servicio** (Service Account):
   - Ve a "IAM y administración" > "Cuentas de servicio".
   - Crea una nueva cuenta.
   - Crea una clave en formato JSON y descárgala.
5. **Importante:** Abre el archivo JSON y copia el email `client_email`.
6. Ve a tu Google Sheet (o crea uno nuevo) y compártelo (botón "Share") con ese email, dándole permisos de **Editor**.

## Configuración de Secretos

### Localmente
Crea una carpeta `.streamlit` y dentro un archivo `secrets.toml`:

```toml
[gcp_service_account]
type = "service_account"
project_id = "tu-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n..."
client_email = "tu-email@..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

*Nota: Copia el contenido de tu archivo JSON descargado y ajústalo al formato TOML anterior.*

### En Streamlit Cloud
1. Al desplegar la app, ve a "Advanced Settings".
2. Pega el contenido de tu archivo JSON en el área de "Secrets" con el formato TOML bajo la cabecera `[gcp_service_account]`.

## Ejecución Local

1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Ejecuta la aplicación:
   ```bash
   streamlit run app.py
   ```

## Despliegue en Streamlit Community Cloud

1. Sube este código a un repositorio de GitHub.
2. Ingresa a [share.streamlit.io](https://share.streamlit.io/).
3. Conecta tu cuenta de GitHub y selecciona el repositorio.
4. En la configuración de despliegue, añade tus secretos de Google Cloud (como se explicó arriba).
5. ¡Listo! Tu aplicación estará disponible públicamente.

## Uso del Sistema

### Rol Responsable
- **Gestión Operativa:** Visualiza todos los pickings, filtra y cambia estatus.
- **Carga Masiva:** Sube archivos Excel (.xlsx) para añadir nuevos registros. El Excel debe tener al menos la columna `FOLIO`.
- **Reasignación:** Cambia el capturista asignado a un folio.

### Rol Capturista
- Solo visualiza los pickings asignados a su usuario.
- Puede cambiar el estatus a "SURTIDO", "CAPTURADO", "EN_VALIDACION" o "DOC_LISTA".
- No puede liberar pickings ni ver los de otros compañeros.
