---
name: Saturday · Painel
description: Painel da equipe para supervisionar a IA de atendimento e intervir na hora certa.
colors:
  cobalto-de-acao: "#1f2de6"
  cobalto-de-acao-suave: "#e4e6fc"
  texto-sobre-cobalto: "#ffffff"
  verde-ia: "#1e6b40"
  ambar-de-atencao: "#9a4a00"
  vermelho-de-erro: "#b3261e"
  tinta: "#0b0c0e"
  grafite-suave: "#5d6470"
  cinza-frio-fundo: "#eef0f3"
  superficie: "#ffffff"
  superficie-recuada: "#e2e5ea"
  borda: "#d3d7de"
typography:
  display:
    fontFamily: "Red Hat Display Variable, system-ui, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Red Hat Display Variable, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Red Hat Text Variable, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Red Hat Text Variable, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 500
    lineHeight: 1.4
  data:
    fontFamily: "IBM Plex Mono, ui-monospace, Menlo, monospace"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  alvo: "44px"
components:
  button-primary:
    backgroundColor: "{colors.cobalto-de-acao}"
    textColor: "{colors.texto-sobre-cobalto}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
    height: "{spacing.alvo}"
  button-secondary:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
    height: "{spacing.alvo}"
  button-danger:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.vermelho-de-erro}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
    height: "{spacing.alvo}"
  input:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
    height: "{spacing.alvo}"
  card:
    backgroundColor: "{colors.superficie}"
    rounded: "{rounded.lg}"
    padding: "1.25rem"
  chip-estado:
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
  nav-item-ativo:
    backgroundColor: "{colors.cobalto-de-acao-suave}"
    textColor: "{colors.cobalto-de-acao}"
    rounded: "{rounded.md}"
    height: "{spacing.alvo}"
---

# Design System: Saturday · Painel

## Overview

**Creative North Star: "A Torre de Controle"**

O painel é uma torre de controle sobre a IA que atende os clientes da MEX: tudo fica em vista, e só o que pede ação se destaca. A base é calma (cinza frio, branco, texto quase preto); a cor aparece para dizer algo, nunca para enfeitar. A atenção da equipe é o recurso escasso, e o sistema existe para gastá-la só onde importa: a conversa sem resposta, o handoff, a IA falando de valores, o envio que falhou.

A densidade é de ferramenta de turno, usada no desktop e no celular com o mesmo peso. Componentes são precisos e calmos: pouco ornamento, estados claros, resposta discreta ao ponteiro. Dados (telefones, horas, IDs, custos) vão em fonte mono e números tabulares; o resto é texto humanista. Há tema claro e escuro, decididos pelo sistema.

**Key Characteristics:**
- Base neutra e calma; cor só com significado (ação, IA, atenção, erro).
- Quem fala na conversa muda a cor: IA em verde, equipe em cobalto, sistema sem balão.
- Atenção sempre com texto, nunca só com cor.
- Alvos de toque de 44 px e foco visível em tudo.
- Movimento curto (120–150 ms) e desligado com redução de movimento.

## Colors

Cinza frio com um único cobalto de ação, mais três cores de estado com significado fixo.

### Primary
- **Cobalto de Ação** (#1f2de6): botão principal, links, aba e página atuais, foco, autor "Equipe". No escuro vira #7aa7ff para manter contraste AA.
- **Cobalto de Ação Suave** (#e4e6fc): fundo do item de navegação ativo, balão da equipe e selo "Assumida". No escuro, #16284a.

### Secondary
- **Verde IA** (#1e6b40): tudo que é da IA: autor "IA", balão da IA (tingido a 10%), selo "IA", instância conectada. No escuro, #6fcf97.
- **Âmbar de Atenção** (#9a4a00): o que pede a equipe: rótulo "pede atenção", faixa do handoff, selo "Handoff", cota acima de 80%, selo de alertas. No escuro, #f2a65a.

### Tertiary
- **Vermelho de Erro** (#b3261e): erro, envio que falhou, ação destrutiva ("Apagar"), instância desconectada. No escuro, #ff8a80.

### Neutral
- **Tinta** (#0b0c0e): texto principal.
- **Grafite Suave** (#5d6470): texto secundário, rótulos, horas; 5,2:1 sobre o fundo.
- **Cinza Frio de Fundo** (#eef0f3): fundo da página.
- **Superfície** (#ffffff): cartões, linhas, campos.
- **Superfície Recuada** (#e2e5ea): gaveta do arrastar, hover de linha.
- **Borda** (#d3d7de): contorno de cartões e campos, divisórias.

### Named Rules
**The Cor Com Motivo Rule.** Cada cor de estado tem um significado só (verde = IA, âmbar = atenção, vermelho = erro, cobalto = ação ou equipe). Não use essas cores para decorar.

**The Nunca Só Cor Rule.** Todo estado colorido vem com texto ("Sem resposta", "desconectada", "falhou"). Contraste AA nos dois temas.

## Typography

**Display Font:** Red Hat Display Variable (com system-ui)
**Body Font:** Red Hat Text Variable (com system-ui)
**Label/Mono Font:** IBM Plex Mono

**Character:** Red Hat é humanista e firme, legível em texto pequeno; Plex Mono marca o que é dado e não prosa.

### Hierarchy
- **Display** (500, 1.6rem, 1.2): título de cada tela ("Conversas", "Alertas", "Operação") com a contagem ao lado em grafite.
- **Headline** (500, 1.25rem, 1.2): títulos de seção e de cartão ("Ficha", "Por dia"). O telefone no topo da conversa é maior (1.45rem, mono), porque é o título dela.
- **Body** (400, 15px, 1.5): falas, prévias, textos de tela vazia.
- **Label** (500, 0.85rem): rótulos de campo, selos, metadados.
- **Data** (400, 0.85rem, mono, números tabulares): telefones mascarados, horas, custos, tokens, IDs.

### Named Rules
**The Mono É Dado Rule.** Fonte mono só para dados e medidas (telefone, hora, custo, ID, contagem), nunca como enfeite "técnico". `<small>` é texto; o dado vai em `<time>`, `<code>` ou na classe `.dado` (mono, 0.875rem, números tabulares).

## Layout

Coluna única centrada com largura máxima de 96rem e respiro lateral de 1–2rem (clamp). O topo fixo tem 60px; no desktop (a partir de 1024px) leva a navegação (Conversas, Alertas com a contagem dos abertos, Bancos, Agente, Canais, Membros, Operação), a cota e a conta (perfil e Sair); abaixo disso, um botão Menu abre o painel lateral. Conversas tem layout de chat a partir de 1024px: lista de 21rem à esquerda, com rolagem própria e a conversa aberta marcada em Cobalto Suave, e a conversa à direita; a Ficha ganha coluna de 20rem a partir de 1280px e, entre 1024 e 1279px, vira aba ao lado de Mensagens. Abaixo de 1024px, lista e conversa são telas separadas. A lista se adapta pela própria largura (container query), não pela da janela. Linhas e cartões se agrupam com gap de 0.5rem; seções com 1.25–1.5rem. Tabelas viram cartões com rótulos abaixo de 768px.

## Elevation & Depth

Híbrido: superfícies brancas sobre o fundo cinza com sombra quase imperceptível em repouso; a sombra cresce só como resposta ao ponteiro.

### Shadow Vocabulary
- **Repouso** (`box-shadow: 0 1px 2px rgb(11 12 14 / 6%), 0 4px 12px rgb(11 12 14 / 4%)`): cartões, linhas da lista.
- **Elevada** (`box-shadow: 0 2px 4px rgb(11 12 14 / 8%), 0 10px 24px rgb(11 12 14 / 8%)`): o aviso flutuante de "Desfazer" e o que mais flutuar sobre a página.

### Named Rules
**The Sombra É Resposta Rule.** Em repouso, a profundidade é quase plana; sombra maior só em hover ou em algo que flutua sobre a página.

## Shapes

Cantos suaves em três passos: 6px para foco e detalhes, 10px para botões e campos, 14px para cartões e painéis. A linha da lista de conversas é a exceção: 18px, com 6px entre as linhas (modelo AnimatedList). Selos e chips são pílulas. Bordas de 1px na cor Borda; nenhuma barra lateral colorida de mais de 1px.

## Components

### Buttons
- **Shape:** cantos de 10px, altura mínima de 44px.
- **Principal:** fundo Cobalto de Ação, texto branco; um por área (Enviar, Entrar, Assumir, Criar).
- **Secundário:** fundo branco, borda cinza, texto Tinta.
- **Perigo:** como o secundário, com texto vermelho (Apagar).
- **Link:** texto cobalto sem borda; o sublinhado aparece no hover.
- **Hover / Active:** sobe 1px com a sombra de repouso; ao clicar, afunda (scale 0,98). Tudo para com redução de movimento.

### Chips (selos)
- **Style:** pílula com o texto na cor do estado e fundo da mesma cor a 12–14%.
- **State:** IA (verde), Handoff (âmbar), Assumida (cobalto); rótulo de atenção em âmbar.

### Cards / Containers
- **Corner Style:** 14px.
- **Background:** Superfície sobre o fundo; a linha que pede atenção não muda de fundo.
- **Shadow Strategy:** repouso. A linha da lista de conversas não levanta no hover: quem responde é o contorno que desliza.
- **Border:** 1px Borda.
- **Internal Padding:** 1.1–1.25rem.

### Inputs / Fields
- **Style:** fundo branco, borda cinza, cantos de 10px, 44px de altura, rótulo visível acima.
- **Focus:** borda cobalto com halo de 3px em Cobalto de Ação Suave.

### Navigation
- **Desktop:** links no topo, 44px de altura; hover com Superfície Recuada; página atual com Cobalto de Ação Suave e texto cobalto.
- **Celular:** botão "Menu" abre um painel lateral (StaggeredMenu) calmo: itens em caixa de frase, Red Hat Text 500 a ~1.15rem, linhas de 48px, sem numeração; a página atual em Cobalto de Ação Suave com texto cobalto; entrada com fade curto; a conta no pé.

### Membro (lista e página)
A equipe é uma lista dentro de um único cartão, uma linha por pessoa separada por fio de 1px: avatar de 40px, nome com função e perfil abaixo, estado, e à direita as conversas assumidas (mono). A linha inteira é o link para a página do membro. O estado é um ponto de 0,55rem com o texto ao lado, nunca só a cor: verde-IA cheio (disponível), âmbar cheio (ausente), contorno grafite (fora do painel). No celular a carga desce para baixo do nome. A página do membro abre com avatar de 72px, nome, função e estado, e segue em cartões: Atividade (números em mono de 1,15rem, sem destaque de cor), Últimas ações, Contato e acesso, Seu perfil (só na própria) e Gestão (só o gestor). A disponibilidade é um par de botões com `aria-pressed`, o escolhido em superfície branca.

### Bancos e produtos
A tela Bancos troca de banco pelas abas de página (as mesmas do Agente), uma por banco. Abaixo, o título da seção (o produto; o banco já está na aba) com o selo de situação (Integrado, Só cálculo, A integrar) e o link para as regras vigentes na Operação. O banco integrado mostra a tela dele; os outros, um cartão de leitura com duas listas, cada uma sob um rótulo em grafite: o que o agente faz hoje e o que falta para integrar. A tela Operação é de todos: abre com um cartão por produto, com as regras vigentes em grupos de pares rótulo e valor separados por fio de 1px, e o link para o banco. Os valores chegam prontos do servidor; a tela não escreve número de regra. Cota e custos, abaixo, aparecem só para o gestor.

### Abas
Um estilo só de aba de página (Agente, Bancos, Granatech, Ficha e IA da conversa): texto em grafite sobre um fio de 1px em Borda; a aba atual em cobalto com sublinhado de 2px. Sem trilho, fundo ou sombra. Setas, Home e End trocam de aba; o conteúdo fica num `tabpanel` ligado à aba. Rolam de lado se faltar espaço, nunca cortam.

### Linha de conversa (assinatura)
A lista segue o modelo AnimatedList da React Bits, com os tokens do painel: as linhas entram uma a uma (fade, 40 ms entre elas, uma vez por linha); um contorno único em grafite desliza entre as linhas atrás do ponteiro e vira cobalto de 2px quando é o foco do teclado; no desktop, a borda da rolagem que ainda tem linha esmaece. À esquerda, uma capa de 36px mostra quem está com a conversa (iniciais ou foto de quem assumiu; ícone da IA em verde; ícone do handoff em âmbar), repetindo em desenho o que o selo diz em texto.

Prévia da última fala com o autor colorido como conteúdo principal; telefone mascarado e canal em segundo plano; à direita, rótulo de atenção só para envio que falhou (os outros motivos aparecem no tempo, na etapa, no filtro "pedem atenção" e na ordem da lista; em texto, só para leitor de tela), etapa, selo de estado e espera relativa ("cliente espera há 12 min"). No desktop tem o botão Assumir/Devolver; arrastar para a esquerda é atalho (no celular, o caminho). Assumir e devolver valem na hora, na lista e no cabeçalho da conversa; por 5s o aviso "Desfazer" devolve a conversa ao estado de antes. O botão Assumir só é principal (cobalto) na linha que pede atenção.

### Acompanhamento na conversa
Ao lado das mensagens, antes da Ficha: a oferta vigente (liberado, parcelas, taxa e CET, seguro), a proposta no banco e as provas de consentimento, para conferir a fala da IA sem trocar de tela. Valores em mono. A situação da proposta usa o mesmo rótulo em português da aba Granatech (um mapa só); a formalização no link do banco se chama "assinatura" ("Aguardando assinatura", "Refazer assinatura"). Quando a proposta do banco não bate com a oferta, uma faixa âmbar diz "Difere da oferta vigente".

### Conferência da fala da IA
Sob cada fala da IA que cita reais, três estados: confere com a oferta (grafite, discreto); valor sem origem registrada ou vindo do modelo (selo âmbar, com texto); valor que difere da oferta (selo âmbar cheio, com os valores). A espera relativa da lista ("ontem", "há 12 min") é texto; datas e horas de tabela e ficha vão em mono.

### Balões da conversa
Cliente à esquerda em branco; IA à direita em verde tingido; equipe à direita em cobalto suave; sistema centrado, sem balão, em grafite. Imagem anexada vai numa moldura fixa de 16rem em 4:3 (RefineFrame), que guarda o lugar enquanto carrega e revela a imagem do mosaico em ~0,5 s; se falha, diz "Não carregou" e oferece "Tentar de novo". PDF e vídeo vão num cartão (ícone, nome, tipo); os demais arquivos, num cartão que só baixa. O clique em imagem, PDF ou vídeo abre o visor de mídia: a miniatura cresce até virar o conteúdo aberto em 0,3 s (View Transitions, no modelo do Morphing Dialog) e encolhe ao fechar por botão, Esc ou clique no fundo; Ctrl/⌘-clique abre em outra aba. O visor é escuro nos dois temas. Só imagem, áudio, vídeo e PDF são desenhados (`src/anexos.ts`): o arquivo vem do cliente, e o resto nunca abre dentro do painel.

## Do's and Don'ts

### Do:
- **Do** usar o Cobalto de Ação só para ação, página atual e a fala da equipe.
- **Do** mostrar o porquê da atenção em texto na conversa aberta e nos alertas; na linha da lista, só "Envio falhou" ganha rótulo visível.
- **Do** usar mono e números tabulares para telefone, hora, custo e tokens.
- **Do** manter alvos de 44px e foco visível de 2px em cobalto.
- **Do** desligar movimento com `prefers-reduced-motion`.

### Don't:
- **Don't** usar verde, âmbar ou vermelho como decoração.
- **Don't** usar barra lateral colorida de mais de 1px em cartões ou linhas.
- **Don't** mostrar dado pessoal sem máscara fora do "Revelar" auditado.
- **Don't** usar violeta ou lilás.
- **Don't** criar uma segunda cor de ação.
