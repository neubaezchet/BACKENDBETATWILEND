"""
Gestor de la carpeta Entrega — Copia compartida con el cliente
IncaNeurobaeza - 2026

FASE 0 del sistema de almacenamiento multi-proveedor (ver app/storage/contract.py):

- El Drive de Neurobaeza (Incapacidades/Completas/Incompletas) sigue siendo
  la ÚNICA fuente de verdad y el único histórico. Este módulo NUNCA lee ni
  modifica esas carpetas ni caso.drive_link.
- Entrega/{Empresa}/{Año}/{Periodo}/{Tipo}/ es una copia paralela, dentro de
  la MISMA cuenta de Neurobaeza, compartida como editor con el correo de la
  empresa. Lo que el cliente haga ahí (editar, mover, borrar) nunca toca el
  histórico: son archivos distintos (copias), no el mismo file_id.
- Hoy solo hay adaptador para Google Drive. Cuando existan las cuentas de
  Neurobaeza en OneDrive/SharePoint (Fase 1) y Dropbox (Fase 2), este
  módulo elige adaptador según TenantConfig.storage_provider sin tocar el
  resto del flujo (recepción, validación, radicación).

Fail-safe por diseño: ningún método de este módulo debe poder romper el
flujo principal. Todo error se atrapa y se registra; el caller nunca
necesita envolver estas llamadas en try/except, pero se recomienda hacerlo
de todos modos en los puntos de enganche (ver main.py y validador.py).
"""

from datetime import datetime

from app.drive_uploader import (
    get_authenticated_service,
    create_folder_if_not_exists,
    normalize_tipo_incapacidad,
    get_periodo_folder_name,
    GOOGLE_SHARED_DRIVE_ID,
)


class EntregaManager:
    """Gestor de la carpeta Entrega (copia compartida con el cliente)."""

    def __init__(self):
        self.service = None
        self.entrega_root_id = None

    def _get_service(self):
        """Obtiene servicio de Drive bajo demanda."""
        if self.service is None:
            self.service = get_authenticated_service()
        return self.service

    def _init_entrega_root(self):
        """Inicializa/obtiene la carpeta raíz Entrega/."""
        self._get_service()
        if not self.entrega_root_id:
            base_root = GOOGLE_SHARED_DRIVE_ID if GOOGLE_SHARED_DRIVE_ID != "root" else 'root'
            self.entrega_root_id = create_folder_if_not_exists(
                self.service, b'Entrega', base_root
            )
        return self.entrega_root_id

    def _extract_file_id(self, drive_link):
        """Extrae el file_id de un link de Google Drive."""
        if not drive_link:
            return None
        if '/file/d/' in drive_link:
            return drive_link.split('/file/d/')[1].split('/')[0]
        elif 'id=' in drive_link:
            return drive_link.split('id=')[1].split('&')[0]
        return None

    # ==================== ACTIVACIÓN (ONBOARDING) ====================

    def activar_para_empresa(self, empresa_nombre: str, correo_cliente: str) -> dict:
        """
        Crea (si no existe) Entrega/{Empresa}/ y la comparte con el correo del
        cliente como editor. Idempotente: llamarla varias veces no duplica
        carpetas ni falla si el permiso ya existía.

        Returns:
            dict: {ok, folder_id, folder_link, error}
        """
        try:
            self._init_entrega_root()
            empresa_folder_id = create_folder_if_not_exists(
                self.service, empresa_nombre.encode(), self.entrega_root_id
            )

            correo_limpio = (correo_cliente or "").strip()
            if correo_limpio:
                try:
                    self.service.permissions().create(
                        fileId=empresa_folder_id,
                        body={'role': 'writer', 'type': 'user', 'emailAddress': correo_limpio},
                        sendNotificationEmail=True,
                        emailMessage=(
                            f"Esta es la carpeta de {empresa_nombre} en IncaNeurobaeza. "
                            "Aquí encontrará copia de las incapacidades recibidas y su estado."
                        ),
                        supportsAllDrives=True,
                    ).execute()
                    print(f"✅ Entrega/{empresa_nombre} compartida con {correo_limpio}")
                except Exception as perm_err:
                    # Compartir de nuevo con el mismo correo no es un error real.
                    err_str = str(perm_err).lower()
                    if 'already' not in err_str and 'duplicate' not in err_str:
                        print(f"⚠️ No se pudo compartir Entrega/{empresa_nombre} con {correo_limpio}: {perm_err}")

            folder_link = f"https://drive.google.com/drive/folders/{empresa_folder_id}"
            return {"ok": True, "folder_id": empresa_folder_id, "folder_link": folder_link, "error": None}

        except Exception as e:
            print(f"❌ Error activando Entrega para {empresa_nombre}: {e}")
            return {"ok": False, "folder_id": None, "folder_link": None, "error": str(e)}

    # ==================== ESPEJO DE CASOS ====================

    def copiar_caso_a_entrega(self, caso):
        """
        Copia la versión actual del archivo del caso (histórico) a
        Entrega/{Empresa}/{Año}/{Periodo}/{Tipo}/. Si ya existe una copia de
        ese serial en la carpeta destino, la reemplaza (para reflejar
        ediciones del validador, p. ej. un PDF mejorado).

        No lanza excepciones: cualquier fallo se registra y se ignora, para
        no afectar nunca el flujo principal de recepción/validación.

        Returns:
            str | None: link de la copia en Entrega, o None si no aplica / falló.
        """
        try:
            if not caso.drive_link:
                return None

            empresa_nombre = caso.empresa.nombre if getattr(caso, "empresa", None) else None
            company_id = getattr(caso, "company_id", None)
            if not empresa_nombre or not company_id:
                return None

            from app.database import TenantConfig, SessionLocal

            db = SessionLocal()
            try:
                config = db.query(TenantConfig).filter(
                    TenantConfig.company_id == company_id
                ).first()
            finally:
                db.close()

            if not config or config.entrega_status != 'ok':
                return None  # Empresa sin Entrega activada — no gastar cuota de API.
            if (config.storage_provider or 'google') != 'google':
                # OneDrive/Dropbox llegan en fases siguientes (app/storage/contract.py).
                return None

            file_id = self._extract_file_id(caso.drive_link)
            if not file_id:
                return None

            self._init_entrega_root()
            empresa_folder_id = create_folder_if_not_exists(
                self.service, empresa_nombre.encode(), self.entrega_root_id
            )

            año_actual = str(datetime.now().year)
            periodo = get_periodo_folder_name(config.ciclo_reporte)
            tipo_raw = caso.tipo.value if getattr(caso, "tipo", None) else 'General'
            tipo_normalizado = normalize_tipo_incapacidad(tipo_raw, getattr(caso, "subtipo", None))

            año_folder_id = create_folder_if_not_exists(self.service, año_actual.encode(), empresa_folder_id)
            periodo_folder_id = create_folder_if_not_exists(self.service, periodo.encode(), año_folder_id)
            tipo_folder_id = create_folder_if_not_exists(self.service, tipo_normalizado.encode(), periodo_folder_id)

            # ¿Ya hay una copia de este serial en Entrega? Si sí, se reemplaza
            # (no se duplica) para reflejar ediciones posteriores del validador.
            existentes = self.service.files().list(
                q=f"name contains '{caso.serial}' and '{tipo_folder_id}' in parents and trashed=false",
                spaces='drive', fields='files(id, name)', pageSize=5,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute().get('files', [])

            for viejo in existentes:
                if caso.serial in viejo.get('name', ''):
                    try:
                        self.service.files().delete(fileId=viejo['id'], supportsAllDrives=True).execute()
                    except Exception:
                        pass  # No crítico: seguimos creando la copia nueva igual.

            copiado = self.service.files().copy(
                fileId=file_id,
                body={'parents': [tipo_folder_id]},
                supportsAllDrives=True,
            ).execute()

            print(f"✅ Caso {caso.serial} espejado a Entrega/{empresa_nombre}/{año_actual}/{periodo}/{tipo_normalizado}/")
            return f"https://drive.google.com/file/d/{copiado.get('id')}/view"

        except Exception as e:
            print(f"⚠️ Error espejando caso {getattr(caso, 'serial', '?')} a Entrega (no afecta el flujo principal): {e}")
            return None


entrega_mgr = EntregaManager()
