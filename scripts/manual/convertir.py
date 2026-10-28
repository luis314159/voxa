"""docs/manual.md → src/voxa/manual/index.html, la página del manual que sirve VOXA (``/manual``).

    python scripts/manual/convertir.py

Entiende solo lo que usa el manual: títulos, párrafos, listas (con un nivel dentro), tablas, citas,
bloques de código e imágenes. Lo que se le dice a VOXA («pon música») sale como globo de diálogo.
tests/test_manual.py revisa que la página esté al día con el markdown.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GITHUB = "https://github.com/luis314159/voxa/blob/master/"
MARKDOWN = REPO / "docs" / "manual.md"
TEMPLATE = Path(__file__).with_name("plantilla.html")
PAGE = REPO / "src" / "voxa" / "manual" / "index.html"

# Dicho antes de una cita, la vuelve algo que se le dice a VOXA: «di "pon música"».
_SAID_BEFORE = re.compile(r"(^|\W)(di|dile|dices|decir|pregúntale|con)\s*(<strong>)?$")
_BLOCK_START = re.compile(r"(#|>|\||```|\s*(-|\d+\.)\s|---|\s*!\[)")
_ITEM = re.compile(r"(\s*)(-|\d+\.)\s(.*)")
_IMAGE = re.compile(r"\s*!\[([^\]]*)\]\(([^)]+)\)")
_SEARCH = (
    '<label class="buscar" for="buscar"><span>Busca qué decirle</span>'
    '<input type="search" id="buscar" placeholder="Por ejemplo: arroz, música, lista…" autocomplete="off"></label>'
    '<p class="sin" id="sin-resultados" hidden>Nada con esa palabra. Prueba con otra, o pregúntale a VOXA '
    '«¿qué puedes hacer?».</p>'
)


def image_url(path: str) -> str:
    """En el markdown las imágenes apuntan al paquete (para GitHub); VOXA las sirve en /manual/img/."""
    return "/manual/img/" + path.rsplit("/", 1)[-1] if "manual/img/" in path else path


class _Page:
    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.i = 0
        self.body: list[str] = []
        self.spoken = False  # en «Qué le puedes pedir», todo lo citado es para decírselo a VOXA

    # --- en línea -------------------------------------------------------------------
    def inline(self, text: str) -> str:
        out = []
        for part in re.split(r"(`[^`]+`)", text):
            if len(part) > 1 and part.startswith("`") and part.endswith("`"):
                out.append(f"<code>{html.escape(part[1:-1])}</code>")
                continue
            part = html.escape(part, quote=False)
            part = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', part)
            part = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, part)
            part = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", part)
            part = re.sub(r"«([^»]+)»", lambda m, p=part: self._quote(m, p), part)
            out.append(part)
        return re.sub(r"\*\*(<code>.*?</code>)\*\*", r"<strong>\1</strong>", "".join(out))

    def _quote(self, m: re.Match, text: str) -> str:
        said = m.group(1)
        before = text[max(0, m.start() - 24):m.start()].lower()
        if self.spoken or said.startswith(("Hey Voxa", "Oye Voxa")) or _SAID_BEFORE.search(before):
            return f'<q class="di">{said}</q>'
        return m.group(0)  # un botón o un texto de la pantalla: con sus comillas, sin globo

    # --- bloques --------------------------------------------------------------------
    def render(self) -> str:
        open_section = False
        lines = self.lines
        while self.i < len(lines):
            line = lines[self.i]
            if line.startswith("```"):
                self._code()
            elif line.startswith("# ") or line.strip() == "---" or not line.strip():
                self.i += 1  # el título va en la cabecera de la página; las rayas, entre secciones
            elif line.startswith("## "):
                if open_section:
                    self.body.append("</section>")
                self._section(line[3:])
                open_section = True
            elif line.startswith("### "):
                self.body.append(f"<h3>{self.inline(line[4:])}</h3>")
                self.i += 1
            elif line.startswith(">"):
                self._note()
            elif line.startswith("|"):
                self._table()
            elif _ITEM.match(line):
                self.body.append(self._list(len(line) - len(line.lstrip())))
            elif image := _IMAGE.match(line):
                self._figure(image.group(1), image.group(2))
            else:
                self._paragraph()
        if open_section:
            self.body.append("</section>")
        return "\n".join(self.body)

    def _code(self) -> None:
        block = []
        self.i += 1
        while not self.lines[self.i].startswith("```"):
            block.append(self.lines[self.i])
            self.i += 1
        self.i += 1
        self.body.append('<div class="code"><pre><code>' + html.escape("\n".join(block)) + "</code></pre></div>")

    def _section(self, title: str) -> None:
        n = re.match(r"(\d+)\.\s*(.*)", title)
        self.spoken = bool(n and n.group(1) == "5")
        self.body.append(f'<section id="s{n.group(1) if n else 0}">')
        if n:
            self.body.append(f'<h2><span class="num">{n.group(1)}</span>{self.inline(n.group(2))}</h2>')
        else:
            self.body.append(f"<h2>{self.inline(title)}</h2>")
        if self.spoken:
            self.body.append(_SEARCH)
        self.i += 1

    def _note(self) -> None:
        quote = []
        while self.i < len(self.lines) and self.lines[self.i].startswith(">"):
            quote.append(self.lines[self.i].lstrip("> ").rstrip())
            self.i += 1
        self.body.append(f'<aside class="nota"><p>{self.inline(" ".join(quote))}</p></aside>')

    def _table(self) -> None:
        rows = []
        while self.i < len(self.lines) and self.lines[self.i].startswith("|"):
            rows.append([c.strip() for c in self.lines[self.i].strip().strip("|").split("|")])
            self.i += 1
        head, rest = rows[0], rows[2:]  # rows[1] es la raya |---|
        out = ['<div class="tabla"><table><thead><tr>' + "".join(f"<th>{self.inline(c)}</th>" for c in head)
               + "</tr></thead><tbody>"]
        out += ["<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in row) + "</tr>" for row in rest]
        self.body.append("".join(out) + "</tbody></table></div>")

    def _list(self, indent: int) -> str:
        first = re.match(r"\s*(\d+)\.", self.lines[self.i])
        items: list[list[str]] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            m = _ITEM.match(line)
            if not m:
                if items and line.strip() and line.startswith(" " * (indent + 2)) and not _IMAGE.match(line):
                    items[-1][0] += " " + line.strip()  # el renglón sigue al de arriba
                    self.i += 1
                    continue
                break
            level = len(m.group(1))
            if level < indent:
                break
            if level > indent:
                items[-1][1] = self._list(level)
                continue
            items.append([m.group(3), ""])
            self.i += 1
        tag = "ol" if first else "ul"
        start = f' start="{first.group(1)}"' if first and first.group(1) != "1" else ""  # sigue después de una imagen
        return f"<{tag}{start}>" + "".join(f"<li>{self.inline(a)}{b}</li>" for a, b in items) + f"</{tag}>"

    def _figure(self, alt: str, path: str) -> None:
        kind = "cel" if "/celular-" in path else "pantalla"
        self.body.append(f'<figure class="{kind}"><img src="{image_url(path)}" alt="{html.escape(alt)}" loading="lazy">'
                         f"<figcaption>{self.inline(alt)}</figcaption></figure>")
        self.i += 1

    def _paragraph(self) -> None:
        words = []
        while self.i < len(self.lines) and self.lines[self.i].strip() and not _BLOCK_START.match(self.lines[self.i]):
            words.append(self.lines[self.i].strip())
            self.i += 1
        self.body.append(f"<p>{self.inline(' '.join(words))}</p>")


def _link(m: re.Match) -> str:
    label, href = m.group(1), m.group(2)
    if href.startswith("#"):
        n = re.match(r"#(\d+)-", href)  # #5-qué-le-puedes-pedir → #s5
        href = f"#s{n.group(1)}" if n else href
    elif href.startswith("../"):
        href = GITHUB + href[3:]
    return f'<a href="{href}">{label}</a>'


def render(markdown: str, template: str) -> str:
    """La página completa: el índice del markdown se cambia por el de la página."""
    text = markdown[: markdown.index("**Contenido**")] + markdown[markdown.index("---"):]
    page = _Page(text)
    body = page.render()
    toc = [f'<li><a href="#s{m.group(1)}"><span class="num">{m.group(1)}</span>{page.inline(m.group(2))}</a></li>'
           for m in re.finditer(r"^## (\d+)\.\s*(.*)$", text, re.M)]
    return template.replace("{{TOC}}", "\n".join(toc)).replace("{{BODY}}", body)


def main() -> None:
    page = render(MARKDOWN.read_text(encoding="utf-8"), TEMPLATE.read_text(encoding="utf-8"))
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    print(f"{PAGE.relative_to(REPO)} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
