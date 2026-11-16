# 0025 — Aba Granatech: uma ação do gestor por vez em cada item

- **Data:** 2026-11-16
- **Status:** aceita
- **Estende:** [0013](0013-acoes-do-painel-na-granatech-por-turno-de-sistema.md)

## Contexto

As cinco ações do gestor (reconciliar, reenviar o link, cancelar, corrigir a
conta e atualizar o detalhe) conferiam se a ação valia e só depois agiam, sem
trava entre uma coisa e outra. Duas requisições na mesma proposta passavam
juntas pela conferência: dois gestores, ou um gestor em duas abas, mandavam ao
cliente dois links de biometria. A tela só barra o segundo clique na mesma aba.

## Decisão

- **Trava por item.** Cada ação tenta a trava `granatech:proposta:<id>` (ou
  `granatech:consulta:<id>`) antes de conferir e a segura até a resposta sair.
  Quem chega com outra ação em andamento no mesmo item recebe **409** na hora:
  não espera na fila. É `pg_try_advisory_xact_lock` (`dados/trava.py`,
  `tentar_trava`).
- **Não é a trava da conversa.** O turno de sistema que a ação dispara pega a
  trava da conversa em outra sessão; a ação ficaria esperando por si mesma.
- **Prazo do reenvio.** Depois de um reenvio, o link da mesma proposta só sai
  de novo passado **1 minuto** (`PRAZO_REENVIO`), para qualquer gestor. A
  conferência lê a auditoria `granatech_reenviar_link` da proposta, sob a
  trava. A recusa é um 409 que diz quanto falta.

## Consequências

- A auditoria é gravada antes do envio: se o reenvio falhar depois de
  auditado, o gestor espera o minuto para tentar de novo.
- Cada ação em andamento segura uma conexão do banco a mais, parada, pelo
  tempo que a Granatech leva para responder.
- As outras quatro ações não têm prazo: passada a primeira, a segunda é
  conferida com o estado novo do item, como antes.

## Alternativas descartadas

- **Esperar a trava em vez de recusar.** A segunda ação rodaria logo depois da
  primeira, e o link sairia em dobro do mesmo jeito.
- **Só a trava, sem prazo.** Não cobre o segundo clique dois segundos depois,
  quando a primeira ação já terminou.
