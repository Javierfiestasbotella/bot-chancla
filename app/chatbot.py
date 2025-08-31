import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generar_respuesta(pregunta):
    try:
        model = genai.GenerativeModel(model_name="models/gemini-pro")
        chat = model.start_chat(history=[])
        response = chat.send_message(pregunta)
        return response.text
    except Exception as e:
        return f"Error al generar respuesta: {e}"
