"""Storage de anexos em S3 (MinIO interno ou bucket externo)."""

from __future__ import annotations

import uuid
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from saturday.settings import Settings


class S3Storage:
    """Grava o anexo no bucket e devolve a chave; o estado guarda só a chave."""

    def __init__(self, settings: Settings, *, cliente: Any = None) -> None:
        self.bucket = settings.s3_bucket
        self._cliente = cliente or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_regiao,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def salvar(self, dados: bytes, *, mime_type: str, chave: str | None = None) -> str:
        destino = chave or f"anexos/{uuid.uuid4().hex}"
        self._cliente.put_object(
            Bucket=self.bucket,
            Key=destino,
            Body=dados,
            ContentType=mime_type,
        )
        return destino

    def ler(self, chave: str) -> bytes:
        try:
            resposta = self._cliente.get_object(Bucket=self.bucket, Key=chave)
        except (ClientError, BotoCoreError) as exc:
            raise KeyError(f"anexo {chave} indisponível no storage") from exc
        return bytes(resposta["Body"].read())

    def apagar(self, chave: str) -> None:
        """Apagar duas vezes não é erro: a retenção pode rodar em paralelo."""

        try:
            self._cliente.delete_object(Bucket=self.bucket, Key=chave)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404"}:
                raise
