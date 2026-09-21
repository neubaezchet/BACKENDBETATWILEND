"""
Contrato de almacenamiento — Fase 0
IncaNeurobaeza - 2026

Define las operaciones que EntregaManager necesita de una nube de
almacenamiento, independientemente del proveedor. Hoy solo existe el
adaptador implícito de Google (ver app/entrega_manager.py) — este archivo es
documentación/andamiaje para las fases siguientes, no está wireado todavía.

Cuando se cree la cuenta de Neurobaeza en OneDrive/SharePoint (Fase 1) y en
Dropbox (Fase 2), cada una implementa esta interfaz y EntregaManager elige
el adaptador según TenantConfig.storage_provider — sin tocar el resto del
flujo (recepción, validación, radicación).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class StorageProvider(ABC):
    """Puerto único que cualquier nube (Google, Microsoft, Dropbox) debe cumplir."""

    @abstractmethod
    def ensure_folder(self, name: str, parent_id: str) -> str:
        """Crea la carpeta si no existe y devuelve su id. Idempotente."""
        ...

    @abstractmethod
    def upload(self, file_path: Path, parent_id: str, filename: str) -> dict:
        """Sube un archivo nuevo. Devuelve {id, link}."""
        ...

    @abstractmethod
    def copy(self, file_id: str, dest_parent_id: str) -> dict:
        """Copia un archivo existente a otra carpeta. Devuelve {id, link}."""
        ...

    @abstractmethod
    def move(self, file_id: str, new_parent_id: str) -> None:
        """Mueve un archivo a otra carpeta."""
        ...

    @abstractmethod
    def replace_content(self, file_id: str, file_path: Path) -> dict:
        """Reemplaza el contenido de un archivo existente (misma id)."""
        ...

    @abstractmethod
    def delete(self, file_id: str) -> None:
        """Elimina un archivo."""
        ...

    @abstractmethod
    def download(self, file_id: str) -> bytes:
        """Descarga el contenido de un archivo."""
        ...

    @abstractmethod
    def share_with_email(self, folder_id: str, email: str, role: str = "writer") -> None:
        """Comparte una carpeta con un correo. Idempotente."""
        ...

    @abstractmethod
    def find_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Busca un archivo/carpeta por nombre dentro de un padre. Devuelve None si no existe."""
        ...
