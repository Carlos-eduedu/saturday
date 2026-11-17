"""Storage S3 contra um S3 de verdade: o caminho que a produção usa, sem cliente falso.

Pulado sem `SATURDAY_TEST_S3_ENDPOINT`. Com o S3 local do compose no ar
(`docker compose --profile s3 up -d s3`, bucket `saturday`):

    SATURDAY_TEST_S3_ENDPOINT=http://127.0.0.1:9000 uv run pytest tests/test_storage_s3_real.py

O bucket (`SATURDAY_TEST_S3_BUCKET`, padrão `saturday`) precisa existir; os
testes apagam o que gravam.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from saturday.settings import Settings
from saturday.storage.base import Storage, criar_storage
from saturday.storage.s3 import S3Storage

ENDPOINT = os.environ.get("SATURDAY_TEST_S3_ENDPOINT", "").strip()
BUCKET = os.environ.get("SATURDAY_TEST_S3_BUCKET", "").strip() or "saturday"
# Credencial fictícia: o S3 local aceita qualquer uma.
CREDENCIAL = "credencial-de-teste"

pytestmark = pytest.mark.skipif(
    not ENDPOINT,
    reason="SATURDAY_TEST_S3_ENDPOINT não definida: este teste exige um S3 de verdade.",
)


# A região entra na assinatura (s3v4): a padrão e a de um bucket em São Paulo.
@pytest.fixture(params=["us-east-1", "sa-east-1"])
def storage(request: pytest.FixtureRequest) -> Storage:
    return criar_storage(
        Settings(
            environment="dev",
            s3_endpoint=ENDPOINT,
            s3_bucket=BUCKET,
            s3_access_key=SecretStr(CREDENCIAL),
            s3_secret_key=SecretStr(CREDENCIAL),
            s3_regiao=request.param,
        )
    )


@pytest.fixture
def chave(storage: Storage) -> Iterator[str]:
    destino = f"teste-integracao/{uuid.uuid4().hex}"
    yield destino
    storage.apagar(destino)


def test_a_fabrica_entrega_o_s3_de_producao(storage: Storage) -> None:
    assert isinstance(storage, S3Storage)


def test_grava_e_le_binario_com_o_tipo(storage: Storage, chave: str) -> None:
    # 1 MiB com todos os bytes: nada de texto que um proxy pudesse recodificar.
    dados = bytes(range(256)) * 4096

    assert storage.salvar(dados, mime_type="application/pdf", chave=chave) == chave

    assert storage.ler(chave) == dados
    assert isinstance(storage, S3Storage)
    cabecalho = storage._cliente.head_object(Bucket=BUCKET, Key=chave)
    assert cabecalho["ContentType"] == "application/pdf"
    assert cabecalho["ContentLength"] == len(dados)


def test_sem_chave_gera_uma_em_anexos(storage: Storage) -> None:
    gerada = storage.salvar(b"conteudo", mime_type="image/png")
    try:
        assert gerada.startswith("anexos/")
        assert storage.ler(gerada) == b"conteudo"
    finally:
        storage.apagar(gerada)


def test_mesma_chave_regrava_o_mesmo_objeto(storage: Storage, chave: str) -> None:
    storage.salvar(b"primeiro", mime_type="image/jpeg", chave=chave)
    storage.salvar(b"segundo", mime_type="image/jpeg", chave=chave)

    assert storage.ler(chave) == b"segundo"


def test_ler_chave_inexistente_vira_keyerror(storage: Storage, chave: str) -> None:
    with pytest.raises(KeyError):
        storage.ler(chave)


def test_apagar_remove_e_pode_repetir(storage: Storage, chave: str) -> None:
    storage.salvar(b"x", mime_type="application/pdf", chave=chave)

    storage.apagar(chave)
    storage.apagar(chave)  # a retenção pode rodar duas vezes

    with pytest.raises(KeyError):
        storage.ler(chave)
