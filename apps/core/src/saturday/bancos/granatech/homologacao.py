"""Evidências da homologação da Granatech (decisão 0014).

O que a Granatech pede (``docs/granatech-homologacao/roteiro-homologacao.md``):

- Fase 1: 2 consultas (resposta direta e notificação do webhook) e 2 simulações
  (com e sem seguro);
- Fase 2: 2 contratações com sucesso (status recebido pelo webhook) e 1 erro de
  contratação.

Uma rodada roda uma fase, no worker (``jobs/homologacao.py``), pedida pelo
gestor na aba Granatech. Fala com a Granatech por um ``httpx.Client`` próprio,
sem o ``ClienteGranatech``: a evidência é a requisição e a resposta cruas. Cada
passo vai para ``ao_mudar``, que o grava na rodada; a chave e o token nunca
são gravados.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from saturday.bancos.granatech.normalizacao import (
    DetalheConsulta,
    Simulacao,
    id_da_proposta,
    montar_corpo_proposta,
    montar_dados_tomador,
    normalizar_detalhe,
    normalizar_simulacao,
)
from saturday.settings import Settings

CONSIGNADO = "/api-consignado/v1"
PRODUCAO = "api.granatech.com.br"
CPF_PADRAO = "00189004967"
NOME = "Cliente de Teste"
TELEFONE = "11999999999"
EMAIL = "cliente@exemplo.com"
CONTA_TESTE = {
    "banco_codigo": "001",
    "agencia": "0001",
    "digito_agencia": "",
    "numero_conta": "12345",
    "digito_conta": "6",
    "tipo_conta": "conta_corrente",
}
ID_INEXISTENTE = "00000000-0000-0000-0000-000000000000"
TZ = ZoneInfo("America/Sao_Paulo")
# Consultas que cada fase abre, para a confirmação do painel.
CONSULTAS_POR_FASE = {1: 1, 2: 2}
# Os itens do roteiro, na ordem em que cada fase os anota; o painel mostra o
# progresso da rodada contra esta lista.
ITENS_POR_FASE = {
    1: [
        "Consulta via resposta direta",
        "Consulta via notificação do webhook",
        "Simulação com seguro",
        "Simulação sem seguro",
    ],
    2: ["Contratação 1 com sucesso", "Contratação 2 com sucesso", "Erro de contratação"],
}


def disponivel(settings: Settings) -> bool:
    """Regra 11: nunca em produção, nem apontando para a Granatech de produção."""

    return settings.environment != "prod" and PRODUCAO not in settings.granatech_base_url


class ErroHomologacao(Exception):
    """Um passo obrigatório falhou; a rodada registra até onde chegou."""


@dataclass
class Evidencia:
    fase: str
    item: str
    arquivo: str
    ok: bool
    observacao: str = ""


@dataclass
class Homologacao:
    granatech: httpx.Client
    chave: str
    ler_eventos: Callable[[str], list[dict[str, Any]]]
    ao_mudar: Callable[[Homologacao], None] = lambda _h: None
    espera_webhook_s: float = 600
    intervalo_s: float = 10
    dormir: Callable[[float], None] = time.sleep
    passos: list[dict[str, Any]] = field(default_factory=list)
    evidencias: list[Evidencia] = field(default_factory=list)
    ids_externos: list[str] = field(default_factory=list)
    _token: str = ""

    # ------------------------------------------------------------ HTTP

    def _login(self) -> None:
        resposta = self.granatech.post("/api/v1/auth/login", json={"chave_api": self.chave})
        if resposta.status_code >= 400:
            raise ErroHomologacao(f"login recusado: HTTP {resposta.status_code}")
        self._token = str(resposta.json().get("token") or "")
        if not self._token:
            raise ErroHomologacao("login sem token")

    def chamar(
        self,
        nome: str,
        metodo: str,
        rota: str,
        *,
        params: dict[str, Any] | None = None,
        corpo: dict[str, Any] | None = None,
    ) -> tuple[int, Any, str]:
        """Uma chamada à Granatech, gravada como evidência. Devolve status, JSON e arquivo."""

        if not self._token:
            self._login()
        resposta = self.granatech.request(
            metodo,
            f"{CONSIGNADO}{rota}",
            params=params,
            json=corpo,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            dados: Any = resposta.json()
        except ValueError:
            dados = resposta.text
        arquivo = self._gravar(
            nome,
            {
                "metodo": metodo,
                "rota": f"{CONSIGNADO}{rota}",
                "parametros": params,
                "corpo": corpo,
                "status_http": resposta.status_code,
                "resposta": dados,
            },
        )
        return resposta.status_code, dados, arquivo

    def _gravar(self, nome: str, conteudo: dict[str, Any]) -> str:
        arquivo = f"{len(self.passos) + 1:02d}-{nome}.json"
        conteudo = {"arquivo": arquivo, "horario": datetime.now(TZ).isoformat(), **conteudo}
        texto = json.dumps(conteudo, ensure_ascii=False, default=str)
        # Nunca grava a chave nem o token, nem por acidente numa resposta.
        for segredo in (self.chave, self._token):
            if segredo:
                texto = texto.replace(segredo, "[removido]")
        self.passos.append(json.loads(texto))
        self.ao_mudar(self)
        return arquivo

    def esperar_webhook(
        self, nome: str, id_externo: str, aceita: Callable[[dict[str, Any]], bool]
    ) -> tuple[bool, str]:
        """Lê os eventos recebidos até chegar um aceito para o id."""

        limite = time.monotonic() + self.espera_webhook_s
        while True:
            eventos = self.ler_eventos(id_externo)
            if any(aceita(e.get("payload") or {}) for e in eventos):
                return True, self._gravar(nome, {"id": id_externo, "eventos": eventos})
            if time.monotonic() >= limite:
                return False, self._gravar(nome, {"id": id_externo, "eventos": eventos})
            self.dormir(self.intervalo_s)

    def registrar_id(self, id_externo: str) -> None:
        self.ids_externos.append(id_externo)
        self.ao_mudar(self)

    def anotar(self, fase: str, item: str, arquivo: str, ok: bool, observacao: str = "") -> None:
        self.evidencias.append(Evidencia(fase, item, arquivo, ok, observacao))
        self.ao_mudar(self)

    # ------------------------------------------------------------ etapas comuns

    def cpf_de_teste(self) -> str:
        status, dados, _ = self.chamar(
            "cpf-de-teste", "GET", "/tools/cpf", params={"digitos": "001"}
        )
        achado = re.search(r"\b\d{11}\b", json.dumps(dados)) if status < 400 else None
        return achado.group(0) if achado else CPF_PADRAO

    def consulta_pronta(self, sufixo: str) -> tuple[str, DetalheConsulta, str, str]:
        """Abre a consulta, assina o termo e espera o detalhe com margens."""

        cpf = self.cpf_de_teste()
        status, dados, direta = self.chamar(
            f"consulta-{sufixo}",
            "GET",
            "/consulta-saldo",
            params={"cpf": cpf, "nome": NOME, "telefone": TELEFONE},
        )
        id_consulta = str(dados.get("id") or "") if isinstance(dados, dict) else ""
        if status >= 400 or not id_consulta:
            raise ErroHomologacao(f"consulta {sufixo}: HTTP {status}")
        self.registrar_id(id_consulta)
        self.chamar(
            f"termo-{sufixo}",
            "POST",
            "/termo-consentimento",
            corpo={
                "cpf": cpf,
                "email": EMAIL,
                "nome": NOME,
                "telefone": TELEFONE,
                "id_consulta": id_consulta,
            },
        )
        limite = time.monotonic() + self.espera_webhook_s
        while True:
            status, dados, _ = self.chamar(
                f"detalhe-{sufixo}", "GET", f"/consulta-saldo/{id_consulta}"
            )
            detalhe = normalizar_detalhe(dados) if isinstance(dados, dict) else None
            if detalhe is not None and detalhe.vinculos:
                return id_consulta, detalhe, cpf, direta
            if time.monotonic() >= limite:
                raise ErroHomologacao(f"consulta {sufixo} sem margens depois da espera")
            self.dormir(self.intervalo_s)

    def simular(
        self, nome: str, detalhe: DetalheConsulta, *, seguro: bool
    ) -> tuple[Simulacao, str, Any]:
        vinculo = detalhe.vinculos[0]
        produto = max(vinculo.produtos, key=lambda p: max(p.parcelas or (0,)))
        idade = detalhe.pessoa.idade if detalhe.pessoa and detalhe.pessoa.idade else 36
        params: dict[str, Any] = {
            "id_margem": vinculo.id_margem,
            "numero_parcelas": max(produto.parcelas),
            "idade": idade,
            "valor_parcela": "100",
            "seguro": "true" if seguro else "false",
        }
        if seguro and produto.id_empresa_seguro:
            params["id_empresa_seguro"] = produto.id_empresa_seguro
        if seguro and produto.id_produto_seguro:
            params["id_produto_seguro"] = produto.id_produto_seguro
        status, dados, arquivo = self.chamar(nome, "GET", f"/simulacao/{produto.id}", params=params)
        if status >= 400 or not isinstance(dados, dict):
            raise ErroHomologacao(f"{nome}: HTTP {status}")
        return normalizar_simulacao(dados), arquivo, produto

    # ------------------------------------------------------------ fases

    def fase1(self) -> None:
        id_consulta, detalhe, _, direta = self.consulta_pronta("fase1")
        self.anotar("Fase 1", "Consulta via resposta direta", direta, True)
        chegou, arquivo = self.esperar_webhook("webhook-consulta", id_consulta, lambda _p: True)
        self.anotar("Fase 1", "Consulta via notificação do webhook", arquivo, chegou)

        _, arquivo, _ = self.simular("simulacao-com-seguro", detalhe, seguro=True)
        self.anotar("Fase 1", "Simulação com seguro", arquivo, True)
        sem, arquivo, _ = self.simular("simulacao-sem-seguro", detalhe, seguro=False)
        observacao = (
            "pedida com seguro=false, mas a API devolveu o bloco com seguro"
            if sem.seguro_aplicado
            else ""
        )
        self.anotar("Fase 1", "Simulação sem seguro", arquivo, True, observacao)

    def contratar(self, numero: int) -> None:
        id_consulta, detalhe, cpf, _ = self.consulta_pronta(f"contratacao{numero}")
        simulacao, _, produto = self.simular(f"simulacao-contratacao{numero}", detalhe, seguro=True)
        vinculo = detalhe.vinculos[0]
        corpo = montar_corpo_proposta(
            id_consulta=id_consulta,
            vinculo=vinculo,
            produto=produto,
            simulacao=simulacao,
            tipo_empregador=1,
            # Teste na api-dev: sem o bloco de seguro, como o exemplo ativo da
            # collection; com ele, o `id_externo` da simulação dá 400.
            bloco_seguro=False,
        )
        status, dados, arquivo = self.chamar(
            f"proposta-contratacao{numero}", "POST", "/propostas", corpo=corpo
        )
        id_proposta = id_da_proposta(dados) if isinstance(dados, dict) else None
        if status >= 400 or not id_proposta:
            raise ErroHomologacao(f"contratação {numero}: HTTP {status}")
        self.registrar_id(id_proposta)
        if detalhe.pessoa is not None:
            self.chamar(
                f"dados-tomador-contratacao{numero}",
                "POST",
                f"/propostas/{id_proposta}/dados-tomador",
                corpo=montar_dados_tomador(
                    pessoa=detalhe.pessoa,
                    cpf=cpf,
                    nome=NOME,
                    estado_civil="SOLTEIRO",
                    celular=TELEFONE,
                    conta=CONTA_TESTE,
                ),
            )
        chegou, webhook = self.esperar_webhook(
            f"webhook-contratacao{numero}", id_proposta, lambda _p: True
        )
        self.anotar(
            "Fase 2",
            f"Contratação {numero} com sucesso",
            f"{arquivo}, {webhook}",
            chegou,
            "" if chegou else "o status não chegou pelo webhook no tempo de espera",
        )

    def fase2(self) -> None:
        self.contratar(1)
        self.contratar(2)
        corpo = {
            "id_consulta": ID_INEXISTENTE,
            "id_produto": "inexistente",
            "id_margem": "inexistente",
            "informacoesFinanceira": [{"valor_parcela": 100, "numero_parcelas": 36}],
        }
        status, _, arquivo = self.chamar("proposta-com-erro", "POST", "/propostas", corpo=corpo)
        self.anotar(
            "Fase 2",
            "Erro de contratação",
            arquivo,
            400 <= status < 500,
            f"HTTP {status}",
        )

    # ------------------------------------------------------------ rodada

    def itens(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self.evidencias]

    def rodar(self, fase: int) -> str | None:
        """Roda uma fase; devolve o erro que a parou, ou None."""

        try:
            if fase == 1:
                self.fase1()
            else:
                self.fase2()
        except (ErroHomologacao, httpx.HTTPError) as exc:
            return str(exc) or type(exc).__name__
        return None


def relatorio(
    itens: list[dict[str, Any]], base_url: str, gerado_em: datetime, erro: str | None
) -> str:
    """O ``RELATORIO.md`` que acompanha os JSON no ``.zip``."""

    linhas = [
        "# Evidências da homologação Granatech",
        "",
        f"Gerado em {gerado_em.astimezone(TZ):%d/%m/%Y %H:%M} contra `{base_url}`.",
        "",
        "| Fase | Item | Arquivos | Situação | Observação |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in itens:
        situacao = "ok" if e["ok"] else "**falhou**"
        linhas.append(
            f"| {e['fase']} | {e['item']} | `{e['arquivo']}` | {situacao} | {e['observacao']} |"
        )
    if erro:
        linhas += ["", f"**Parou antes do fim:** {erro}"]
    return "\n".join(linhas) + "\n"
