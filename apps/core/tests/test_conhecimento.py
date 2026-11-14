"""Base de conhecimento (RAG): trechos, leitura, indexação, busca e a aba no painel.

Os embeddings são falsos (MockTransport): cada texto vira um vetor pelas
palavras-chave, então a busca é previsível. Exige Postgres com pgvector.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update

from saturday.conhecimento import (
    TRECHO_CARACTERES,
    Conhecimento,
    ErroConhecimento,
    Trecho,
    extrair_texto,
    quebrar,
)
from saturday.dados.modelos import FonteConhecimento, TrechoConhecimento, UsuarioPainel
from saturday.dados.sessao import sessao as abrir
from saturday.painel import sessoes
from saturday.services.llm import _system_prompt

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
PALAVRAS = ("pix", "taxa", "horário")


def _pdf(linha: str) -> bytes:
    """PDF mínimo e válido (com xref) com uma linha de texto selecionável."""

    conteudo = f"BT /F1 12 Tf 10 50 Td ({linha}) Tj ET".encode()
    objetos = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    saida = b"%PDF-1.4\n"
    posicoes = []
    for i, obj in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj" % i + obj + b"endobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    saida += b"".join(b"%010d 00000 n \n" % pos for pos in posicoes)
    saida += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objetos) + 1, xref)
    return saida


PDF = _pdf("O pix cai em 1 dia")


def _vetor(texto: str) -> list[float]:
    t = texto.lower()
    return [float(p in t) for p in PALAVRAS] + [0.1]


def _http() -> tuple[httpx.Client, list[dict]]:
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content)
        pedidos.append(corpo)
        dados = [{"index": i, "embedding": _vetor(t)} for i, t in enumerate(corpo["input"])]
        return httpx.Response(200, json={"data": dados, "usage": {"prompt_tokens": 5}})

    return httpx.Client(transport=httpx.MockTransport(responder)), pedidos


@pytest.fixture
def com_chave(settings):
    return settings.model_copy(update={"openrouter_api_key": SecretStr("chave-de-teste")})


def _entrar(client, fabrica, email, *, editor=True, perfil="atendente") -> dict[str, str]:
    with abrir(fabrica) as s:
        u = sessoes.criar_usuario(s, email, SENHA, perfil)
        s.execute(
            update(UsuarioPainel).where(UsuarioPainel.id == u.id).values(pode_editar_agente=editor)
        )
    client.cookies.clear()
    r = client.post("/admin/login", json={"email": email, "senha": SENHA})
    return {"X-CSRF-Token": r.json()["csrf"]}


# ------------------------------------------------------------------ sem banco


def test_quebrar_respeita_o_tamanho_e_nao_perde_texto():
    paragrafos = [f"Parágrafo {i}. " + "palavra " * 60 for i in range(12)]
    trechos = quebrar("\n\n".join(paragrafos))
    assert len(trechos) > 1
    assert all(len(t) <= TRECHO_CARACTERES + 10 for t in trechos)
    for i in range(12):
        assert any(f"Parágrafo {i}." in t for t in trechos)
    gigante = quebrar("x " * 3000)
    assert all(len(t) <= TRECHO_CARACTERES for t in gigante)


def test_extrai_texto_de_pdf_e_txt_e_recusa_vazio():
    assert "pix cai em 1 dia" in extrair_texto("pdf", PDF)
    assert extrair_texto("txt", "Olá\r\n\r\n\r\nmundo".encode("latin-1")) == "Olá\n\nmundo"
    with pytest.raises(ErroConhecimento):
        extrair_texto("pdf", b"%PDF-1.4 quebrado")
    with pytest.raises(ErroConhecimento):
        extrair_texto("markdown", b"   \n  ")


def test_trechos_entram_no_prompt_so_quando_existem():
    sem = _system_prompt(None)
    com = _system_prompt(None, [Trecho("Pix", "O pix cai em 1 dia.", 0.9)])
    assert "base de conhecimento" not in sem
    assert "[Pix]\nO pix cai em 1 dia." in com and com.startswith(sem.split("FAQ:")[0])


# ------------------------------------------------------------------ com banco


def test_texto_indexado_e_encontrado_pela_pergunta(client_pg, fabrica, service_pg, com_chave):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test")
    for titulo, texto in (("Pix", "O pix cai em até 1 dia útil."), ("Taxas", "Não há taxa.")):
        r = client_pg.post(
            "/admin/agente/conhecimento/texto",
            json={"titulo": titulo, "texto": texto},
            headers=csrf,
        )
        assert r.status_code == 201

    http, pedidos = _http()
    conhecimento = Conhecimento(http, com_chave, fabrica)
    assert conhecimento.indexar_pendente(service_pg.storage) is True
    assert conhecimento.indexar_pendente(service_pg.storage) is True
    assert conhecimento.indexar_pendente(service_pg.storage) is False
    assert pedidos[0]["model"] == "openai/text-embedding-3-small"

    lista = client_pg.get("/admin/agente/conhecimento").json()
    assert {f["status"] for f in lista["fontes"]} == {"pronta"}
    assert all(f["trechos"] == 1 and f["indexada_em"] for f in lista["fontes"])

    [achado] = conhecimento.buscar("quando cai o pix?")
    assert achado.titulo == "Pix" and achado.similaridade > 0.9
    assert conhecimento.buscar("qual o endereço de vocês?") == []


def test_arquivo_pdf_vai_para_o_storage_e_some_ao_remover(
    client_pg, fabrica, service_pg, com_chave
):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test")

    def enviar(nome, dados):
        return client_pg.post(
            "/admin/agente/conhecimento/arquivo",
            params={"titulo": "Manual", "nome": nome},
            content=dados,
            headers={**csrf, "Content-Type": "application/octet-stream"},
        )

    assert enviar("manual.docx", b"x").status_code == 415
    assert enviar("falso.pdf", b"nao sou pdf").status_code == 415
    r = enviar("C:\\docs\\manual.pdf", PDF)
    assert r.status_code == 201
    fonte_id = r.json()["id"]

    http, _ = _http()
    Conhecimento(http, com_chave, fabrica).indexar_pendente(service_pg.storage)
    [fonte] = client_pg.get("/admin/agente/conhecimento").json()["fontes"]
    assert fonte["status"] == "pronta" and fonte["arquivo_nome"] == "manual.pdf"
    assert fonte["editavel"] is False

    with abrir(fabrica) as s:
        chave = s.get(FonteConhecimento, fonte_id).arquivo_chave
    assert service_pg.storage.ler(chave) == PDF
    assert (
        client_pg.delete(f"/admin/agente/conhecimento/{fonte_id}", headers=csrf).status_code == 204
    )
    with abrir(fabrica) as s:
        assert s.scalar(select(func.count()).select_from(TrechoConhecimento)) == 0
    with pytest.raises(KeyError):
        service_pg.storage.ler(chave)


def test_falha_de_embeddings_vira_erro_visivel(client_pg, fabrica, service_pg, settings):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test")
    client_pg.post(
        "/admin/agente/conhecimento/texto", json={"titulo": "A", "texto": "b"}, headers=csrf
    )
    http, _ = _http()
    # Sem chave da OpenRouter: não indexa, e o painel mostra o motivo.
    Conhecimento(http, settings, fabrica).indexar_pendente(service_pg.storage)
    [fonte] = client_pg.get("/admin/agente/conhecimento").json()["fontes"]
    assert fonte["status"] == "erro" and "embeddings" in fonte["erro"]


def test_editar_texto_e_trocar_o_modelo_mandam_reindexar(client_pg, fabrica, service_pg, com_chave):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test")
    fonte_id = client_pg.post(
        "/admin/agente/conhecimento/texto", json={"titulo": "A", "texto": "pix"}, headers=csrf
    ).json()["id"]
    http, _ = _http()
    Conhecimento(http, com_chave, fabrica).indexar_pendente(service_pg.storage)

    r = client_pg.patch(
        f"/admin/agente/conhecimento/{fonte_id}", json={"texto": "taxa"}, headers=csrf
    )
    assert r.status_code == 204
    [fonte] = client_pg.get("/admin/agente/conhecimento").json()["fontes"]
    assert fonte["status"] == "pendente"
    Conhecimento(http, com_chave, fabrica).indexar_pendente(service_pg.storage)

    r = client_pg.post(
        "/admin/agente/versoes",
        json={"versao_base": None, "modelos": {"embeddings": "openai/text-embedding-3-large"}},
        headers=csrf,
    )
    assert r.status_code == 201
    lista = client_pg.get("/admin/agente/conhecimento").json()
    assert lista["modelo_embeddings"] == "openai/text-embedding-3-large"
    assert lista["fontes"][0]["status"] == "pendente"


def test_sem_permissao_so_ve(client_pg, fabrica):
    csrf = _entrar(client_pg, fabrica, "ana@exemplo.test", editor=False, perfil="gestor")
    assert client_pg.get("/admin/agente/conhecimento").json()["pode_editar"] is False
    r = client_pg.post(
        "/admin/agente/conhecimento/texto", json={"titulo": "A", "texto": "b"}, headers=csrf
    )
    assert r.status_code == 403
