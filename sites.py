"""Imobiliárias de Indaial/SC e as páginas por onde o robô começa a procurar.

Para adicionar uma imobiliária nova, basta incluir um item na lista SITES.
`inicio` são as primeiras páginas visitadas; a partir delas o robô segue
links do mesmo site que pareçam levar a imóveis para alugar (ex.: "alugar",
"locacao", "carijos", paginação).  Quanto mais específica a URL inicial
(já filtrada por aluguel/Indaial/Carijós), mais rápido e preciso fica.
"""

SITES = [
    {
        "nome": "Mapa Imobiliária",
        "inicio": [
            "https://www.imobiliariamapa.com.br/alugar/apartamento/indaial/carijos/",
            "https://www.imobiliariamapa.com.br/alugar/casa/indaial/carijos/",
            "https://www.imobiliariamapa.com.br/busca/imoveis/alugar/indaial?bairro=Carij%C3%B3s",
        ],
    },
    {
        "nome": "Hauster Imóveis",
        "inicio": [
            "https://hausterimoveis.com.br/alugar/casa/indaial",
            "https://hausterimoveis.com.br/alugar/apartamento/indaial",
            "https://hausterimoveis.com.br/",
        ],
    },
    {
        "nome": "Terra Assessoria Imobiliária",
        "inicio": ["https://www.terraimobiliaria.net/"],
    },
    {
        "nome": "Imobiliária Médio Vale",
        "inicio": ["https://imobiliariamediovale.com.br/"],
    },
    {
        "nome": "Imobiliária Hoje",
        "inicio": ["https://imobiliariahoje.com.br/"],
    },
    {
        "nome": "Metta Negócios Imobiliários",
        "inicio": ["https://www.mettaimobi.com.br/"],
    },
    {
        "nome": "Líder Imobiliária",
        "inicio": ["https://www.liderimobiliaria.net/imoveis"],
    },
    {
        "nome": "MGF Imóveis",
        "inicio": [
            "https://www.mgfimoveis.com.br/aluguel/casa/sc-indaial",
            "https://www.mgfimoveis.com.br/aluguel/apartamento/sc-indaial",
        ],
    },
    # Portal regional que reúne anúncios de várias imobiliárias de SC.
    {
        "nome": "Imóveis-SC (várias imobiliárias)",
        "inicio": [
            "https://www.imoveis-sc.com.br/indaial/alugar/apartamento/carijos",
            "https://www.imoveis-sc.com.br/indaial/alugar/casa/carijos",
            "https://www.imoveis-sc.com.br/indaial/alugar/sala-escritorio/carijos",
        ],
    },
]

# Domínios que nunca devem entrar pela descoberta automática: portais grandes
# bloqueiam robôs e redes sociais/diretórios não têm anúncios.
DOMINIOS_IGNORADOS = {
    "zapimoveis.com.br", "vivareal.com.br", "olx.com.br", "imovelweb.com.br",
    "wimoveis.com.br", "quintoandar.com.br", "mitula.com.br", "trovit.com.br",
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com",
    "google.com", "reclameaqui.com.br", "redecasas.com.br", "wikipedia.org",
    "duckduckgo.com", "bing.com",
}
