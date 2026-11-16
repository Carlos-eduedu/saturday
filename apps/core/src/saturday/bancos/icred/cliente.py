"""Cliente HTTP do motor de consultas do iCred (decisão 0027).

Fase 1: abrir consulta (`acao: consultar`) e ler o resultado. Nunca
`acao: gravar` nem `aceitar_mudanca`: os dois gravam o que o cliente não viu.

- A consulta é gravada como intenção antes do POST, com a chave que vai no
  `Idempotency-Key`. O POST não repete: se falhar, a conversa segue sem o iCred.
- GET repete uma vez em erro de rede ou 5xx.
- Cada chamada deixa em ``chamadas_externas`` só a rota-modelo.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.icred.normalizacao import Resultado, normalizar_consulta
from saturday.dados.modelos import ChamadaExterna, ConsultaIcred
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import registrar_chamada
from saturday.settings import GRANATECH_ESPERA_RETRY_S, ICRED_TIMEOUT_S, Settings

logger = logging.getLogger(__name__)

PARCEIRO = "icred"
INTENCAO = "intencao"
FALHOU = "falhou"
DESISTIDA = "desistida"
ABERTAS = ("na_fila", "processando")


class ErroIcred(Exception):
    """O motor recusou, não foi alcançado ou respondeu algo ilegível."""

    def __init__(self, mensagem: str, *, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


def gravar_resultado(sessao: Session, resultado: Resultado) -> ConsultaIcred | None:
    """Aplica o resultado na linha da consulta; devolve-a só se algo mudou.

    Consulta que já terminou (ou de que a conversa desistiu) não volta atrás:
    evento repetido ou atrasado é ignorado.
    """

    linha = sessao.scalar(
        select(ConsultaIcred)
        .where(ConsultaIcred.id_externo == resultado.id_externo)
        .with_for_update()
    )
    if linha is None or linha.estado not in ABERTAS or resultado.estado == linha.estado:
        return None
    linha.estado = resultado.estado
    linha.situacao = resultado.situacao
    # Pacote lido pela metade não é apresentado (decisão 0027): sem contratos,
    # a regra manda um atendente conferir.
    linha.contratos = resultado.contratos if resultado.completo else []
    linha.valido_ate = resultado.valido_ate
    return linha


class ClienteIcred:
    def __init__(
        self,
        http: httpx.Client,
        settings: Settings,
        fabrica: sessionmaker[Session],
        *,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._base = settings.icred_base_url.rstrip("/")
        self._chave = settings.icred_chave_api.get_secret_value()
        self._fabrica = fabrica
        self._dormir = dormir
        self.espera_min = settings.icred_espera_min

    def _enviar(
        self,
        metodo: str,
        rota_modelo: str,
        caminho: str,
        *,
        json: dict[str, Any] | None = None,
        idempotencia: str | None = None,
        conversa_id: Any = None,
    ) -> Any:
        cabecalhos = {"X-API-Key": self._chave}
        if idempotencia:
            cabecalhos["Idempotency-Key"] = idempotencia
        inicio = time.monotonic()
        situacao: int | None = None
        try:
            resposta = self._http.request(
                metodo,
                f"{self._base}{caminho}",
                json=json,
                headers=cabecalhos,
                timeout=ICRED_TIMEOUT_S,
            )
            situacao = resposta.status_code
        except httpx.HTTPError as exc:
            raise ErroIcred(f"rede: {type(exc).__name__}") from exc
        finally:
            self._registrar(metodo, rota_modelo, situacao, inicio, conversa_id)

        if situacao >= 400:
            raise ErroIcred(f"{metodo} {rota_modelo}: {situacao}", status=situacao)
        try:
            return resposta.json()
        except ValueError as exc:
            raise ErroIcred(f"{metodo} {rota_modelo}: resposta não é JSON") from exc

    def _registrar(
        self,
        metodo: str,
        rota_modelo: str,
        situacao: int | None,
        inicio: float,
        conversa_id: Any,
    ) -> None:
        duracao_ms = (time.monotonic() - inicio) * 1000
        registrar_chamada(PARCEIRO, duracao_ms, status=situacao if situacao else "erro")
        logger.info(
            "icred_chamada metodo=%s rota=%s status=%s ms=%.0f",
            metodo,
            rota_modelo,
            situacao,
            duracao_ms,
        )
        try:
            with abrir_sessao(self._fabrica) as sessao:
                sessao.add(
                    ChamadaExterna(
                        conversa_id=conversa_id,
                        servico=PARCEIRO,
                        metodo=metodo,
                        rota=rota_modelo,
                        status_http=situacao,
                        duracao_ms=int(duracao_ms),
                    )
                )
        except Exception:  # noqa: BLE001 - o registro não pode derrubar a chamada
            logger.exception("icred_registro_falhou rota=%s", rota_modelo)

    def abrir_consulta(self, *, cpf: str, telefone: str, nome: str | None, conversa_id: Any) -> int:
        """Abre a consulta e devolve o id local. Só depois do SIM gravado (regra 3)."""

        chave = str(uuid.uuid4())
        with abrir_sessao(self._fabrica) as sessao:
            linha = ConsultaIcred(chave=chave, cpf=cpf, conversa_id=conversa_id, estado=INTENCAO)
            sessao.add(linha)
            sessao.flush()
            id_local = linha.id

        corpo: dict[str, Any] = {
            "cpf": cpf,
            "telefone": telefone,
            "lgpd_ok": True,
            "acao": "consultar",
            "referencia": str(conversa_id) if conversa_id else None,
        }
        if nome:
            corpo["nome"] = nome
        try:
            resposta = self._enviar(
                "POST",
                "/consultas",
                "/consultas",
                json=corpo,
                idempotencia=chave,
                conversa_id=conversa_id,
            )
            id_externo, estado = resposta["id"], resposta["estado"]
            if not isinstance(id_externo, str) or not isinstance(estado, str):
                raise ErroIcred("POST /consultas: resposta sem id ou estado")
        except (ErroIcred, KeyError, TypeError) as exc:
            with abrir_sessao(self._fabrica) as sessao:
                sessao.get_one(ConsultaIcred, id_local).estado = FALHOU
            if isinstance(exc, ErroIcred):
                raise
            raise ErroIcred("POST /consultas: resposta sem id ou estado") from exc

        with abrir_sessao(self._fabrica) as sessao:
            nova = sessao.get_one(ConsultaIcred, id_local)
            # O motor devolve a consulta já aberta do mesmo CPF (`ja_existia`).
            antiga = sessao.scalar(
                select(ConsultaIcred).where(ConsultaIcred.id_externo == id_externo)
            )
            if antiga is None:
                nova.id_externo = id_externo
                nova.estado = estado
                return id_local
            if antiga.conversa_id == conversa_id and antiga.estado in ABERTAS:
                sessao.delete(nova)
                return antiga.id
            # A consulta aberta é de outra conversa (ou já foi abandonada): o
            # resultado dela não chegaria a esta, que segue sem o iCred.
            nova.estado = FALHOU
        raise ErroIcred("POST /consultas: o CPF já tem consulta aberta em outra conversa")

    def ler(self, id_externo: str, *, conversa_id: Any = None) -> Resultado:
        rota = "/consultas/{cid}"
        try:
            dados = self._enviar("GET", rota, f"/consultas/{id_externo}", conversa_id=conversa_id)
        except ErroIcred as erro:
            if erro.status is not None and erro.status < 500:
                raise
            self._dormir(GRANATECH_ESPERA_RETRY_S)
            dados = self._enviar("GET", rota, f"/consultas/{id_externo}", conversa_id=conversa_id)
        try:
            return normalizar_consulta(dados)
        except (ValueError, AttributeError) as exc:
            raise ErroIcred(f"GET {rota}: {exc}") from exc
