"""Evidências da homologação da Granatech (fases 1 e 2) contra a api-dev.

O que a Granatech pede (``docs/granatech-homologacao/roteiro-homologacao.md``):

- Fase 1: 2 consultas (resposta direta e notificação do webhook) e 2 simulações
  (com e sem seguro);
- Fase 2: 2 contratações com sucesso (status recebido pelo webhook) e 1 erro de
  contratação.

Rode da raiz do repositório, com as variáveis no ambiente (nunca no código)::

    SATURDAY_GRANATECH_BASE_URL=https://api-dev.granatech.com.br \\
    SATURDAY_GRANATECH_CHAVE_API=... \\
    SATURDAY_URL_HOMOLOG=https://saturday-homolog.dynatech.systems \\
    SATURDAY_API_KEY=... \\
    uv run --project apps/core python scripts/homologacao_granatech.py

O webhook é recebido pelo Saturday (homolog); o script lê os eventos pela rota
``GET /eventos/granatech/{id}``. A saída fica em ``evidencias/granatech-<data>/``:
um JSON por passo e um ``RELATORIO.md``. A chave e o token nunca são gravados.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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


class ErroHomologacao(Exception):
    """Um passo obrigatório falhou; o relatório registra até onde chegou."""


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
    saturday: httpx.Client
    chave: str
    api_key: str
    saida: Path
    espera_webhook_s: float = 600
    intervalo_s: float = 10
    dormir: Callable[[float], None] = time.sleep
    evidencias: list[Evidencia] = field(default_factory=list)
    _token: str = ""
    _passo: int = 0

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
        self._passo += 1
        arquivo = f"{self._passo:02d}-{nome}.json"
        conteudo = {"horario": datetime.now(TZ).isoformat(), **conteudo}
        texto = json.dumps(conteudo, ensure_ascii=False, indent=2, default=str)
        # Nunca grava a chave nem o token, nem por acidente numa resposta.
        for segredo in (self.chave, self._token, self.api_key):
            if segredo:
                texto = texto.replace(segredo, "[removido]")
        (self.saida / arquivo).write_text(texto + "\n", encoding="utf-8")
        return arquivo

    def esperar_webhook(
        self, nome: str, id_externo: str, aceita: Callable[[dict[str, Any]], bool]
    ) -> tuple[bool, str]:
        """Consulta o Saturday até chegar um evento aceito para o id."""

        limite = time.monotonic() + self.espera_webhook_s
        eventos: list[dict[str, Any]] = []
        while True:
            resposta = self.saturday.get(
                f"/eventos/granatech/{id_externo}", headers={"X-API-Key": self.api_key}
            )
            if resposta.status_code == 200:
                eventos = list(resposta.json())
                if any(aceita(e.get("payload") or {}) for e in eventos):
                    break
            if time.monotonic() >= limite:
                arquivo = self._gravar(nome, {"id": id_externo, "eventos": eventos})
                return False, arquivo
            self.dormir(self.intervalo_s)
        return True, self._gravar(nome, {"id": id_externo, "eventos": eventos})

    def anotar(self, fase: str, item: str, arquivo: str, ok: bool, observacao: str = "") -> None:
        self.evidencias.append(Evidencia(fase, item, arquivo, ok, observacao))

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
        )
        status, dados, arquivo = self.chamar(
            f"proposta-contratacao{numero}", "POST", "/propostas", corpo=corpo
        )
        id_proposta = id_da_proposta(dados) if isinstance(dados, dict) else None
        if status >= 400 or not id_proposta:
            raise ErroHomologacao(f"contratação {numero}: HTTP {status}")
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

    # ------------------------------------------------------------ relatório

    def relatorio(self, erro: str | None = None) -> Path:
        linhas = [
            "# Evidências da homologação Granatech",
            "",
            f"Gerado em {datetime.now(TZ):%d/%m/%Y %H:%M} contra `{self.granatech.base_url}`.",
            "",
            "| Fase | Item | Arquivos | Situação | Observação |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in self.evidencias:
            situacao = "ok" if e.ok else "**falhou**"
            linhas.append(f"| {e.fase} | {e.item} | `{e.arquivo}` | {situacao} | {e.observacao} |")
        if erro:
            linhas += ["", f"**Parou antes do fim:** {erro}"]
        caminho = self.saida / "RELATORIO.md"
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return caminho

    def rodar(self) -> Path:
        try:
            self.fase1()
            self.fase2()
        except (ErroHomologacao, httpx.HTTPError) as exc:
            return self.relatorio(str(exc))
        return self.relatorio()


def main() -> int:
    ambiente = {
        nome: os.environ.get(nome, "").strip()
        for nome in (
            "SATURDAY_GRANATECH_BASE_URL",
            "SATURDAY_GRANATECH_CHAVE_API",
            "SATURDAY_URL_HOMOLOG",
            "SATURDAY_API_KEY",
        )
    }
    faltando = [nome for nome, valor in ambiente.items() if not valor]
    if faltando:
        print("Faltam variáveis: " + ", ".join(faltando), file=sys.stderr)
        return 2
    base = ambiente["SATURDAY_GRANATECH_BASE_URL"]
    if PRODUCAO in base:
        # Regra 11: homologação nunca roda contra a produção da Granatech.
        print("Recusado: a base aponta para a produção da Granatech.", file=sys.stderr)
        return 2
    saida = Path("evidencias") / f"granatech-{datetime.now(TZ):%Y%m%d-%H%M%S}"
    saida.mkdir(parents=True, exist_ok=True)
    with (
        httpx.Client(base_url=base, timeout=30) as granatech,
        httpx.Client(base_url=ambiente["SATURDAY_URL_HOMOLOG"], timeout=30) as saturday,
    ):
        relatorio = Homologacao(
            granatech=granatech,
            saturday=saturday,
            chave=ambiente["SATURDAY_GRANATECH_CHAVE_API"],
            api_key=ambiente["SATURDAY_API_KEY"],
            saida=saida,
        ).rodar()
    print(f"Relatório: {relatorio}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
