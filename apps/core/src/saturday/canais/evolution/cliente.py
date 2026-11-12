"""Cliente HTTP da Evolution API (v2.3.7).

Só as rotas das decisões 0009 (envio de texto e download de mídia) e 0010
(gestão das instâncias pelo painel). Os erros
seguem a hierarquia do WhatsApp da Meta, porque a saída e a entrada já sabem
classificá-los; repetir é só do outbox (decisão 0001).
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from saturday.canais.whatsapp.cliente import (
    ErroIncerto,
    ErroPermanente,
    ErroTemporario,
    ErroWhatsApp,
)
from saturday.canais.whatsapp.telefone import normalizar_telefone
from saturday.settings import Settings

logger = logging.getLogger(__name__)

DDI_BRASIL = "55"
JID_TELEFONE = "@s.whatsapp.net"
INTEGRACAO = "WHATSAPP-BAILEYS"
EVENTOS_WEBHOOK = ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "CONNECTION_UPDATE"]
# `EventController.events` da tag 2.3.7: o `/webhook/set` recusa qualquer outro.
EVENTOS_DISPONIVEIS = (
    "APPLICATION_STARTUP",
    "QRCODE_UPDATED",
    "MESSAGES_SET",
    "MESSAGES_UPSERT",
    "MESSAGES_EDITED",
    "MESSAGES_UPDATE",
    "MESSAGES_DELETE",
    "SEND_MESSAGE",
    "SEND_MESSAGE_UPDATE",
    "CONTACTS_SET",
    "CONTACTS_UPSERT",
    "CONTACTS_UPDATE",
    "PRESENCE_UPDATE",
    "CHATS_SET",
    "CHATS_UPSERT",
    "CHATS_UPDATE",
    "CHATS_DELETE",
    "GROUPS_UPSERT",
    "GROUP_UPDATE",
    "GROUP_PARTICIPANTS_UPDATE",
    "CONNECTION_UPDATE",
    "LABELS_EDIT",
    "LABELS_ASSOCIATION",
    "CALL",
    "TYPEBOT_START",
    "TYPEBOT_CHANGE_STATUS",
    "REMOVE_INSTANCE",
    "LOGOUT_INSTANCE",
    "INSTANCE_CREATE",
    "INSTANCE_DELETE",
    "STATUS_INSTANCE",
)
# O que o Saturday aplica em `/settings/set`; a tela Canais compara com o atual.
CONFIGURACOES = {
    "rejectCall": False,
    "groupsIgnore": True,
    "alwaysOnline": False,
    "readMessages": True,
    "readStatus": False,
    "syncFullHistory": False,
}


@dataclass(frozen=True)
class EstadoInstancia:
    """O que o painel mostra de uma instância."""

    nome: str
    # `open`, `connecting`, `close` ou `refused`.
    estado: str
    # DDD + número, vazio enquanto não conectou.
    telefone: str


@dataclass(frozen=True)
class Qr:
    """QR para ler no celular, ou ``None`` com a instância já conectada."""

    imagem: str | None
    estado: str


def telefone_do_jid(jid: object) -> str:
    """`5511987654321@s.whatsapp.net` → `11987654321`; vazio se não for telefone."""

    if isinstance(jid, str) and jid.endswith(JID_TELEFONE):
        return normalizar_telefone(jid.removesuffix(JID_TELEFONE))
    return ""


def _numero_inexistente(corpo: dict[str, Any]) -> bool:
    """400 com `[{exists: false}]`: o número não tem WhatsApp."""

    resposta = corpo.get("response")
    mensagens = resposta.get("message") if isinstance(resposta, dict) else None
    return isinstance(mensagens, list) and any(
        isinstance(item, dict) and item.get("exists") is False for item in mensagens
    )


def classificar(status: int, corpo: dict[str, Any]) -> ErroWhatsApp:
    """O que a resposta de erro diz sobre tentar de novo.

    Outros 400 cobrem a instância desconectada ("Connection Closed"), que volta
    quando o número for reconectado; credencial e instância errada não voltam.
    """

    detalhe = f"evolution status={status}"
    if status >= 500:
        return ErroTemporario(detalhe)
    if status == 400 and not _numero_inexistente(corpo):
        return ErroTemporario(detalhe)
    return ErroPermanente(detalhe)


class EvolutionClient:
    """Envio e leitura de mídia. Não decide *o que* enviar."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._base = settings.evolution_url.rstrip("/")
        self._chave = settings.evolution_api_key.get_secret_value()
        self._limite_midia = settings.whatsapp_limite_midia_mb * 1024 * 1024
        self._webhook_url = settings.evolution_webhook_url
        self._webhook_token = settings.evolution_webhook_token.get_secret_value()

    def _objeto(
        self, metodo: str, rota: str, corpo: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        dados = self._pedir(metodo, rota, corpo)
        return dados if isinstance(dados, dict) else {}

    def _pedir(self, metodo: str, rota: str, corpo: dict[str, Any] | None = None) -> Any:
        try:
            resposta = self._http.request(
                metodo, f"{self._base}{rota}", json=corpo, headers={"apikey": self._chave}
            )
        except (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # A conexão caiu depois do envio: não dá para saber se saiu.
            raise ErroIncerto(f"leitura: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise ErroTemporario(f"rede: {type(exc).__name__}") from exc

        try:
            dados = resposta.json()
        except ValueError:
            dados = {}

        if resposta.status_code >= 400:
            erro = classificar(resposta.status_code, dados if isinstance(dados, dict) else {})
            logger.warning(
                "evolution_falhou rota=%s status=%s tipo=%s",
                rota.split("/")[1],
                resposta.status_code,
                type(erro).__name__,
            )
            raise erro
        # `connect` devolve erro com 200 e `error: true`.
        if isinstance(dados, dict) and dados.get("error") is True:
            raise ErroPermanente(f"evolution rota={rota.split('/')[1]} error=true")
        return dados

    def enviar_texto(self, instancia: str, numero: str, texto: str) -> str | None:
        """Devolve o id da mensagem (`key.id`), que os status usam."""

        dados = self._objeto(
            "POST",
            f"/message/sendText/{instancia}",
            {"number": f"{DDI_BRASIL}{numero}", "text": texto},
        )
        chave = dados.get("key")
        if isinstance(chave, dict) and isinstance(chave.get("id"), str):
            return str(chave["id"])
        return None

    def marcar_lida(self, instancia: str, wamid: str) -> None:
        """Nada a fazer: a instância lê sozinho (`readMessages=true`).

        A rota de leitura pede o JID do cliente, que a entrada não guarda; a
        configuração da instância faz o mesmo sem uma chamada a mais.
        """

    def baixar_midia(self, media_id: str, instancia: str) -> tuple[bytes, str]:
        """A Evolution acha a mídia pelo id na base dela e devolve em base64.

        Exige `DATABASE_SAVE_DATA_NEW_MESSAGE=true` na instância.
        """

        dados = self._objeto(
            "POST",
            f"/chat/getBase64FromMediaMessage/{instancia}",
            {"message": {"key": {"id": media_id}}},
        )
        codificado = dados.get("base64")
        if not isinstance(codificado, str) or not codificado:
            raise ErroPermanente("midia_sem_conteudo")
        # base64 ocupa 4/3 do arquivo: confere antes de decodificar.
        if len(codificado) * 3 // 4 > self._limite_midia:
            raise ErroPermanente("midia_acima_do_limite")
        try:
            conteudo = base64.b64decode(codificado, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ErroPermanente("midia_base64_invalido") from exc
        return conteudo, str(dados.get("mimetype") or "application/octet-stream")

    # ------------------------------------------------------- instâncias (0010)

    def _webhook(self, extras: list[str] | None = None) -> dict[str, Any]:
        """Webhook do Saturday; os eventos dele vão sempre, os extras por escolha."""

        escolhidos = set(extras or []) - set(EVENTOS_WEBHOOK)
        a_mais = [e for e in EVENTOS_DISPONIVEIS if e in escolhidos]
        return {
            "enabled": True,
            "url": self._webhook_url,
            "headers": {"x-webhook-token": self._webhook_token},
            "byEvents": False,
            "base64": False,
            "events": EVENTOS_WEBHOOK + a_mais,
        }

    @staticmethod
    def _qr(dados: dict[str, Any]) -> Qr:
        """QR do `connect`/`create`, ou o estado quando já conectou."""

        instancia = dados.get("instance")
        if isinstance(instancia, dict) and instancia.get("state"):
            return Qr(imagem=None, estado=str(instancia["state"]))
        qrcode = dados.get("qrcode") if "qrcode" in dados else dados
        imagem = qrcode.get("base64") if isinstance(qrcode, dict) else None
        return Qr(
            imagem=imagem if isinstance(imagem, str) and imagem else None, estado="connecting"
        )

    def criar_instancia(self, nome: str) -> Qr:
        """Cria já com webhook e leitura automática; devolve o primeiro QR."""

        dados = self._objeto(
            "POST",
            "/instance/create",
            {
                "instanceName": nome,
                "integration": INTEGRACAO,
                "qrcode": True,
                "readMessages": True,
                "groupsIgnore": True,
                "webhook": self._webhook(),
            },
        )
        return self._qr(dados)

    def aplicar_webhook(self, nome: str, extras: list[str] | None = None) -> None:
        """Grava na instância o webhook do Saturday (URL, token e eventos).

        Sem `extras`, mantém os eventos a mais que o gestor já tinha ligado.
        """

        if extras is None:
            atuais = self.webhook_atual(nome).get("events")
            extras = [str(e) for e in atuais] if isinstance(atuais, list) else []
        self._objeto("POST", f"/webhook/set/{nome}", {"webhook": self._webhook(extras)})

    def aplicar_configuracoes(self, nome: str, valores: dict[str, Any]) -> None:
        """Grava as configurações por cima das atuais.

        O `/settings/set` da 2.3.7 exige os seis booleanos e tira da memória da
        instância o que não vier (`msgCall`, `wavoipToken`): por isso parte do
        que está gravado, e esses campos nunca passam pelo painel.
        """

        atuais = self.configuracoes_atuais(nome)
        corpo = {**CONFIGURACOES, **atuais, **valores}
        corpo = {campo: valor for campo, valor in corpo.items() if valor is not None}
        self._objeto("POST", f"/settings/set/{nome}", corpo)

    def webhook_atual(self, nome: str) -> dict[str, Any]:
        """Webhook gravado na instância; vazio se não houver nenhum."""

        return self._objeto("GET", f"/webhook/find/{nome}")

    def configuracoes_atuais(self, nome: str) -> dict[str, Any]:
        return self._objeto("GET", f"/settings/find/{nome}")

    def conectar(self, nome: str) -> Qr:
        return self._qr(self._objeto("GET", f"/instance/connect/{nome}"))

    def listar(self) -> list[EstadoInstancia]:
        dados = self._pedir("GET", "/instance/fetchInstances")
        linhas = dados if isinstance(dados, list) else []
        return [
            EstadoInstancia(
                nome=str(linha.get("name") or ""),
                estado=str(linha.get("connectionStatus") or "close"),
                telefone=telefone_do_jid(linha.get("ownerJid")),
            )
            for linha in linhas
            if isinstance(linha, dict) and linha.get("name")
        ]

    def desconectar(self, nome: str) -> None:
        self._objeto("DELETE", f"/instance/logout/{nome}")

    def apagar(self, nome: str) -> None:
        self._objeto("DELETE", f"/instance/delete/{nome}")
