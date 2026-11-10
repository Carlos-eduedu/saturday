"""Avaliação manual do Jev com frases realistas (usa a API de verdade)."""

from __future__ import annotations

import csv
import os
from collections import Counter
from pathlib import Path

import httpx
import pytest

from saturday.services.jev import JevClient
from saturday.settings import JEV_INTENT_THRESHOLD, Settings

FRASES = Path(__file__).parent / "dados" / "jev_frases.csv"


@pytest.mark.jev
@pytest.mark.skipif(
    not os.getenv("SATURDAY_OPENROUTER_API_KEY"),
    reason="SATURDAY_OPENROUTER_API_KEY não definida",
)
def test_avaliacao_jev_imprime_acertos_por_rotulo():
    settings = Settings(
        environment="pytest",
        openrouter_api_key=os.environ["SATURDAY_OPENROUTER_API_KEY"],
        jev_model=os.getenv("SATURDAY_JEV_MODEL", "typesafe/jev-1.13"),
    )
    linhas = list(csv.DictReader(FRASES.read_text(encoding="utf-8").splitlines()))
    assert len(linhas) >= 30

    acertos_intent: Counter[str] = Counter()
    total_intent: Counter[str] = Counter()
    acertos_oferta: Counter[str] = Counter()
    total_oferta: Counter[str] = Counter()
    erros: list[str] = []

    with httpx.Client(timeout=30) as http:
        client = JevClient(http, settings)
        for linha in linhas:
            oferta = linha["oferta_pendente"].strip().lower() == "true"
            resultado = client.classify(linha["frase"], oferta_pendente=oferta)

            esperado = linha["intent"]
            total_intent[esperado] += 1
            if resultado.intent == esperado:
                acertos_intent[esperado] += 1
            else:
                erros.append(
                    f"intent: {linha['frase']!r} esperado={esperado} "
                    f"obtido={resultado.intent} "
                    f"p(esperado)={resultado.probabilidade('intent', esperado):.2f} "
                    f"p(obtido)={resultado.probabilidade('intent', resultado.intent):.2f}"
                )

            esperado_oferta = linha["resposta_oferta"].strip()
            if oferta and esperado_oferta:
                total_oferta[esperado_oferta] += 1
                if resultado.resposta_oferta == esperado_oferta:
                    acertos_oferta[esperado_oferta] += 1
                else:
                    erros.append(
                        f"oferta: {linha['frase']!r} esperado={esperado_oferta} "
                        f"obtido={resultado.resposta_oferta} "
                        "p(esperado)="
                        f"{resultado.probabilidade('resposta_oferta', esperado_oferta):.2f}"
                    )

    print(f"\nAcerto por rótulo de intent (limite atual {JEV_INTENT_THRESHOLD:.2f}):")
    for rotulo in sorted(total_intent):
        print(
            f"  {rotulo}: {acertos_intent[rotulo]}/{total_intent[rotulo]} "
            f"({acertos_intent[rotulo] / total_intent[rotulo]:.0%})"
        )
    print("Acerto por rótulo de resposta_oferta:")
    for rotulo in sorted(total_oferta):
        print(
            f"  {rotulo}: {acertos_oferta[rotulo]}/{total_oferta[rotulo]} "
            f"({acertos_oferta[rotulo] / total_oferta[rotulo]:.0%})"
        )
    print("Erros (frase, esperado, obtido, probabilidades):")
    for erro in erros:
        print("  " + erro)
