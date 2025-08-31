import os
from datetime import datetime

from flask import Flask, render_template, request
from markupsafe import Markup

import google.generativeai as genai
from dotenv import load_dotenv
from lector_pdf import leer_todos_los_pdfs_en_fragmentos

# TF-IDF para ranking de fragmentos
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

# Convertir Markdown -> HTML
import markdown

# Guardar preguntas sin respuesta en Word
from docx import Document

# --- Configuración de claves ---
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("❌ No se encontró la clave GOOGLE_API_KEY en el archivo .env")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-pro-latest")

# --- Carga de documentos ---
fragmentos = leer_todos_los_pdfs_en_fragmentos("data/pdf_data")
if not fragmentos:
    fragmentos = ["[No hay fragmentos cargados de los PDF.]"]

app = Flask(__name__)

# --- Utilidades de persistencia ---

LEES_DIR = "lees_resp"
LEES_DOCX = os.path.join(LEES_DIR, "respuestas.docx")

def asegurar_docx():
    """Crea carpeta y docx si no existen."""
    os.makedirs(LEES_DIR, exist_ok=True)
    if not os.path.exists(LEES_DOCX):
        doc = Document()
        doc.add_heading("Preguntas sin respuesta / con error", level=1)
        doc.add_paragraph(f"Documento creado el {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_paragraph("")  # línea en blanco
        doc.save(LEES_DOCX)

def anotar_pendiente(pregunta: str, motivo: str, contexto_preview: str = ""):
    """Añade una entrada al Word sin sobrescribir lo anterior."""
    asegurar_docx()
    doc = Document(LEES_DOCX)
    doc.add_heading(datetime.now().strftime('%Y-%m-%d %H:%M'), level=2)
    doc.add_paragraph(f"Pregunta: {pregunta}")
    doc.add_paragraph(f"Motivo: {motivo}")
    if contexto_preview:
        doc.add_paragraph("Contexto usado (preview):")
        doc.add_paragraph(contexto_preview[:1200])  # para que no sea enorme
    doc.add_paragraph("")  # separador
    doc.save(LEES_DOCX)

# --- Búsqueda de fragmentos por TF-IDF ---
def encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8):
    # Vectorizador con n-gramas (1 y 2) para captar frases como "jefe de cocina"
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
    docs = fragmentos + [pregunta]
    tfidf = vectorizer.fit_transform(docs)

    # Similitud coseno entre la pregunta (último vector) y los fragmentos
    sims = linear_kernel(tfidf[-1], tfidf[:-1]).flatten()
    top_idx = sims.argsort()[::-1][:max_resultados]

    # Si la similitud es bajísima, devolvemos algunos fragmentos por defecto
    if sims[top_idx[0]] < 0.05:
        return fragmentos[:3]

    return [fragmentos[i] for i in top_idx]

# --- Rutas ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/preguntar", methods=["POST"])
def preguntar():
    pregunta = request.form.get("pregunta", "").strip()

    try:
        # 1) Top-N fragmentos más relevantes
        top_fragmentos = encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8)
        contexto = "\n\n---\n\n".join(top_fragmentos)

        # 2) Prompt reforzado (evita inventar y pide formato Markdown)
        prompt = f"""Responde SOLO usando la información del contexto.
- Si el dato no aparece, dilo claramente y ofrece 2-3 puntos relacionados que SÍ estén en contexto.
- Responde en **Markdown** (usa títulos, listas y tablas cuando ayuden).
- Sé breve y claro en español.

Contexto:
{contexto}

Pregunta:
{pregunta}
"""

        respuesta = model.generate_content(prompt)
        texto_respuesta = (respuesta.text or "").strip()

        # 3) Detectar si la respuesta es "pendiente"
        es_pendiente = False
        lower = texto_respuesta.lower()
        # Heurísticas simples: puedes ajustar las frases a tu gusto
        if not texto_respuesta:
            es_pendiente = True
            motivo = "Respuesta vacía"
        elif "no aparece" in lower or "no está en el contexto" in lower or "no se encuentra en el contexto" in lower:
            es_pendiente = True
            motivo = "No cubierto por el contexto"
        else:
            motivo = ""

        if es_pendiente:
            anotar_pendiente(pregunta, motivo, contexto_preview=contexto)

        # 4) Formato bonito: Markdown -> HTML y marcar como seguro para renderizar
        html = markdown.markdown(texto_respuesta, extensions=["extra"])
        html_seguro = Markup(html)  # evita que Jinja escape el HTML

        return render_template(
            "index.html",
            pregunta=pregunta,
            respuesta=html_seguro
        )

    except Exception as e:
        # Registrar también el error en el Word
        anotar_pendiente(pregunta, f"Error: {e}")
        texto_respuesta = f"Error al generar respuesta: {e}"
        html = markdown.markdown(texto_respuesta)
        return render_template(
            "index.html",
            pregunta=pregunta,
            respuesta=Markup(html)
        )

# --- Arranque (local/Render) ---
if __name__ == "__main__":
    # En local usa 5000; en Render usa el puerto de la variable PORT
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
