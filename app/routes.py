from flask import request, render_template
from utils import guardar_pregunta_fallida
from lector_pdf import leer_todos_los_pdfs_en_fragmentos
import google.generativeai as genai
import os
from app import bp

# CONFIGURACIÓN DEL MODELO
genai.configure(api_key="AIzaSyC6-tTHKa2WlYG9yDYbNgQ-Y8h5cuQzYMQ")  # <-- Sustituye por tu clave real
model = genai.GenerativeModel("gemini-pro")

# Cargar los fragmentos de todos los PDFs desde la carpeta
fragmentos = leer_todos_los_pdfs_en_fragmentos("data/pdf_data")

@bp.route("/preguntar", methods=["POST"])
def preguntar():
    pregunta = request.form["pregunta"]
    try:
        prompt = f"Teniendo en cuenta esta información sobre el restaurante La Chancla:\n\n{contenido_pdf}\n\nPregunta: {pregunta}"

        respuesta = model.generate_content(prompt)

        # Elimina cualquier carácter raro que cause errores de codificación
        import re
        texto_respuesta = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', respuesta.text)

        # Si no sabe o no responde, lo guardamos
        if "no lo sé" in texto_respuesta.lower() or "no tengo información" in texto_respuesta.lower():
            guardar_pregunta_fallida(pregunta)

    except Exception as e:
        texto_respuesta = f"Error al generar respuesta: {e}"
        guardar_pregunta_fallida(pregunta)

    return render_template("index.html", pregunta=pregunta, respuesta=texto_respuesta)
