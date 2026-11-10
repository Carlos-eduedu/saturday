"""Storage S3: contrato coberto com cliente falso, sem rede.

O MinIO do compose não é obrigatório para testar a camada: `S3Storage` recebe um
cliente, e o que interessa é o que ela manda para lá.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr

from saturday.settings import Settings
from saturday.storage.s3 import S3Storage

BUCKET = "saturday-teste"
# Credencial de teste: o cliente S3 aqui é falso, nada sai para a rede.
CREDENCIAL = "credencial-de-teste"


class ClienteS3Falso:
    def __init__(self) -> None:
        self.objetos: dict[str, bytes] = {}
        self.tipos: dict[str, str | None] = {}
        self.buckets: set[str] = set()
        self.apagar_falha_com: str | None = None

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.buckets.add(Bucket)
        self.objetos[Key] = Body
        self.tipos[Key] = ContentType

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objetos:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objetos[Key])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        if self.apagar_falha_com:
            raise ClientError({"Error": {"Code": self.apagar_falha_com}}, "DeleteObject")
        self.objetos.pop(Key, None)


@pytest.fixture
def cliente() -> ClienteS3Falso:
    return ClienteS3Falso()


@pytest.fixture
def storage(cliente: ClienteS3Falso) -> S3Storage:
    return S3Storage(
        Settings(
            environment="dev",
            s3_bucket=BUCKET,
            s3_access_key=SecretStr(CREDENCIAL),
            s3_secret_key=SecretStr(CREDENCIAL),
        ),
        cliente=cliente,
    )


def test_salvar_guarda_no_bucket_com_o_tipo(storage: S3Storage, cliente: ClienteS3Falso) -> None:
    chave = storage.salvar(b"%PDF-1.4", mime_type="application/pdf")

    assert chave.startswith("anexos/")
    assert cliente.buckets == {BUCKET}
    assert cliente.objetos[chave] == b"%PDF-1.4"
    assert cliente.tipos[chave] == "application/pdf"


def test_salvar_nao_repete_chave(storage: S3Storage, cliente: ClienteS3Falso) -> None:
    primeira = storage.salvar(b"a", mime_type="application/pdf")
    segunda = storage.salvar(b"b", mime_type="application/pdf")

    assert primeira != segunda
    assert len(cliente.objetos) == 2


def test_ler_devolve_os_bytes(storage: S3Storage) -> None:
    chave = storage.salvar(b"conteudo", mime_type="image/png")

    assert storage.ler(chave) == b"conteudo"


def test_ler_chave_inexistente_vira_keyerror(storage: S3Storage) -> None:
    with pytest.raises(KeyError):
        storage.ler("anexos/nao-existe")


def test_apagar_remove_e_pode_repetir(storage: S3Storage, cliente: ClienteS3Falso) -> None:
    chave = storage.salvar(b"x", mime_type="application/pdf")

    storage.apagar(chave)
    storage.apagar(chave)  # a retenção pode rodar duas vezes

    assert chave not in cliente.objetos


def test_apagar_tolera_no_such_key(storage: S3Storage, cliente: ClienteS3Falso) -> None:
    cliente.apagar_falha_com = "NoSuchKey"

    storage.apagar("anexos/qualquer")  # não levanta


def test_apagar_propaga_erro_real(storage: S3Storage, cliente: ClienteS3Falso) -> None:
    cliente.apagar_falha_com = "AccessDenied"

    with pytest.raises(ClientError):
        storage.apagar("anexos/qualquer")
