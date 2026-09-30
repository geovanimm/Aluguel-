# Aluguel mais barato no Carijós (Indaial/SC)

Robô que visita os sites das imobiliárias de Indaial, junta os anúncios de
**aluguel** do bairro **Carijós** e mostra os mais baratos.

## Como usar

```bash
pip install -r requirements.txt
python buscar_aluguel.py
```

Saída (exemplo):

```
 1.     R$ 750,00  Mapa Imobiliária
    Kitnet mobiliada
    https://www.imobiliariamapa.com.br/imoveis/...
 2.   R$ 1.000,00  Imóveis-SC (várias imobiliárias)
    ...
Lista completa salva em alugueis_carijos.csv
```

O CSV (separado por `;`, abre direto no Excel) traz preço, imobiliária,
título, link e onde o bairro foi confirmado.

### Opções úteis

| Opção | O que faz |
|---|---|
| `--top 10` | quantos resultados mostrar (padrão 20) |
| `--descobrir` | procura na web outras imobiliárias de Indaial além das cadastradas |
| `--navegador` | abre as páginas no Chromium, para sites que montam a lista via JavaScript (`pip install playwright && playwright install chromium`) |
| `--site mapa` | roda só as imobiliárias cujo nome contém o texto (pode repetir) |
| `--bairro "Centro"` | outro bairro |
| `--max-paginas 40` | limite de páginas visitadas por site |
| `--pausa 1.0` | segundos entre requisições (seja gentil com os sites) |

## Imobiliárias cadastradas

Estão em [`sites.py`](sites.py): Mapa, Hauster, Terra, Médio Vale,
Imobiliária Hoje, Metta, Líder, MGF e o portal Imóveis-SC. Para incluir outra,
adicione `{"nome": ..., "inicio": [url, ...]}` à lista. Uma URL inicial que já
filtra aluguel/Indaial/Carijós deixa a busca mais rápida e precisa.

Portais grandes (Zap, VivaReal, OLX) ficam de fora: eles bloqueiam robôs.

## Como funciona

1. A partir das páginas iniciais, segue links do mesmo site que pareçam levar
   a aluguéis (palavras como "alugar", "locação", "carijós", paginação) e
   ignora venda, contato, blog etc.
2. Em cada página acha os *cards* de anúncio (link do imóvel + "R$") e lê
   também dados estruturados JSON-LD.
3. Escolhe o valor do aluguel ignorando condomínio, IPTU, taxas e total.
4. Mantém só os anúncios do bairro. Se o card não diz o bairro, abre a página
   do anúncio para conferir (desconsiderando menus, filtros e rodapé, que
   costumam listar todos os bairros).
5. Ordena pelo preço.

Como cada site tem um layout diferente, a extração é heurística: confira o
anúncio no link antes de fechar negócio.

## Testes

```bash
pip install pytest
python -m pytest
```
