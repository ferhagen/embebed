from flask import Flask, render_template, request, jsonify
import re
import requests
from html import unescape
from yt_dlp import YoutubeDL

app = Flask(__name__)

# -------------------------------------------------
#   Extraer ID del video
# -------------------------------------------------
def extract_video_id(url):
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    return match.group(1) if match else None


# -------------------------------------------------
#   Limpiar texto [Música], [Aplausos], etc
# -------------------------------------------------
def limpiar_basura(texto):
    limpio = re.sub(r"\[.*?\]", "", texto)
    limpio = re.sub(r"\s{2,}", " ", limpio)
    return limpio.strip()


# -------------------------------------------------
#   Capitalizar párrafo
# -------------------------------------------------
def capitalizar_parrafo(texto):
    texto = texto.strip()
    if not texto:
        return texto
    return texto[0].upper() + texto[1:]


# -------------------------------------------------
#   Sistema de párrafos inteligente
# -------------------------------------------------
def _parrafos_html(lineas):

    if not lineas:
        return "<p>❌ No se pudieron procesar los subtítulos.</p>"

    texto = " ".join(lineas)
    texto = re.sub(r"\s+", " ", texto).strip()

    tiene_puntuacion = bool(re.search(r"[\.?!]", texto))

    parrafos = []

    # -------------------------------------------------
    # A) SI HAY PUNTUACIÓN → AGRUPAR POR FRASES
    # -------------------------------------------------
    if tiene_puntuacion:
        frases = re.split(r'(?<=[\.\?\!])\s+', texto)
        frases = [f.strip() for f in frases if f.strip()]

        # Dividir frases demasiado largas
        frases_procesadas = []
        for f in frases:
            palabras = f.split()
            if len(palabras) > 35:
                for i in range(0, len(palabras), 25):
                    chunk = " ".join(palabras[i:i+25])
                    frases_procesadas.append(chunk)
            else:
                frases_procesadas.append(f)

        frases = frases_procesadas

        temp = []
        actual = 0

        for frase in frases:
            temp.append(frase)
            actual += len(frase.split())

            # Límite seguro
            if actual >= 60:
                bloque = " ".join(temp).strip()
                bloque = capitalizar_parrafo(bloque)
                parrafos.append(bloque)
                temp = []
                actual = 0

        if temp:
            bloque = " ".join(temp).strip()
            bloque = capitalizar_parrafo(bloque)
            parrafos.append(bloque)

    # -------------------------------------------------
    # B) SUBTÍTULOS AUTOMÁTICOS SIN PUNTUACIÓN
    # -------------------------------------------------
    else:
        temp = []
        acumulado = 0

        for i, linea in enumerate(lineas):
            linea = linea.strip()
            if not linea:
                continue

            palabras = linea.split()
            temp.append(linea)
            acumulado += len(palabras)

            siguiente = lineas[i+1] if i+1 < len(lineas) else ""
            siguiente = siguiente.strip()

            debe_cortar = False

            if acumulado >= 70:
                debe_cortar = True
            elif siguiente and (
                siguiente[0].isupper() or
                re.match(r'^(Pero|Así|Entonces|Sin embargo|Además|Por lo tanto|De modo que)\b',
                         siguiente, re.IGNORECASE)
            ):
                debe_cortar = True

            if debe_cortar:
                bloque = " ".join(temp)
                bloque = capitalizar_parrafo(bloque)
                parrafos.append(bloque)
                temp = []
                acumulado = 0

        if temp:
            bloque = " ".join(temp)
            bloque = capitalizar_parrafo(bloque)
            parrafos.append(bloque)

    # -------------------------------------------------
    # SIEMPRE insertar <p></p> entre párrafos
    # -------------------------------------------------
    html = ""
    for p in parrafos:
        html += f"<p>{p}</p>\n<p></p>\n"

    return html


# -------------------------------------------------
#   Obtener subtítulos VTT o JSON pb3
# -------------------------------------------------
def obtener_subtitulos(url):
    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "nocheckcertificate": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["es", "es-419", "es-ES", "es-LA", "en"],
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        subs = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}

        preferidos = ["es", "es-419", "es-ES", "es-LA", "en"]

        url_sub = None

        # Manuales
        for lang in preferidos:
            if lang in subs and subs[lang]:
                url_sub = subs[lang][0].get("url")
                break

        # Automáticos
        if not url_sub:
            for lang in preferidos:
                if lang in auto and auto[lang]:
                    url_sub = auto[lang][0].get("url")
                    break

        if not url_sub:
            return "<p>❌ Este video no tiene subtítulos disponibles.</p>"

        # Descargar archivo de subtítulos
        resp = requests.get(url_sub)
        text = resp.text.strip()

        lineas = []

        # ---------------------------------------------------------
        # CASO 1: VTT tradicional
        # ---------------------------------------------------------
        if text.startswith("WEBVTT"):
            raw = text.splitlines()
            for l in raw:
                l = l.strip()
                if not l:
                    continue
                if l.upper().startswith("WEBVTT"):
                    continue
                if re.match(r"^\d+$", l):
                    continue
                if "-->" in l:
                    continue
                texto = limpiar_basura(l)
                if texto:
                    lineas.append(texto)

        # ---------------------------------------------------------
        # CASO 2: JSON pb3 moderno
        # ---------------------------------------------------------
        elif text.startswith("{") and '"events"' in text:
            try:
                data = resp.json()
                for ev in data.get("events", []):
                    frase = ""
                    for s in ev.get("segs", []):
                        frase += s.get("utf8", "")
                    frase = limpiar_basura(frase).strip()
                    if frase:
                        lineas.append(frase)
            except Exception as e:
                print("Error parseando subtítulos JSON:", e)
                return "<p>❌ No se pudieron procesar subtítulos automáticos.</p>"

        # ---------------------------------------------------------
        # CASO 3: Otro formato desconocido
        # ---------------------------------------------------------
        else:
            return "<p>❌ Formato de subtítulos no reconocido.</p>"

        return _parrafos_html(lineas)

    except Exception as e:
        print("Error al obtener subtítulos:", e)
        return "<p>❌ Error al procesar subtítulos.</p>"


# -------------------------------------------------
#   Rutas Flask
# -------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/procesar', methods=['POST'])
def procesar():
    data = request.get_json()
    url = data.get("url")
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({"error": "URL inválida."}), 400

    # -------------------------------------------------
    # OBTENER METADATOS
    # -------------------------------------------------
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'nocheckcertificate': True
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        canal = info.get("uploader", "Canal no disponible").strip()
        titulo = info.get("title", "Título no disponible").strip()
        fecha_raw = info.get("upload_date")

        if fecha_raw and len(fecha_raw) == 8:
            year = fecha_raw[0:4]
            month = int(fecha_raw[4:6])
            day = int(fecha_raw[6:8])

            meses = [
                "enero","febrero","marzo","abril","mayo","junio",
                "julio","agosto","septiembre","octubre","noviembre","diciembre"
            ]
            fecha_formateada = f"{year}, {day} de {meses[month-1]}"
        else:
            fecha_formateada = "s.f."

    except Exception as e:
        print("Error obteniendo metadatos con yt-dlp:", e)
        canal = "Canal no disponible"
        titulo = "Título no disponible"
        fecha_formateada = "s.f."

    # -------------------------------------------------
    # Obtener subtítulos procesados
    # -------------------------------------------------
    parrafos = obtener_subtitulos(url)

    # -------------------------------------------------
    # Referencia APA
    # -------------------------------------------------
    referencia_html = f"""
<br>
<!--Referencia-->
<div class="linkd40-video bg-blue-l2 d40-border-blue">
    <div class="linkd40-video-s1">
        <span class="linkd40-textbox-badge bg-blue">
            <i class="fa fa-video-camera" aria-hidden="true"></i>
        </span>
    </div>
<div class="linkd40-video-s2">
    <p>Referencia:</p>
    <p>{canal}. ({fecha_formateada}). <i>{titulo}</i> [Video]. YouTube.</p>
</div>
</div>
"""

    # -------------------------------------------------
    # HTML final
    # -------------------------------------------------
    html_result = f"""
<iframe src="https://www.youtube.com/embed/{video_id}"
        title="{titulo}"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        frameborder="0" class="video-d401" allowfullscreen>
</iframe>

<!--Transcripción-->
<div class="accordion accordion-d401" id="accordionTranscripcion">
    <div class="accordion-item">
        <h3 class="accordion-header">
            <button class="accordion-button collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseOne"
                    aria-expanded="false"
                    aria-controls="collapseOne">
                Transcripción del video
            </button>
        </h3>
        <div id="collapseOne"
             class="accordion-collapse collapse"
             data-bs-parent="#accordionTranscripcion">
            <div class="accordion-body">
                <div class="book-d401">
                    {parrafos}
                </div>
            </div>
        </div>
    </div>
</div>

{referencia_html}
"""

    return jsonify({"html": html_result})


if __name__ == '__main__':
    app.run(debug=True)
