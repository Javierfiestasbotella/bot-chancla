import os
import PyPDF2

def leer_todos_los_pdfs_en_fragmentos(carpeta_relativa):
    base_dir = os.path.dirname(os.path.abspath(__file__))  # ruta absoluta del proyecto
    carpeta = os.path.join(base_dir, carpeta_relativa)     # une la base con 'data/pdf_data'

    if not os.path.exists(carpeta):
        raise FileNotFoundError(f"La carpeta {carpeta} no existe")

    fragmentos = []
    for archivo in os.listdir(carpeta):
        if archivo.endswith(".pdf"):
            ruta_pdf = os.path.join(carpeta, archivo)
            with open(ruta_pdf, "rb") as f:
                lector = PyPDF2.PdfReader(f)
                for pagina in lector.pages:
                    texto = pagina.extract_text() or ""
                    fragmentos.append(texto.strip())

    return fragmentos
