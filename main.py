import os
from flask import Flask, render_template, request
import google.generativeai as genai
from dotenv import load_dotenv
from lector_pdf import leer_todos_los_pdfs_en_fragmentos

# TF-IDF para ranking de fragmentos
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

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
        # Top-N fragmentos más relevantes
        top_fragmentos = encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8)
        contexto = "\n\n---\n\n".join(top_fragmentos)

        # Prompt reforzado (evita inventar y pide brevedad)
        prompt = f"""Responde SOLO usando la información del contexto.
Si el dato no aparece, dilo claramente y ofrece 2-3 puntos relacionados que SÍ estén en contexto.
Escribe de forma breve y clara en español.

Contexto:
{contexto}

Pregunta:
{pregunta}
"""

        respuesta = model.generate_content(prompt)
        texto_respuesta = respuesta.text

    except Exception as e:
        texto_respuesta = f"Error al generar respuesta: {e}"

    return render_template(
        "index.html",
        pregunta=pregunta,
        respuesta=texto_respuesta.encode("utf-8", "ignore").decode("utf-8")
    )

# --- Arranque (local/Render) ---
if __name__ == "__main__":
    # En local usa 5000; en Render usa el puerto de la variable PORT
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
