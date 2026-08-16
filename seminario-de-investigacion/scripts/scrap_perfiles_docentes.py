"""
Scraper del cuerpo docente - Facultad de Ingeniería (Javeriana)
Objetivo del script: Estructurar un archivo plano con información de los perfiles de los
docentes para poder explorar de manera sencilla o con ayuda de IA cuál de ellos podría ser
un director de proyecto de grado adecuado según el contenido de mi idea.

Cómo funciona
-------------
1. Descarga la página https://ingenieria.javeriana.edu.co/cuerpo-docente
   y extrae, para cada docente: nombre, cargo y el link "Ver más" (que casi
   siempre apunta a perfilesycapacidades.javeriana.edu.co/es/persons/<slug>).
2. Filtra solo los bloques de "DEPARTAMENTO DE INGENIERÍA INDUSTRIAL" y
   "DEPARTAMENTO DE INGENIERÍA DE SISTEMAS".
3. Entra a cada perfil individual y extrae:
   - Nombre completo
   - Cargo / cargo académico
   - Departamento
   - Perfil (texto narrativo, cuando existe)
   - Formación académica (Doctorado / Maestría / Especialización / Pregrado)
4. Guarda todo en un CSV.

Requisitos
----------
pip install requests beautifulsoup4 lxml

Uso
----
python scraper_docentes_javeriana.py
Genera: scrap_perfiles_docentes.csv
"""


import csv
import re
import time
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

LISTADO_URL = "https://ingenieria.javeriana.edu.co/cuerpo-docente"

DEPARTAMENTOS_OBJETIVO = {
    "DEPARTAMENTO DE INGENIERÍA INDUSTRIAL": "Ingeniería Industrial",
    "DEPARTAMENTO DE INGENIERÍA DE SISTEMAS": "Ingeniería de Sistemas",
    "DEPARTAMENTO DE ELECTRÓNICA": "Ingeniería Electrónica"
}

HEADING_RE = re.compile(r"^h[1-6]$")
DEPT_RE = re.compile(r"^DEPARTAMENTO DE .+", re.IGNORECASE)


def get_soup(url, retries=3, wait=1.5):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except requests.RequestException as e:
            print(f"  [retry {attempt + 1}] {url} -> {e}")
            time.sleep(wait)
    return None


def extraer_listado_docentes():
    """
    Recorre la página de 'Cuerpo docente' en orden de documento (usando
    .descendants) y arma una tarjeta por cada foto de profesor encontrada
    (las fotos siempre traen el nombre completo en el atributo title/alt).

    Devuelve lista de dicts: {nombre, cargo, departamento, url_perfil}
    filtrada solo a Industrial y Sistemas.
    """
    soup = get_soup(LISTADO_URL)
    if soup is None:
        raise RuntimeError("No se pudo descargar la página de listado")

    body = soup.find("body") or soup

    docentes = []
    dept_actual = None
    pending_name = None
    pending_cargo_parts = []
    collecting = False

    for el in body.descendants:
        # --- Detectar encabezados de departamento ---
        if isinstance(el, Tag) and el.name in ("h1", "h2", "h3", "h4", "p", "strong", "div"):
            txt = el.get_text(strip=True)
            if txt and DEPT_RE.match(txt):
                dept_actual = txt

        # --- Detectar el inicio de una tarjeta de profesor (foto con title) ---
        if isinstance(el, Tag) and el.name == "img":
            title = (el.get("title") or el.get("alt") or "").strip()
            if title and len(title) > 4:
                pending_name = title
                pending_cargo_parts = []
                collecting = True
                continue

        if not collecting:
            continue

        # --- Mientras recolectamos, buscamos el link "Ver más >>" que cierra la tarjeta ---
        if isinstance(el, Tag) and el.name == "a":
            link_text = el.get_text(strip=True)
            href = el.get("href", "")
            if link_text.lower().startswith("ver más") or link_text.lower().startswith("ver mas"):
                cargo = " ".join(pending_cargo_parts).strip()
                dept_raw = (dept_actual or "").upper()
                for clave, bonito in DEPARTAMENTOS_OBJETIVO.items():
                    if clave in dept_raw:
                        docentes.append({
                            "nombre": pending_name,
                            "cargo": cargo,
                            "departamento": bonito,
                            "url_perfil": href,
                        })
                        break
                collecting = False
                pending_name = None
                pending_cargo_parts = []
            elif link_text and link_text != pending_name:
                # texto de un link que no es ni el nombre repetido ni "Ver más"
                # (raro, pero por si acaso lo tratamos como posible cargo)
                pass
            continue

        # --- Texto plano (NavigableString) que no es parte de un <a>: candidato a cargo ---
        if isinstance(el, NavigableString):
            txt = str(el).strip()
            if txt and txt != pending_name:
                pending_cargo_parts.append(txt)

    return docentes


def _texto_seccion(texto_completo, titulo, siguientes):
    """
    Busca 'titulo' como línea aislada dentro de texto_completo y devuelve
    todo el contenido hasta la primera aparición de alguno de los títulos
    en 'siguientes'.
    """
    patron_siguientes = "|".join(re.escape(s) for s in siguientes)
    patron = re.compile(
        r"(?:^|\n)\s*" + re.escape(titulo) + r"\s*\n+(.+?)\n+\s*(?:" + patron_siguientes + r")",
        re.DOTALL,
    )
    m = patron.search(texto_completo)
    if m:
        return re.sub(r"\n{2,}", "\n", m.group(1)).strip()
    return ""


def extraer_ficha_profesor(url):
    resultado = {"perfil": "", "formacion_academica": ""}
    if not url or url.strip() in ("#", ""):
        return resultado

    soup = get_soup(url)
    if soup is None:
        return resultado

    texto = soup.get_text("\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    resultado["perfil"] = _texto_seccion(
        texto, "Perfil",
        ["Formación académica", "Formacion academica"],
    )

    formacion_raw = _texto_seccion(
        texto, "Formación académica",
        ["Categoría en el Sistema Nacional de Ciencia",
         "Programas académicos asociados",
         "Líneas de Investigación",
         "Experiencia relacionada con los ODS",
         "CVLAC"],
    )
    if formacion_raw:
        lineas = [l.strip() for l in formacion_raw.split("\n") if l.strip()]
        resultado["formacion_academica"] = " | ".join(lineas)

    return resultado


def main():
    print("Descargando listado de docentes...")
    docentes = extraer_listado_docentes()
    print(f"Encontrados {len(docentes)} docentes en Industrial + Sistemas")

    if not docentes:
        print("\n⚠️  No se encontró ningún docente. Esto puede pasar si:")
        print("   - Liferay renderiza el listado vía JavaScript/AJAX (contenido dinámico)")
        print("   - Cambiaron las clases/estructura del HTML")
        print("Sugerencia: guarda el HTML crudo con requests y revísalo a mano:")
        print("   r = requests.get(LISTADO_URL, headers=HEADERS)")
        print("   open('debug.html','w',encoding='utf-8').write(r.text)")
        return

    filas = []
    for i, d in enumerate(docentes, 1):
        print(f"[{i}/{len(docentes)}] {d['nombre']} -> {d['cargo']}")
        ficha = extraer_ficha_profesor(d["url_perfil"])
        filas.append({
            "Nombre": d["nombre"],
            "Cargo": d["cargo"],
            "Departamento": d["departamento"],
            "Facultad": "Facultad de Ingeniería",
            "Perfil": ficha["perfil"],
            "Formacion_Academica": ficha["formacion_academica"],
            "URL_Perfil": d["url_perfil"],
        })
        time.sleep(0.8)

    with open("scrap_perfiles_docentes.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Nombre", "Cargo", "Departamento", "Facultad",
                        "Perfil", "Formacion_Academica", "URL_Perfil"],
        )
        writer.writeheader()
        writer.writerows(filas)

    print("\nListo -> scrap_perfiles_docentes.csv")


if __name__ == "__main__":
    main()
