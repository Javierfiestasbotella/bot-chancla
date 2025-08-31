import os
import re
from datetime import datetime
from difflib import get_close_matches

from flask import Flask, render_template, request
from markupsafe import Markup

import google.generativeai as genai
from dotenv import load_dotenv
from lector_pdf import leer_todos_los_pdfs_en_fragmentos

# TF-IDF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

# Markdown → HTML
import markdown

# Word (pendientes)
from docx import Document

# Excel
from openpyxl import load_workbook

# =========================
# Utilidades: sanitizar texto
# =========================
def safe_text(s: str) -> str:
    if s is None:
        return ""
    return s.encode("utf-8", "ignore").decode("utf-8", "ignore")

# Troceo con solape
def chunk_text(text, size=900, overlap=200):
    text = safe_text(text)
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks

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
# Carga de documentos (PDF + XLSX)
# =========================
def leer_todos_los_xlsx_en_fragmentos(carpeta):
    frags = []
    for root, _, files in os.walk(carpeta):
        for fn in files:
            if fn.lower().endswith(".xlsx"):
                path = os.path.join(root, fn)
                try:
                    wb = load_workbook(path, data_only=True)
                    for sheet_name in wb.sheetnames:
                        ws = wb[sheet_name]
                        # Convertimos hoja a texto simple
                        lines = []
                        for row in ws.iter_rows(values_only=True):
                            vals = [str(v) for v in row if v is not None]
                            if vals:
                                lines.append(" | ".join(vals))
                        text = f"[DOC: {fn} - Hoja: {sheet_name}]\n" + "\n".join(lines)
                        for ch in chunk_text(text, size=1000, overlap=250):
                            frags.append(safe_text(ch))
                except Exception as e:
                    # Si una hoja falla, seguimos con el resto
                    frags.append(safe_text(f"[DOC ERROR {fn}] {e}"))
    return frags

# Leemos PDFs (función existente) + XLSX
_fragmentos_pdf = leer_todos_los_pdfs_en_fragmentos("data/pdf_data")
_fragmentos_xlsx = leer_todos_los_xlsx_en_fragmentos("data/pdf_data")
fragmentos = [safe_text(f) for f in (_fragmentos_pdf + _fragmentos_xlsx)]
if not fragmentos:
    fragmentos = ["[No hay fragmentos cargados de los documentos.]"]

app = Flask(__name__)

# =========================
# Persistencia pendientes
# =========================
LEES_DIR = "lees_resp"
LEES_DOCX = os.path.join(LEES_DIR, "respuestas.docx")

def asegurar_docx():
    os.makedirs(LEES_DIR, exist_ok=True)
    if not os.path.exists(LEES_DOCX):
        doc = Document()
        doc.add_heading("Preguntas sin respuesta / con error", level=1)
        doc.add_paragraph(f"Documento creado el {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_paragraph("")
        doc.save(LEES_DOCX)

def anotar_pendiente(pregunta: str, motivo: str, contexto_preview: str = ""):
    asegurar_docx()
    doc = Document(LEES_DOCX)
    doc.add_heading(datetime.now().strftime('%Y-%m-%d %H:%M'), level=2)
    doc.add_paragraph(f"Pregunta: {safe_text(pregunta)}")
    doc.add_paragraph(f"Motivo: {safe_text(motivo)}")
    if contexto_preview:
        doc.add_paragraph("Contexto usado (preview):")
        doc.add_paragraph(safe_text(contexto_preview[:1200]))
    doc.add_paragraph("")
    doc.save(LEES_DOCX)

# =========================
# Catálogo de vinos (parse desde fragmentos)
# =========================
def construir_catalogo_vinos(fragmentos):
    vinos = []
    for frag in fragmentos:
        lines = [l.strip() for l in frag.splitlines()]
        for i, line in enumerate(lines):
            if "📍" in line and ("D.O." in line or "D.O" in line or "Rioja" in line or "Ribeiro" in line or "Tierras" in line):
                name = ""
                j = i - 1
                while j >= 0 and not name:
                    cand = lines[j].strip()
                    if cand and not cand.startswith(("📍", "🍇", "🛢")):
                        name = cand
                    j -= 1
                do = line.replace("📍", "").strip()
                uvas, crianza, nota = "", "", ""
                k = i + 1
                while k < len(lines):
                    l2 = lines[k]
                    if "📍" in l2:
                        break
                    if l2.startswith("🍇"):
                        uvas = l2.replace("🍇", "").strip()
                    elif l2.startswith("🛢"):
                        crianza = l2.replace("🛢", "").strip()
                    else:
                        if l2:
                            nota = (nota + " " + l2).strip() if nota else l2
                    k += 1
                def clean(x): return safe_text(re.sub(r"\s{2,}", " ", x))
                name, do, uvas, crianza, nota = map(clean, [name, do, uvas, crianza, nota])
                if name and len(name) <= 80:
                    vinos.append({"nombre": name, "do": do, "uvas": uvas, "crianza": crianza, "nota": nota})
    vistos, result = set(), []
    for v in vinos:
        n = v["nombre"].strip().lower()
        if n not in vistos:
            vistos.add(n)
            result.append(v)
    return result

CATALOGO_VINOS = construir_catalogo_vinos(fragmentos)

def buscar_vino_por_nombre(nombre, catalogo):
    nombres = [v["nombre"] for v in catalogo]
    candidatos = get_close_matches(nombre, nombres, n=1, cutoff=0.6)
    if candidatos:
        nombre_ok = candidatos[0]
        for v in catalogo:
            if v["nombre"] == nombre_ok:
                return v
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
    cab = "| Vino | D.O. | Uvas | Crianza |\n|---|---|---|---|"
    filas = [f"| {v['nombre']} | {v['do']} | {v['uvas']} | {v['crianza']} |" for v in vinos]
    return "\n".join([cab] + filas)

def es_pregunta_de_vinos(p):
    p = p.lower()
    claves = ["vino", "vinos", "carta de vinos", "tinto", "blanco", "rosado", "espumoso", "cava"]
    return any(c in p for c in claves)

# =========================
# Expansión de consulta (sinónimos del dominio)
# =========================
SINONIMOS = {
    "cierre": ["protocolo de cierre", "procedimiento de cierre", "recogida", "limpieza final", "cuadre de caja", "cierre de barra", "cierre de cocina"],
    "cocina": ["cocinero", "cocineros", "chef", "pase", "partida", "mise en place"],
    "hamaca": ["hamacas", "balinesas", "sombrillas", "tumbonas", "reserva de hamacas", "camas balinesas"],
    "alergenos": ["alérgenos", "intolerancias"],
    "horario": ["turnos", "apertura", "cierre"],
    "pinganillo": ["walkie", "radio", "comunicación"],
    "vinos": ["vino", "carta de vinos", "tinto", "blanco", "rosado", "rioja", "ribeiro", "ronda", "malagueño"]
}

def expand_query(pregunta: str) -> str:
    p = pregunta.lower()
    extra = []
    for clave, exps in SINONIMOS.items():
        if clave in p:
            extra += exps
    return (pregunta + " " + " ".join(extra)).strip() if extra else pregunta

# =========================
# Búsqueda general (TF-IDF combinado)
# =========================
def encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=8):
    q = expand_query(pregunta)
    # 1) Palabras (1-2 gramos)
    v_words = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    tfidf_words = v_words.fit_transform(fragmentos + [q])
    sims_words = linear_kernel(tfidf_words[-1], tfidf_words[:-1]).flatten()
    # 2) Caracteres en ventana (3-5) para robustez ante variaciones
    v_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    tfidf_char = v_char.fit_transform(fragmentos + [q])
    sims_char = linear_kernel(tfidf_char[-1], tfidf_char[:-1]).flatten()
    # 3) Combinamos (media ponderada)
    sims = 0.6 * sims_words + 0.4 * sims_char
    top_idx = sims.argsort()[::-1][:max_resultados]
    if sims[top_idx[0]] < 0.03:   # umbral bajo para no quedarnos sin nada
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
    pregunta = safe_text(request.form.get("pregunta", "").strip())

    try:
        # --- Rama especial: Vinos ---
        if es_pregunta_de_vinos(pregunta) and CATALOGO_VINOS:
            tokens = [t for t in re.findall(r"[A-Za-zÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜ-]*", pregunta)]
            candidato_nombre = " ".join([t for t in tokens if len(t) > 2])
            vino_encontrado = buscar_vino_por_nombre(candidato_nombre, CATALOGO_VINOS) if candidato_nombre else None
            if vino_encontrado:
                md = f"### Ficha del vino\n\n{markdown_vino(vino_encontrado)}"
            else:
                md = "### Carta de vinos (resumen)\n\n" + markdown_tabla_vinos(CATALOGO_VINOS)
            html = markdown.markdown(safe_text(md), extensions=["extra"])
            return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

        # --- Rama general (TF-IDF + Gemini) ---
        top_fragmentos = encontrar_fragmentos_relacionados(pregunta, fragmentos, max_resultados=10)
        contexto = "\n\n---\n\n".join(top_fragmentos)
        contexto = safe_text(contexto)

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
        texto_respuesta = safe_text((respuesta.text or "").strip())

        # ¿Cubierta o pendiente?
        es_pendiente = False
        low = texto_respuesta.lower()
        if not texto_respuesta:
            es_pendiente = True; motivo = "Respuesta vacía"
        elif "no aparece" in low or "no está en el contexto" in low or "no se encuentra en el contexto" in low:
            es_pendiente = True; motivo = "No cubierto por el contexto"
        else:
            motivo = ""

        if es_pendiente:
            anotar_pendiente(pregunta, motivo, contexto_preview=contexto)

        html = markdown.markdown(texto_respuesta, extensions=["extra"])
        return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

    except Exception as e:
        anotar_pendiente(pregunta, f"Error: {safe_text(str(e))}")
        html = markdown.markdown(f"Error al generar respuesta: {safe_text(str(e))}")
        return render_template("index.html", pregunta=pregunta, respuesta=Markup(html))

# =========================
# Arranque (local/Render)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
