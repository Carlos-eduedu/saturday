"""Anexo e áudio enviados pelo painel: API, saída na Meta e na Evolution."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from test_painel_api import TELEFONE, _cliente_escreve, _conversa_id, _criar, _entrar

from saturday.canais.base import Resultado
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.canais.evolution.saida import SaidaEvolution
from saturday.canais.whatsapp.audio import ErroConversao, para_ogg_opus
from saturday.canais.whatsapp.cliente import WhatsAppClient
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, Mensagem, Outbox
from saturday.dados.sessao import sessao as abrir

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
SIMULADORES = Path(__file__).resolve().parents[3] / "simuladores"


@pytest.fixture
def ana(fabrica):
    return _criar(fabrica, "ana@exemplo.test")


def _assumida(client, service, fabrica, conversation_id):
    _cliente_escreve(service, conversation_id, "oi")
    alvo = _conversa_id(fabrica, conversation_id)
    csrf = _entrar(client, "ana@exemplo.test")
    assert client.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204
    return alvo, csrf


def _anexar(client, alvo, csrf, dados, mime, nome="foto.png", legenda=""):
    return client.post(
        f"/admin/conversas/{alvo}/anexos",
        params={"nome": nome, "legenda": legenda},
        content=dados,
        headers={**csrf, "Content-Type": mime},
    )


# ------------------------------------------------------------------ API


def test_anexo_vai_para_o_storage_e_o_outbox_leva_so_a_chave(
    client_pg, service_pg, fabrica, storage, ana, conversa
):
    alvo, csrf = _assumida(client_pg, service_pg, fabrica, conversa)

    resposta = _anexar(
        client_pg, alvo, csrf, PNG, "image/png", nome="C:\\fotos\\rg.png", legenda="Seu RG"
    )

    assert resposta.status_code == 201, resposta.text
    with abrir(fabrica) as s:
        mensagem = s.get(Mensagem, resposta.json()["mensagem_id"])
        assert mensagem is not None
        assert (mensagem.autor, mensagem.conteudo) == ("atendente", "Seu RG")
        [anexo] = mensagem.anexos or []
        linha = s.scalars(select(Outbox).order_by(Outbox.id.desc())).first()
    assert anexo["nome"] == "rg.png"
    assert anexo["chave"].startswith(f"whatsapp/{TELEFONE}/painel-")
    assert storage.ler(anexo["chave"]) == PNG
    assert linha is not None
    assert linha.payload["midia"] == {**anexo, "tipo": "imagem"}
    assert linha.payload["answer"] == "Seu RG"
    assert "PNG" not in repr(linha.payload)
    # O histórico mostra o nome do anexo.
    detalhe = client_pg.get(f"/admin/conversas/{alvo}").json()
    assert detalhe["mensagens"][-1]["anexos"] == [{"mime_type": "image/png", "nome": "rg.png"}]


@pytest.mark.parametrize(
    ("dados", "mime", "status"),
    [
        (b"oi", "text/plain", 415),
        (PDF, "image/png", 415),
        (b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024), "image/png", 413),
        (b"", "application/pdf", 422),
    ],
)
def test_anexo_recusado_por_tipo_assinatura_ou_tamanho(
    client_pg, service_pg, fabrica, ana, conversa, dados, mime, status
):
    alvo, csrf = _assumida(client_pg, service_pg, fabrica, conversa)
    assert _anexar(client_pg, alvo, csrf, dados, mime).status_code == status


def test_anexo_exige_dono_e_janela_aberta_na_meta(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    assert _anexar(client_pg, alvo, csrf, PNG, "image/png").status_code == 409

    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    with abrir(fabrica) as s:
        s.execute(
            update(Conversa)
            .where(Conversa.conversation_id == conversa)
            .values(ultima_entrada_em=datetime.now(UTC) - timedelta(hours=30))
        )
    fechada = _anexar(client_pg, alvo, csrf, PNG, "image/png")
    assert fechada.status_code == 409
    assert "janela" in fechada.json()["detail"]
    assert _anexar(client_pg, alvo, {}, PNG, "image/png").status_code == 403


# ------------------------------------------------------------------ saída


def _simulador(nome: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"simulador_{nome}_anexo", SIMULADORES / nome / "app.py"
    )
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _linha(storage, tipo, mime, dados, conversation_id, canal) -> Outbox:
    chave = storage.salvar(dados, mime_type=mime, chave=f"{canal}/{TELEFONE}/painel-{tipo}")
    return Outbox(
        id=1,
        canal=canal,
        payload={
            "conversation_id": conversation_id,
            "numero": TELEFONE,
            "phone_number_id": "100000000000001" if canal == "whatsapp" else "inst-1",
            "answer": "segue",
            "midia": {"chave": chave, "mime_type": mime, "nome": "arquivo.x", "tipo": tipo},
        },
    )


@pytest.fixture
def meta(settings) -> Iterator[tuple[ModuleType, httpx.Client, Any]]:
    modulo = _simulador("meta")
    configurado = settings.model_copy(update={"whatsapp_graph_url": "http://meta"})
    with TestClient(modulo.app, base_url="http://meta") as http:
        yield modulo, http, configurado


def test_meta_sobe_a_midia_e_envia_pelo_id(meta, fabrica, storage, conversa):
    modulo, http, configurado = meta
    with abrir(fabrica) as s:
        c = repositorios.obter_ou_criar_conversa(s, conversa, canal="whatsapp", telefone=TELEFONE)
        c.ultima_entrada_em = datetime.now(UTC)
    convertidos: list[bytes] = []

    def converter(dados: bytes) -> bytes:
        convertidos.append(dados)
        return b"OggS-convertido"

    saida = SaidaWhatsApp(
        WhatsAppClient(http, configurado),
        fabrica,
        configurado,
        storage=storage,
        converter_audio=converter,
    )

    documento = _linha(storage, "documento", "application/pdf", PDF, conversa, "whatsapp")
    audio = _linha(storage, "audio", "audio/webm", b"webm-gravado", conversa, "whatsapp")
    assert saida.entregar(documento) is Resultado.OK
    assert saida.entregar(audio) is Resultado.OK

    assert convertidos == [b"webm-gravado"]
    subidas = modulo.SUBIDAS
    assert [s["messaging_product"] and s["arquivo"] for s in subidas] == [True, True]
    assert all(s["content_type"].startswith("multipart/form-data") for s in subidas)
    doc, voz = modulo.ENVIADAS
    assert doc["type"] == "document"
    assert doc["document"] == {"id": subidas[0]["id"], "caption": "segue", "filename": "arquivo.x"}
    assert voz["type"] == "audio"
    assert voz["audio"] == {"id": subidas[1]["id"]}


def test_meta_audio_que_nao_converte_desiste(meta, fabrica, storage, conversa):
    _, http, configurado = meta
    with abrir(fabrica) as s:
        c = repositorios.obter_ou_criar_conversa(s, conversa, canal="whatsapp", telefone=TELEFONE)
        c.ultima_entrada_em = datetime.now(UTC)

    def quebra(_dados: bytes) -> bytes:
        raise ErroConversao("ffmpeg 1: Invalid data")

    saida = SaidaWhatsApp(
        WhatsAppClient(http, configurado),
        fabrica,
        configurado,
        storage=storage,
        converter_audio=quebra,
    )
    linha = _linha(storage, "audio", "audio/webm", b"lixo", conversa, "whatsapp")
    assert saida.entregar(linha) is Resultado.PERMANENTE


def test_evolution_envia_midia_e_audio(settings, fabrica, storage, conversa):
    modulo = _simulador("evolution")
    configurado = settings.model_copy(
        update={
            "evolution_url": "http://evolution",
            "evolution_api_key": SecretStr("chave-do-simulador"),
        }
    )
    with TestClient(modulo.app, base_url="http://evolution") as http:
        saida = SaidaEvolution(EvolutionClient(http, configurado), fabrica, storage=storage)
        imagem = _linha(storage, "imagem", "image/png", PNG, conversa, "evolution")
        audio = _linha(storage, "audio", "audio/webm", b"webm-gravado", conversa, "evolution")
        assert saida.entregar(imagem) is Resultado.OK
        assert saida.entregar(audio) is Resultado.OK

    foto, voz = modulo.ENVIADAS
    assert foto["rota"] == "sendMedia"
    assert {k: foto[k] for k in ("number", "mediatype", "mimetype", "fileName", "caption")} == {
        "number": f"55{TELEFONE}",
        "mediatype": "image",
        "mimetype": "image/png",
        "fileName": "arquivo.x",
        "caption": "segue",
    }
    assert foto["media_bytes"] == len(PNG)
    assert voz["rota"] == "sendWhatsAppAudio"
    assert voz["audio_bytes"] == len(b"webm-gravado")


# ------------------------------------------------------------------ conversão


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg na máquina")
def test_ffmpeg_converte_para_ogg_opus():
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    entrada = subprocess.run(  # noqa: S603 - argumentos fixos
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout

    saida = para_ogg_opus(entrada)

    assert saida.startswith(b"OggS")
    assert b"OpusHead" in saida[:200]
    with pytest.raises(ErroConversao):
        para_ogg_opus(b"isto nao e audio")


def test_storage_fora_do_ar_responde_503(client_pg, service_pg, fabrica, ana, conversa):
    alvo, csrf = _assumida(client_pg, service_pg, fabrica, conversa)

    class Quebrado:
        def salvar(self, *_a, **_k):
            raise RuntimeError("S3 API Requests must be made to API port.")

    service_pg.storage = Quebrado()

    resposta = _anexar(client_pg, alvo, csrf, PNG, "image/png")

    assert resposta.status_code == 503
    with abrir(fabrica) as s:
        assert not [o for o in s.scalars(select(Outbox)) if "midia" in o.payload]
