import os
import re
from datetime import datetime
from difflib import get_close_matches

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

# =========================
# Configuración de claves
# =========================
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("❌ No se encontró la clave GOOGLE_API_KEY en el archivo .env")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-pro-latest")

# =========================
# Carga de documentos
# =========================
fragmentos = leer_todos_los_pdfs_en_fragmentos("data/pdf_data")
if not fragmentos:
    fragmentos = ["[No hay fragmentos cargados de los PDF.]"]

app = Flask(__name__)

# =========================
# Utilidades de persistencia
# =========================
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
        doc.add_paragraph(contexto_preview[:1200])  # evitar doc gigantes
    doc.add_paragraph("")  # separador
    doc.save(LEES_DOCX)

# =========================
# Catálogo de vinos (parse PDFs)
# =========================
def construir_catalogo_vinos(fragmentos):
    """
    Extrae vinos buscando patrones típicos:
    Línea con el nombre, luego líneas con:
      📍 D.O. ....
      🍇 uvas...
      🛢 crianza...
    y una o varias líneas de nota/maridaje.
    Es tolerante a ausencias (si falta algo lo deja vacío).
    """
    vinos = []
    for frag in fragmentos:
        # Normalizamos saltos
        lines = [l.strip() for l in frag.splitlines()]
        for i, line in enumerate(lines):
            if "📍" in line and ("D.O." in line or "D.O" in line or "Tierras" in line or "Ribeiro" in line):
                # Nombre: línea no vacía anterior
                name = ""
                j = i - 1
                while j >= 0 and not name:
                    cand = lines[j].strip()
                    if cand and not cand.startswith(("📍", "🍇", "🛢")):
                        name = cand
                    j -= 1

                do = line.replace("📍", "").strip()
                uvas = ""
                crianza = ""
                nota = ""

                # Busca hacia adelante detalles 🍇, 🛢 y nota
                k = i + 1
                while k < len(lines):
                    l2 = lines[k]
                    if "📍" in l2:  # siguiente vino
                        break
                    if l2.startswith("🍇"):
                        uvas = l2.replace("🍇", "").strip()
                    elif l2.startswith("🛢"):
                        crianza = l2.replace("🛢", "").strip()
                    else:
                        # acumula texto suelto como nota (maridaje / descripción)
                        if l2:
                            if nota:
                                nota += " " + l2
                            else:
                                nota = l2
                    k += 1

                # Limpieza mínima
                name = re.sub(r"\s{2,}", " ", name)
                do = re.sub(r"\s{2,}", " ", do)
                uvas = re.sub(r"\s{2,}", " ", uvas)
                crianza = re.sub(r"\s{2,}", " ", crianza)
                nota = re.sub(r"\s{2,}", " ", nota)

                # Filtros básicos para evitar entradas falsas
                if name and len(name) <= 80:
                    vinos.append({
                        "nombre": name,
                        "do": do,
                        "uvas": uvas,
                        "crianza": crianza,
                        "nota": nota
                    })
    # Eliminar duplicados por nombre (conservando el primero)
    vistos = set()
    result = []
    for v in vinos:
        n = v["nombre"].strip().lower()
        if n not in vistos:
            vistos.add(n)
            result.append(v)
    return result

CATALOGO_VINOS = construir_catalogo_vinos(fragmentos)

def buscar_vino_por_nombre(nombre, catalogo):
    """Devuelve el mejor match (difuso) por nombre."""
    nombres = [v["nombre"] for v in catalogo]
    candidatos = get_close_matches(nombre, nombres, n=1, cutoff=0.6)
    if candidatos:
        nombre_ok = candidatos[0]
        for v in catalogo:
            if v["nombre"] == nombre_ok:
                return v
    # Intento por inclusión simple
    for v in catalogo:
        if nombre.lower() in v["nombre"].lower():
            return v
    return None

def markdown_vino(v):
    filas = [
        f"**{v['nombre']}**",
        f"- **D.O.**: {v['do']}" if v["do"] else "",
        f"- **Uvas**: {v['uvas']}" if v["uvas"] else "",
        f"- **Crianza**: {v['crianza']}" if v["crianza"] else "",
        f"- **Nota**: {v['nota']}" if v["nota"] else "",
    ]
    return "\n".join([x for x in filas if x])

def markdown_tabla_vinos(vinos):
    # Tabla compacta para vista rápida
    cab = "| Vino | D.O. | Uvas | Crianza |\n|---|---|---|---|"
    filas = []
    for v in vinos:
        filas.append(f"| {v['nombre']} | {v['do']} | {v['uvas']} | {v['crianza']} |")
    return "\n".join([cab] + filas)

def es_pregunta_de_vinos(p):
    p = p.lower()
    claves = ["vino", "vinos", "carta de vinos", "tinto", "blanco", "rosado", "espumoso", "cava"]
    return any(c in p for c in claves)

# =========================
# Búsqueda general (TF-IDF)
# =========================
def encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8):
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words=None)
    docs = fragmentos + [pregunta]
    tfidf = vectorizer.fit_transform(docs)
    sims = linear_kernel(tfidf[-1], tfidf[:-1]).flatten()
    top_idx = sims.argsort()[::-1][:max_resultados]
    if sims[top_idx[0]] < 0.05:
        return fragmentos[:3]
    return [fragmentos[i] for i in top_idx]

# =========================
# Rutas
# =========================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/preguntar", methods=["POST"])
def preguntar():
    pregunta = request.form.get("pregunta", "").strip()

    try:
        # --- Rama especial: Vinos ---
        if es_pregunta_de_vinos(pregunta) and CATALOGO_VINOS:
            # ¿Pregunta por uno concreto?
            # Busca un nombre propio en la frase (simple: toma tokens con mayúscula inicial)
            tokens = [t for t in re.findall(r"[A-Za-zÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜ-]*", pregunta)]
            candidato_nombre = " ".join([t for t in tokens if len(t) > 2])
            vino_encontrado = None
            if candidato_nombre:
                vino_encontrado = buscar_vino_por_nombre(candidato_nombre, CATALOGO_VINOS)

            if vino_encontrado:
                md = f"### Ficha del vino\n\n{markdown_vino(vino_encontrado)}"
            else:
                # Lista general
                md = "### Carta de vinos (resumen)\n\n" + markdown_tabla_vinos(CATALOGO_VINOS)

            html = markdown.markdown(md, extensions=["extra"])
            return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

        # --- Rama general (TF-IDF + Gemini) ---
        top_fragmentos = encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8)
        contexto = "\n\n---\n\n".join(top_fragmentos)

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

        # Detectar si la respuesta no cubre
        es_pendiente = False
        lower = texto_respuesta.lower()
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

        html = markdown.markdown(texto_respuesta, extensions=["extra"])
        return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

    except Exception as e:
        # Registrar también el error en el Word
        anotar_pendiente(pregunta, f"Error: {e}")
        texto_respuesta = f"Error al generar respuesta: {e}"
        html = markdown.markdown(texto_respuesta)
        return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

# =========================
# Arranque (local/Render)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
