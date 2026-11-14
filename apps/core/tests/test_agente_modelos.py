"""Aba Agente: modelos por etapa, catálogo, teste, versões e permissão. Exige Postgres."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import select, update

from saturday.agente_config import Modelos
from saturday.dados.modelos import Auditoria, UsuarioPainel
from saturday.dados.sessao import sessao as abrir
from saturday.painel import sessoes

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste

CATALOGO = {
    "data": [
        {
            "id": "openai/gpt-4o-mini",
            "name": "GPT-4o mini",
            "context_length": 128000,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006", "image": "0"},
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            "top_provider": {"max_completion_tokens": 16384},
            "supported_parameters": ["response_format", "temperature"],
        },
        {
            "id": "meta/so-texto",
            "name": "Só texto",
            "context_length": 8000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["response_format"],
        },
        {"id": "id com espaço", "name": "inválido"},
    ]
}


def _entrar(client, fabrica, email, perfil, *, editor=False) -> dict[str, str]:
    with abrir(fabrica) as s:
        usuario = sessoes.criar_usuario(s, email, SENHA, perfil)
        s.execute(
            update(UsuarioPainel)
            .where(UsuarioPainel.id == usuario.id)
            .values(pode_editar_agente=editor)
        )
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _http(client, rotas: dict[str, Any]) -> list[httpx.Request]:
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(200, json=rotas[str(pedido.url)])

    client.app.state.http = httpx.Client(transport=httpx.MockTransport(responder))
    return pedidos


def _acoes(fabrica) -> list[str]:
    with abrir(fabrica) as s:
        return [a.acao for a in s.scalars(select(Auditoria).order_by(Auditoria.id))]


def test_editor_salva_versao_e_o_turno_seguinte_usa(client_pg, fabrica, settings):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test", "atendente", editor=True)
    inicio = client_pg.get("/admin/agente/modelos").json()
    assert inicio["vigente"] is None and inicio["pode_editar"] is True
    llm = next(p for p in inicio["papeis"] if p["papel"] == "llm")
    assert llm["origem"] == "ambiente" and llm["variavel"] == "SATURDAY_LLM_MODEL"

    salvo = client_pg.post(
        "/admin/agente/versoes",
        json={"versao_base": None, "modelos": {"llm": "openai/gpt-4o-mini"}, "nota": "teste"},
        headers=csrf,
    )
    assert salvo.status_code == 201 and salvo.json() == {"versao": 1}
    assert Modelos(settings, fabrica).modelo("llm") == "openai/gpt-4o-mini"
    # Sem fábrica (ou com o banco fora), vale o ambiente.
    assert Modelos(settings).modelo("llm") == ""

    depois = client_pg.get("/admin/agente/modelos").json()
    assert depois["vigente"]["versao"] == 1 and depois["vigente"]["autor"]
    assert "agente_config_salva" in _acoes(fabrica)

    # Base desatualizada: outra pessoa salvou antes.
    velho = client_pg.post(
        "/admin/agente/versoes",
        json={"versao_base": None, "modelos": {"llm": "outro/modelo"}},
        headers=csrf,
    )
    assert velho.status_code == 409
    igual = client_pg.post(
        "/admin/agente/versoes",
        json={"versao_base": 1, "modelos": {"llm": "openai/gpt-4o-mini"}},
        headers=csrf,
    )
    assert igual.status_code == 422


def test_sem_permissao_nao_salva_nem_atualiza_catalogo(client_pg, fabrica):
    # Nem gestor: a permissão independe do perfil.
    csrf = _entrar(client_pg, fabrica, "gestor@exemplo.test", "gestor", editor=False)
    assert client_pg.get("/admin/agente/modelos").json()["pode_editar"] is False
    corpo = {"versao_base": None, "modelos": {"llm": "x/y"}}
    assert client_pg.post("/admin/agente/versoes", json=corpo, headers=csrf).status_code == 403
    assert client_pg.post("/admin/agente/catalogo/atualizar", headers=csrf).status_code == 403
    # Sem CSRF também não.
    _entrar(client_pg, fabrica, "edita2@exemplo.test", "atendente", editor=True)
    assert client_pg.post("/admin/agente/versoes", json=corpo).status_code == 403


def test_catalogo_traz_preco_por_milhao_e_valida_a_escolha(client_pg, fabrica):
    pedidos = _http(client_pg, {"https://openrouter.ai/api/v1/models": CATALOGO})
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test", "atendente", editor=True)

    assert client_pg.post("/admin/agente/catalogo/atualizar", headers=csrf).json() == {"modelos": 2}
    assert "authorization" not in pedidos[0].headers
    catalogo = client_pg.get("/admin/agente/modelos").json()["catalogo"]
    assert catalogo["fonte"] == "https://openrouter.ai/api/v1/models"
    assert catalogo["buscado_em"]
    mini = next(m for m in catalogo["modelos"] if m["id"] == "openai/gpt-4o-mini")
    assert mini["preco_entrada"] == 0.15 and mini["preco_saida"] == 0.6
    assert mini["contexto"] == 128000 and mini["max_saida"] == 16384
    assert "image" in mini["entrada"]

    def salvar(modelos):
        return client_pg.post(
            "/admin/agente/versoes", json={"versao_base": None, "modelos": modelos}, headers=csrf
        )

    assert "não aceita image" in salvar({"visao": "meta/so-texto"}).json()["detail"]
    assert "não está no catálogo" in salvar({"llm": "sumiu/modelo"}).json()["detail"]
    # Jev e transcrição têm provedor próprio: fora do catálogo da OpenRouter.
    assert salvar({"jev": "typesafe/jev-2.0", "visao": "openai/gpt-4o-mini"}).status_code == 201


def test_restaurar_cria_versao_nova_com_os_modelos_antigos(client_pg, fabrica, settings):
    csrf = _entrar(client_pg, fabrica, "edita@exemplo.test", "atendente", editor=True)
    for base, modelo in ((None, "a/um"), (1, "b/dois")):
        r = client_pg.post(
            "/admin/agente/versoes",
            json={"versao_base": base, "modelos": {"llm": modelo}},
            headers=csrf,
        )
        assert r.status_code == 201

    r = client_pg.post("/admin/agente/versoes/1/restaurar", json={"versao_base": 2}, headers=csrf)
    assert r.json() == {"versao": 3}
    versoes = client_pg.get("/admin/agente/versoes").json()
    assert [v["versao"] for v in versoes] == [3, 2, 1]
    assert versoes[0]["restaurada_de"] == 1 and versoes[0]["modelos"]["llm"] == "a/um"
    assert Modelos(settings, fabrica).modelo("llm") == "a/um"
    assert "agente_config_restaurada" in _acoes(fabrica)


def test_testar_modelo_e_so_do_gestor_e_usa_o_prompt_real(client_pg, fabrica, settings):
    client_pg.app.state.settings = settings.model_copy(
        update={"openrouter_api_key": SecretStr("chave-de-teste")}
    )
    resposta = {
        "choices": [{"message": {"content": json.dumps({"resposta": "Oi!", "resolvido": True})}}],
        "usage": {"cost": 0.0002, "prompt_tokens": 900, "completion_tokens": 12},
    }
    pedidos = _http(client_pg, {"https://openrouter.ai/api/v1/chat/completions": resposta})
    corpo = {"papel": "llm", "modelo": "openai/gpt-4o-mini", "texto": "vocês cobram algo?"}

    atendente = _entrar(client_pg, fabrica, "ana@exemplo.test", "atendente", editor=True)
    assert (
        client_pg.post("/admin/agente/modelos/testar", json=corpo, headers=atendente).status_code
        == 403
    )

    gestor = _entrar(client_pg, fabrica, "gestor@exemplo.test", "gestor")
    r = client_pg.post("/admin/agente/modelos/testar", json=corpo, headers=gestor).json()
    assert r["ok"] is True and r["resposta"] == "Oi!" and r["detalhe"] == {"resolvido": True}
    assert r["custo_usd"] == 0.0002 and r["tokens_entrada"] == 900
    enviado = json.loads(pedidos[0].content)
    assert enviado["model"] == "openai/gpt-4o-mini"
    assert enviado["messages"][0]["role"] == "system"  # o prompt da FAQ, como no atendimento

    transcricao = {**corpo, "papel": "transcricao"}
    assert (
        client_pg.post("/admin/agente/modelos/testar", json=transcricao, headers=gestor).status_code
        == 422
    )
    with abrir(fabrica) as s:
        [auditoria] = s.scalars(select(Auditoria).where(Auditoria.acao == "agente_modelo_testado"))
        assert "cobram" not in json.dumps(auditoria.detalhe)


def test_eu_e_usuarios_mostram_a_permissao(client_pg, fabrica):
    csrf = _entrar(client_pg, fabrica, "gestor@exemplo.test", "gestor")
    assert client_pg.get("/admin/eu").json()["pode_editar_agente"] is False
    with abrir(fabrica) as s:
        alvo = sessoes.criar_usuario(s, "ana@exemplo.test", SENHA, "atendente")
        alvo_id = str(alvo.id)
    r = client_pg.patch(
        f"/admin/gestao/usuarios/{alvo_id}", json={"pode_editar_agente": True}, headers=csrf
    )
    assert r.status_code == 204, r.text
    linha = next(u for u in client_pg.get("/admin/gestao/usuarios").json() if u["id"] == alvo_id)
    assert linha["pode_editar_agente"] is True
