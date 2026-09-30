import http.server
import threading
from functools import partial
from pathlib import Path

import pytest

import buscar_aluguel as ba

LISTA = """
<html><body>
<header><nav><a href="/contato">Contato</a><a href="/venda">Comprar</a></nav></header>
<form><select name="bairro"><option>Carijós</option><option>Centro</option></select></form>
<div class="lista">
  <div class="card">
    <a href="/imovel/101"><img src="a.jpg"></a>
    <h3>Apartamento 2 quartos</h3>
    <p>Carijós - Indaial/SC</p>
    <p>Aluguel R$ 1.250,00</p><p>Condomínio R$ 180,00</p>
  </div>
  <div class="card">
    <a href="/imovel/102">Casa com pátio</a>
    <p>Centro - Indaial</p><p>R$ 900,00 /mês</p>
  </div>
  <div class="card">
    <a href="/imovel/103">Kitnet mobiliada</a>
    <span>IPTU R$ 50,00</span><span>Locação R$ 750,00</span>
  </div>
  <div class="card">
    <a href="/imovel/104">Casa à venda no Carijós</a>
    <p>Venda R$ 450.000,00</p>
  </div>
</div>
<a href="/alugar/indaial/carijos?pagina=2">2</a>
<footer>Bairros atendidos: Carijós, Centro, Nações</footer>
</body></html>
"""

PAGINA_2 = """
<html><body>
<div class="item"><a href="/imovel/105"><h2>Sala comercial</h2>
<span>Carijós</span><b>R$ 1.000</b></a></div>
</body></html>
"""

DETALHE_103 = """
<html><body><h1>Kitnet mobiliada</h1><p>Rua X, Carijós, Indaial</p>
<p>Locação R$ 750,00</p><footer>Centro</footer></body></html>
"""

DETALHE_102 = """
<html><body><h1>Casa com pátio</h1><p>Rua Y, Centro, Indaial</p>
<form><select><option>Carijós</option></select></form>
<footer>Bairros: Carijós</footer></body></html>
"""


@pytest.mark.parametrize("texto,esperado", [
    ("Aluguel R$ 1.250,00 Condomínio R$ 180,00", 1250.0),
    ("Condomínio R$ 180,00 Aluguel R$ 1.250,00", 1250.0),
    ("IPTU R$ 50,00 R$ 800", 800.0),
    ("R$ 1.100,00 /mês", 1100.0),
    ("Total R$ 1.817,26 Locação R$ 1.500,00", 1500.0),
    ("Venda R$ 450.000,00", None),
    ("Sem preço", None),
])
def test_preco_aluguel(texto, esperado):
    assert ba.preco_aluguel(texto) == esperado


def test_normalizar_e_bairro():
    assert ba.normalizar("  Carijós\n") == "carijos"
    assert ba.menciona_bairro("https://x.com/alugar/indaial/carijos/", "Carijós")
    assert ba.menciona_bairro("/busca?bairro=Carij%C3%B3s", "Carijós")
    assert not ba.menciona_bairro("Centro", "Carijós")


def test_extrair_cards():
    anuncios = {a.url: a for a in ba.extrair_anuncios(LISTA, "https://imob.com/alugar", "Imob")}
    assert anuncios["https://imob.com/imovel/101"].preco == 1250.0
    assert anuncios["https://imob.com/imovel/101"].titulo == "Apartamento 2 quartos"
    assert anuncios["https://imob.com/imovel/102"].preco == 900.0
    assert anuncios["https://imob.com/imovel/103"].preco == 750.0
    assert "https://imob.com/imovel/104" not in anuncios  # preço de venda
    assert "https://imob.com/contato" not in anuncios


def test_json_ld():
    html = """<script type="application/ld+json">
    {"@graph": [{"@type": "Apartment", "name": "Apto Carijós", "url": "/i/9",
      "address": {"addressLocality": "Indaial", "streetAddress": "Carijós"},
      "offers": {"@type": "Offer", "price": "980.00"}}]}</script>"""
    [a] = ba.extrair_anuncios(html, "https://imob.com/", "Imob")
    assert (a.preco, a.url) == (980.0, "https://imob.com/i/9")


def test_texto_principal_ignora_filtros_e_rodape():
    assert not ba.menciona_bairro(ba.texto_principal(DETALHE_102), "Carijós")
    assert ba.menciona_bairro(ba.texto_principal(DETALHE_103), "Carijós")


def test_pontuar_link():
    assert ba.pontuar_link("https://x.com/contato", "Fale conosco", "Carijós", "Indaial") == 0
    assert ba.pontuar_link("https://x.com/venda/casa", "", "Carijós", "Indaial") == 0
    assert (ba.pontuar_link("https://x.com/alugar/indaial/carijos", "", "Carijós", "Indaial")
            > ba.pontuar_link("https://x.com/alugar", "", "Carijós", "Indaial") > 0)


@pytest.fixture
def site_local(tmp_path: Path):
    arquivos = {
        "alugar/indaial/carijos/index.html": LISTA,
        "alugar/indaial/carijos/pagina2.html": PAGINA_2,
        "imovel/102/index.html": DETALHE_102,
        "imovel/103/index.html": DETALHE_103,
    }
    for caminho, html in arquivos.items():
        destino = tmp_path / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(html, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            # ?pagina=2 -> pagina2.html (simula paginação por query string)
            if "pagina=2" in path:
                return str(tmp_path / "alugar/indaial/carijos/pagina2.html")
            return super().translate_path(path)

        def log_message(self, *args):
            pass

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()


def test_rastrear_site_completo(site_local):
    site = {"nome": "Imob Teste", "inicio": [f"{site_local}/alugar/indaial/carijos/"]}
    baixador = ba.Baixador(pausa=0)
    baixador.sessao.trust_env = False  # não passar pelo proxy no teste
    resultado = ba.rastrear_site(site, baixador, "Carijós", "Indaial",
                                 max_paginas=10, max_verificacoes=10)
    precos = sorted((a.preco, a.url.rsplit("/", 1)[-1], a.confirmado_em) for a in resultado)
    assert precos == [
        (750.0, "103", "pagina"),   # bairro só na página do anúncio
        (1000.0, "105", "card"),    # veio da página 2
        (1250.0, "101", "card"),
    ]  # 102 é do Centro; 104 é venda
