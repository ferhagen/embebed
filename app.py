from flask import Flask, render_template, request, jsonify
import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

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
    # A) SI HAY PUNTUACIÓN
    # -------------------------------------------------
    if tiene_puntuacion:
        frases = re.split(r'(?<=[\.\?\!])\s+', texto)
        frases = [f.strip() for f in frases if f.strip()]

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
    # B) SUBTÍTULOS SIN PUNTUACIÓN
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
    # Generar HTML final con <p></p> extra
    # -------------------------------------------------
    html = ""
    for p in parrafos:
        html += f"<p>{p}</p>\n<p></p>\n"

    return html


# -------------------------------------------------
#   Obtener subtítulos con youtube-transcript-api
# -------------------------------------------------
def obtener_subtitulos(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "es-419", "es-ES", "es-LA", "en"])
        lineas = [limpiar_basura(item["text"]) for item in transcript_list if item["text"].strip()]

        return _parrafos_html(lineas)

    except TranscriptsDisabled:
        return "<p>❌ Este video no tiene subtítulos disponibles.</p>"
    except NoTranscriptFound:
        return "<p>❌ No se encontraron subtítulos para este video.</p>"
    except Exception as e:
        print("Error al obtener subtítulos:", e)
        return "<p>❌ Error al procesar subtítulos.</p>"


# -------------------------------------------------
#   Obtener metadatos vía oEmbed (seguro y sin bloqueo)
# -------------------------------------------------
def obtener_metadata(video_id):
    url_oembed = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"

    try:
        r = requests.get(url_oembed, timeout=5)
        data = r.json()

        titulo = data.get("title", "Título no disponible")
        canal = data.get("author_name", "Canal no disponible")

        return titulo, canal

    except Exception as e:
        print("Error metadatos oEmbed:", e)
        return "Título no disponible", "Canal no disponible"


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

    # Metadatos estables
    titulo, canal = obtener_metadata(video_id)
    fecha_formateada = "s.f."  # oEmbed no trae fecha (puedo agregarlo si quieres)

    # Subtítulos procesados
    parrafos = obtener_subtitulos(video_id)

    # Referencia APA
    referencia_html = f"""
<br>
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

    # HTML final
    html_result = f"""
<iframe src="https://www.youtube.com/embed/{video_id}"
        title="{titulo}"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        frameborder="0" class="video-d401" allowfullscreen>
</iframe>

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
