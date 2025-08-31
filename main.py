import os
from flask import Flask, render_template, request
import google.generativeai as genai
from dotenv import load_dotenv
from lector_pdf import leer_todos_los_pdfs_en_fragmentos

# Carga la clave
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("❌ No se encontró la clave GOOGLE_API_KEY en el archivo .env")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-pro-latest")

# Lee todos los fragmentos al arrancar
fragmentos = leer_todos_los_pdfs_en_fragmentos("data/pdf_data")

app = Flask(__name__)

def encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=3):
    pregunta = pregunta.lower()
    puntuaciones = []

    for fragmento in fragmentos:
        fragmento_bajo = fragmento.lower()
        puntuacion = sum(1 for palabra in pregunta.split() if palabra in fragmento_bajo)
        puntuaciones.append((puntuacion, fragmento))

    # Ordenamos por puntuación de mayor a menor
    puntuaciones.sort(reverse=True, key=lambda x: x[0])

    # Nos quedamos con los fragmentos más relevantes
    mejores = [frag for punt, frag in puntuaciones if punt > 0][:max_resultados]

    return mejores or fragmentos[:1]


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/preguntar", methods=["POST"])
def preguntar():
    pregunta = request.form["pregunta"]

    try:
        contexto = "\n\n".join(encontrar_fragmentos_relacionados(pregunta, fragmentos))
        prompt = f"""Responde con claridad y de forma útil a la siguiente pregunta utilizando este contexto:

Contexto:
{contexto}

Pregunta:
{pregunta}
"""
        respuesta = model.generate_content(prompt)
        texto_respuesta = respuesta.text

    except Exception as e:
        texto_respuesta = f"Error al generar respuesta: {e}"

    #return render_template("index.html", pregunta=pregunta, respuesta=texto_respuesta)
    return render_template("index.html", pregunta=pregunta, respuesta=texto_respuesta.encode("utf-8", "ignore").decode("utf-8"))


#if __name__ == "__main__":
#    app.run(debug=True)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
