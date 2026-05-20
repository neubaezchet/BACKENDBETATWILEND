"""
Test rápido de Mistral OCR — muestra el JSON crudo que devuelve la API.
Uso:
    python test_mistral_ocr.py ruta/al/archivo.pdf
"""
import sys
import json
import base64
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def main():
    if len(sys.argv) < 2:
        print("Uso: python test_mistral_ocr.py <ruta_pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"❌ Archivo no encontrado: {pdf_path}")
        sys.exit(1)

    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        print("❌ MISTRAL_API_KEY no está en el .env")
        sys.exit(1)

    print(f"[PDF]  Archivo  : {pdf_path.name}  ({pdf_path.stat().st_size / 1024:.1f} KB)")
    print(f"[KEY]  API Key  : {api_key[:8]}***")
    print("[...] Enviando a Mistral OCR...\n")

    from app.mistral_ocr_service import MistralDocumentAIOCR
    servicio = MistralDocumentAIOCR()

    pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
    resultado = servicio.procesar_pdf_base64(pdf_b64)

    if not resultado["exito"]:
        print(f"[ERROR] {resultado['error']}")
        sys.exit(1)

    print(f"[OK] Paginas procesadas : {resultado['paginas']}")
    print(f"[OK] Modelo usado       : {resultado['modelo']}")
    print(f"[OK] Usage info         : {resultado.get('usage_info', {})}")
    print("\n" + "=" * 60)
    print("JSON COMPLETO POR PÁGINA:")
    print("=" * 60 + "\n")

    for page in resultado.get("raw_pages", []):
        print(json.dumps(page, ensure_ascii=False, indent=2))
        print("\n" + "-" * 60 + "\n")

    print("=" * 60)
    print("TEXTO EXTRAÍDO COMPLETO (markdown):")
    print("=" * 60 + "\n")
    print(resultado["texto"])


if __name__ == "__main__":
    main()
