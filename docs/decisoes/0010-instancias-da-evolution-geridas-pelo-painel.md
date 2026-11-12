# 0010 — Instâncias da Evolution geridas pelo painel

- **Data:** 2026-11-12
- **Status:** aceita
- **Complementa:** [decisão 0009](0009-evolution-api-como-segundo-canal-whatsapp.md)
  (contrato permitido, regra 12)

## Contexto

Na 0009 as instâncias atendidas vinham de `SATURDAY_EVOLUTION_INSTANCIAS`, e
criar uma instância exigia abrir a Evolution com um domínio público temporário
para ler o QR. A equipe quer gerir os canais pelo próprio painel.

## Decisão

- Uma tela **Canais** no painel, só para gestor, com auditoria de cada ação:
  números da Meta só para leitura (de `SATURDAY_WHATSAPP_NUMEROS`) e instâncias
  da Evolution gerenciáveis: listar com estado e telefone, criar com QR,
  reconectar com QR (só fora do ar), desconectar e apagar.
- **A própria Evolution diz quais instâncias existem.** O Saturday atende toda
  instância da sua Evolution (que é só dele) e
  `SATURDAY_EVOLUTION_INSTANCIAS` deixa de existir.
- Criar e reconectar sempre reaplicam o webhook e `readMessages`; o nome da
  instância aceita letras minúsculas, números e hífen.
- Desconectar e apagar pedem confirmação, mostrando quantas conversas usaram a
  instância nos últimos 7 dias; as conversas ficam.
- **Telefone fixado:** a tabela `instancias` guarda só o nome e o telefone da
  primeira conexão. Se a instância voltar com outro telefone, o Saturday a
  desconecta na hora e abre um alerta: outro número exige apagar e criar outra
  instância. Apagar a instância apaga a linha.
- Queda definitiva da instância (`connection.update` com `close` ou
  `refused`) vira o alerta "instância desconectada".
- Contrato permitido, somado ao da 0009 e conferido no código da tag 2.3.7:
  `POST /instance/create`, `GET /instance/connect/{instancia}`,
  `GET /instance/connectionState/{instancia}`, `GET /instance/fetchInstances`,
  `DELETE /instance/logout/{instancia}`, `DELETE /instance/delete/{instancia}`,
  `POST /webhook/set/{instancia}`, `POST /settings/set/{instancia}` e o evento
  `connection.update`.

## Alternativas descartadas

- **Tabela no Saturday como fonte das instâncias atendidas.** Permitiria pausar
  um número sem desconectar, mas teria de ficar em sincronia com a Evolution.
- **Só o `ownerJid` da Evolution para o telefone.** O código não garante que ele
  sobreviva a logout ou a uma base recriada; o bloqueio falharia sem aviso.
- **Gerir pela própria interface da Evolution.** Exige expor a Evolution na
  internet e repetir a configuração do webhook a cada instância.
