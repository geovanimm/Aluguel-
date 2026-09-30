#!/usr/bin/env python3
"""Procura os aluguéis mais baratos de um bairro de Indaial/SC nos sites das
imobiliárias da cidade.

Como funciona:
  1. Para cada imobiliária de `sites.py` (e, com --descobrir, outras achadas
     numa busca na web), visita as páginas iniciais e segue os links internos
     que pareçam levar a imóveis para alugar (aluguel, locação, paginação...).
  2. Em cada página, acha os "cards" de anúncio: um link para o imóvel junto
     com um preço "R$ ...".  Também lê dados estruturados (JSON-LD).
  3. Mantém só os anúncios de aluguel do bairro pedido.  Se o card não diz o
     bairro, abre a página do anúncio para conferir.
  4. Ordena pelo preço e mostra/salva os mais baratos.

Uso:
  python buscar_aluguel.py                      # bairro Carijós, top 20
  python buscar_aluguel.py --top 10 --csv saida.csv
  python buscar_aluguel.py --descobrir          # procura mais imobiliárias
  python buscar_aluguel.py --navegador          # usa Chromium (sites em JS)
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sites import DOMINIOS_IGNORADOS, SITES

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Menor e maior valor aceitos como aluguel mensal.  Abaixo disso quase sempre
# é taxa (condomínio, IPTU); acima, preço de venda.
PRECO_MINIMO = 150.0
PRECO_MAXIMO = 30000.0

RE_PRECO = re.compile(r"R\$\s*([\d]{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")

EXTENSOES_IGNORADAS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip",
    ".mp4", ".css", ".js", ".ico", ".xml",
)


# --------------------------------------------------------------------------
# Texto e preços
# --------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples ("Carijós" -> "carijos")."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def valor_para_float(valor: str) -> float:
    """'1.250,00' -> 1250.0"""
    return float(valor.replace(".", "").replace(",", "."))


def preco_aluguel(texto: str) -> float | None:
    """Escolhe, entre os "R$" do texto, o que é o valor do aluguel.

    Prefere preços rotulados como aluguel/locação; ignora os rotulados como
    condomínio, IPTU, taxa, seguro, total ou venda.
    """
    rotulado, sem_rotulo = [], []
    for m in RE_PRECO.finditer(texto):
        try:
            valor = valor_para_float(m.group(1))
        except ValueError:
            continue
        antes = normalizar(texto[max(0, m.start() - 35):m.start()])
        depois = normalizar(texto[m.end():m.end() + 12])
        # Olha só o rótulo mais próximo, depois do último preço anterior.
        antes = re.split(r"r\$", antes)[-1]
        if re.search(r"condom|cond\.|iptu|taxa|seguro|total|venda|vend[ae]|a partir", antes):
            continue
        if not PRECO_MINIMO <= valor <= PRECO_MAXIMO:
            continue
        if re.search(r"alug|loca|mensal", antes) or re.search(r"/\s*m[eê]s|mensais", depois):
            rotulado.append(valor)
        else:
            sem_rotulo.append(valor)
    if rotulado:
        return rotulado[0]
    if sem_rotulo:
        return sem_rotulo[0]
    return None


def parece_venda(texto_norm: str) -> bool:
    """Card que fala em venda e em nenhum momento em aluguel/locação."""
    tem_venda = re.search(r"\bvenda\b|\bcomprar\b|\bvende-se\b", texto_norm)
    tem_aluguel = re.search(r"alug|loca", texto_norm)
    return bool(tem_venda and not tem_aluguel)


# --------------------------------------------------------------------------
# Extração de anúncios de uma página
# --------------------------------------------------------------------------

@dataclass
class Anuncio:
    imobiliaria: str
    titulo: str
    preco: float
    url: str
    texto: str = field(repr=False, default="")
    confirmado_em: str = ""  # "card", "url", "json-ld" ou "pagina"


def _limpar_url(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


def _link_interno(href: str, base: str) -> str | None:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "whatsapp:", "#")):
        return None
    absoluta = _limpar_url(urljoin(base, href))
    p = urlparse(absoluta)
    if p.scheme not in ("http", "https"):
        return None
    if _dominio(absoluta) != _dominio(base):
        return None
    if p.path.lower().endswith(EXTENSOES_IGNORADAS):
        return None
    return absoluta


def _dominio(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _titulo_do_card(card, link) -> str:
    for tag in card.find_all(["h1", "h2", "h3", "h4", "h5"], limit=1):
        t = tag.get_text(" ", strip=True)
        if t:
            return t
    t = link.get("title") or link.get_text(" ", strip=True)
    if t and "R$" not in t:
        return t
    return card.get_text(" ", strip=True)[:90]


def anuncios_json_ld(soup: BeautifulSoup, url_pagina: str, imobiliaria: str) -> list[Anuncio]:
    """Lê anúncios descritos em <script type="application/ld+json">."""
    achados = []

    def visitar(no):
        if isinstance(no, list):
            for item in no:
                visitar(item)
            return
        if not isinstance(no, dict):
            return
        ofertas = no.get("offers")
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else None
        preco = None
        if isinstance(ofertas, dict):
            preco = ofertas.get("price") or ofertas.get("lowPrice")
        if preco is not None:
            try:
                valor = float(str(preco).replace(",", "."))
            except ValueError:
                valor = None
            if valor and PRECO_MINIMO <= valor <= PRECO_MAXIMO:
                texto = json.dumps(no, ensure_ascii=False)
                url = no.get("url") or (ofertas or {}).get("url") or url_pagina
                achados.append(Anuncio(
                    imobiliaria=imobiliaria,
                    titulo=str(no.get("name") or "")[:120],
                    preco=valor,
                    url=_limpar_url(urljoin(url_pagina, url)),
                    texto=texto,
                ))
        for v in no.values():
            if isinstance(v, (dict, list)):
                visitar(v)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            visitar(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    return achados


def anuncios_em_cards(soup: BeautifulSoup, url_pagina: str, imobiliaria: str) -> list[Anuncio]:
    """Acha blocos "link + R$" que representam um anúncio cada.

    Para cada link interno, sobe na árvore HTML até o menor elemento que
    contenha um preço.  Se esse elemento tiver preços demais, é uma lista
    inteira (não um card) e é descartado.
    """
    por_url: dict[str, Anuncio] = {}
    pagina = _limpar_url(url_pagina)
    for link in soup.find_all("a", href=True):
        url = _link_interno(link["href"], url_pagina)
        if not url or url == pagina:
            continue
        card = None
        for pai in [link, *link.parents][:9]:
            if pai.name in ("body", "html", "[document]"):
                break
            texto = pai.get_text(" ", strip=True)
            if "R$" in texto:
                if len(RE_PRECO.findall(texto)) <= 4:
                    card = pai
                break
        if card is None:
            continue
        texto = card.get_text(" ", strip=True)
        preco = preco_aluguel(texto)
        if preco is None or url in por_url:
            continue
        por_url[url] = Anuncio(
            imobiliaria=imobiliaria,
            titulo=_titulo_do_card(card, link),
            preco=preco,
            url=url,
            texto=texto,
        )
    return list(por_url.values())


def extrair_anuncios(html: str | bytes, url_pagina: str, imobiliaria: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios = {a.url: a for a in anuncios_em_cards(soup, url_pagina, imobiliaria)}
    for a in anuncios_json_ld(soup, url_pagina, imobiliaria):
        anuncios.setdefault(a.url, a)
    return list(anuncios.values())


def menciona_bairro(texto: str, bairro: str) -> bool:
    return normalizar(bairro) in normalizar(unquote(texto)).replace("-", " ")


def texto_principal(html: str | bytes) -> str:
    """Texto da página sem menus, filtros de busca e rodapé, que costumam
    listar todos os bairros da cidade e dariam falso positivo."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "select", "option", "form",
                     "nav", "header", "footer", "aside"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


# --------------------------------------------------------------------------
# Navegação
# --------------------------------------------------------------------------

class Baixador:
    """Baixa páginas com requests ou, opcionalmente, com Chromium (Playwright)
    para sites que só montam a lista de imóveis via JavaScript."""

    def __init__(self, usar_navegador: bool = False, pausa: float = 1.0, timeout: int = 20):
        self.pausa = pausa
        self.timeout = timeout
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
        self._pw = self._browser = None
        if usar_navegador:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                sys.exit("Para --navegador instale: pip install playwright && playwright install chromium")
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()

    def baixar(self, url: str) -> str | bytes | None:
        time.sleep(self.pausa)
        try:
            if self._browser:
                pagina = self._browser.new_page(user_agent=USER_AGENT)
                try:
                    pagina.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
                    return pagina.content()
                finally:
                    pagina.close()
            r = self.sessao.get(url, timeout=self.timeout)
            if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "html"):
                return None
            return r.content
        except Exception as e:  # rede, timeout, SSL...
            print(f"    ! erro em {url}: {e.__class__.__name__}", file=sys.stderr)
            return None

    def fechar(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()


def pontuar_link(url: str, texto_link: str, bairro: str, cidade: str) -> int:
    """Quanto maior, mais provável que o link leve a aluguéis do bairro.
    0 = não vale a pena seguir."""
    alvo = normalizar(unquote(url) + " " + texto_link).replace("-", " ")
    if re.search(r"contato|sobre|quem somos|blog|noticia|trabalhe|login|cadastr|"
                 r"politica|privacidade|anuncie|financiamento|favorito", alvo):
        return 0
    venda = re.search(r"\bvenda\b|\bcomprar\b|\bvendas\b", alvo)
    aluguel = re.search(r"alug|loca", alvo)
    if venda and not aluguel:
        return 0
    pontos = 0
    if aluguel:
        pontos += 3
    if normalizar(bairro) in alvo:
        pontos += 4
    if normalizar(cidade) in alvo:
        pontos += 1
    if re.search(r"pagina|page|pg=|pag=|proxima|\b\d{1,2}\b$", alvo):
        pontos += 2
    if re.search(r"imove|busca|pesquisa|resultado|casa|apartamento|kitnet|sala", alvo):
        pontos += 1
    return pontos


def rastrear_site(site: dict, baixador: Baixador, bairro: str, cidade: str,
                  max_paginas: int, max_verificacoes: int) -> list[Anuncio]:
    nome = site["nome"]
    print(f"\n==> {nome}")
    fila: list[tuple[int, int, str]] = []  # (-pontos, ordem, url)
    vistos: set[str] = set()
    ordem = 0
    for url in site["inicio"]:
        heapq.heappush(fila, (-100, ordem, _limpar_url(url)))
        ordem += 1

    candidatos: dict[str, Anuncio] = {}
    paginas = 0
    while fila and paginas < max_paginas:
        _, _, url = heapq.heappop(fila)
        if url in vistos:
            continue
        vistos.add(url)
        html = baixador.baixar(url)
        paginas += 1
        if not html:
            continue
        novos = extrair_anuncios(html, url, nome)
        for a in novos:
            candidatos.setdefault(a.url, a)
        print(f"    [{paginas:>3}] {len(novos):>3} anúncios  {url}")

        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("a", href=True):
            destino = _link_interno(link["href"], url)
            if not destino or destino in vistos:
                continue
            pontos = pontuar_link(destino, link.get_text(" ", strip=True), bairro, cidade)
            if pontos > 0:
                heapq.heappush(fila, (-pontos, ordem, destino))
                ordem += 1

    # Filtra: aluguel + bairro certo.
    resultado, pendentes = [], []
    for a in candidatos.values():
        texto_norm = normalizar(a.texto)
        if parece_venda(texto_norm):
            continue
        if menciona_bairro(a.texto, bairro) or menciona_bairro(a.titulo, bairro):
            a.confirmado_em = "json-ld" if a.texto.startswith("{") else "card"
            resultado.append(a)
        elif menciona_bairro(a.url, bairro):
            a.confirmado_em = "url"
            resultado.append(a)
        else:
            pendentes.append(a)

    # Cards sem bairro: confere na página do próprio anúncio (mais baratos primeiro).
    pendentes.sort(key=lambda a: a.preco)
    for a in pendentes[:max_verificacoes]:
        html = baixador.baixar(a.url)
        if html and menciona_bairro(texto_principal(html), bairro):
            texto = normalizar(texto_principal(html))
            if parece_venda(texto):
                continue
            a.confirmado_em = "pagina"
            resultado.append(a)

    print(f"    -> {len(candidatos)} anúncios lidos, {len(resultado)} em {bairro}")
    return resultado


# --------------------------------------------------------------------------
# Descoberta de outras imobiliárias (opcional)
# --------------------------------------------------------------------------

def descobrir_sites(cidade: str, bairro: str, conhecidos: list[dict]) -> list[dict]:
    """Busca no DuckDuckGo por imobiliárias da cidade que ainda não estão em
    sites.py e devolve-as no mesmo formato, começando pela página inicial."""
    consultas = [
        f"imobiliária {cidade} SC aluguel",
        f"imobiliária {cidade} SC locação {bairro}",
        f"imóveis para alugar {bairro} {cidade}",
    ]
    ja_tem = {_dominio(u) for s in conhecidos for u in s["inicio"]}
    novos: dict[str, dict] = {}
    sessao = requests.Session()
    sessao.headers["User-Agent"] = USER_AGENT
    for q in consultas:
        try:
            r = sessao.post("https://html.duckduckgo.com/html/", data={"q": q}, timeout=20)
        except requests.RequestException as e:
            print(f"  ! busca falhou ({q}): {e.__class__.__name__}", file=sys.stderr)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            # O DuckDuckGo embrulha o destino em /l/?uddg=<url>
            if "uddg=" in href:
                href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            dom = _dominio(href)
            if not dom or dom in ja_tem or dom in novos:
                continue
            if any(dom == d or dom.endswith("." + d) for d in DOMINIOS_IGNORADOS):
                continue
            novos[dom] = {"nome": a.get_text(" ", strip=True)[:60] or dom,
                          "inicio": [f"https://{urlparse(href).netloc}/", href]}
        time.sleep(1)
    return list(novos.values())


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def formatar_reais(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aluguéis mais baratos de um bairro de Indaial/SC.")
    ap.add_argument("--bairro", default="Carijós")
    ap.add_argument("--cidade", default="Indaial")
    ap.add_argument("--top", type=int, default=20, help="quantos resultados mostrar")
    ap.add_argument("--csv", default="alugueis_carijos.csv", help="arquivo de saída")
    ap.add_argument("--max-paginas", type=int, default=40, help="páginas por site")
    ap.add_argument("--max-verificacoes", type=int, default=30,
                    help="anúncios sem bairro no card para conferir por site")
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre requisições")
    ap.add_argument("--descobrir", action="store_true",
                    help="procurar na web outras imobiliárias além das de sites.py")
    ap.add_argument("--navegador", action="store_true",
                    help="renderizar páginas com Chromium (Playwright) para sites em JavaScript")
    ap.add_argument("--site", action="append", default=[],
                    help="rodar só as imobiliárias cujo nome contém este texto")
    args = ap.parse_args(argv)

    sites = list(SITES)
    if args.site:
        filtros = [normalizar(s) for s in args.site]
        sites = [s for s in sites if any(f in normalizar(s["nome"]) for f in filtros)]
    if args.descobrir:
        print("Procurando outras imobiliárias na web...")
        extras = descobrir_sites(args.cidade, args.bairro, sites)
        for s in extras:
            print(f"  + {s['nome']}  ({s['inicio'][0]})")
        sites += extras

    baixador = Baixador(usar_navegador=args.navegador, pausa=args.pausa)
    todos: dict[str, Anuncio] = {}
    try:
        for site in sites:
            try:
                for a in rastrear_site(site, baixador, args.bairro, args.cidade,
                                       args.max_paginas, args.max_verificacoes):
                    todos.setdefault(a.url, a)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # um site com problema não derruba os outros
                print(f"    ! {site['nome']} falhou: {e!r}", file=sys.stderr)
    finally:
        baixador.fechar()

    ordenados = sorted(todos.values(), key=lambda a: a.preco)
    if not ordenados:
        print(f"\nNenhum aluguel encontrado em {args.bairro}.")
        return 1

    with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["preco", "imobiliaria", "titulo", "url", "bairro_confirmado_em"])
        for a in ordenados:
            w.writerow([f"{a.preco:.2f}".replace(".", ","), a.imobiliaria, a.titulo, a.url, a.confirmado_em])

    print(f"\n{'=' * 80}\n{min(args.top, len(ordenados))} aluguéis mais baratos em "
          f"{args.bairro} - {args.cidade}  ({len(ordenados)} no total)\n{'=' * 80}")
    for i, a in enumerate(ordenados[:args.top], 1):
        print(f"{i:>2}. {formatar_reais(a.preco):>13}  {a.imobiliaria}\n"
              f"    {a.titulo[:75]}\n    {a.url}")
    print(f"\nLista completa salva em {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
