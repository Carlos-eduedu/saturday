"""Casos para conferir o painel local no navegador, com dados fictícios.

Cria uma conversa do ramo CLT que o SQL não consegue criar, porque a ficha mora
no checkpoint do grafo:

- ficha preenchida (nome, CPF, nascimento, e-mail), para ver e editar;
- com humano (handoff e alerta aberto), para assumir e devolver à IA;
- consulta da Granatech parada em PROCESSING, para o "atualizar detalhe".

E uma do ramo INSS em que o cliente aceitou o contrato novo do C6: handoff, as
condições aceitas no checkpoint e a prova do SIM da simulação.

E uma do ramo INSS com a oferta de portabilidade e outra com o pacote do iCred,
cada uma com a fala fixa da oferta e uma resposta do modelo que cita reais (a
da portabilidade com um valor fora da oferta), para a conferência da fala. E
uma com o contrato novo recusado seguido da oferta de portabilidade.

E, para o funil da Operação, uma conversa CLT do SIM à proposta paga, mais os
turnos e as provas que dão público e etapa às conversas acima (os números
esperados estão na decisão 0031).

E o que a tela precisa para ser conferida de verdade:

- um gestor para entrar (`gestor@exemplo.test`); a senha é sorteada a cada
  rodada e impressa no fim, ou vem de `PAINEL_LOCAL_SENHA`;
- conversas nas três situações (IA, aguardando humano, com humano), para a
  lista rolar;
- uma conversa com imagem, PDF e arquivo sem prévia, gravados no S3 local.

Não roda o grafo nem chama parceiro nenhum. Pode rodar de novo. Use por
`infra/painel_local.sh seed`, que já exporta o banco e os segredos fictícios.
"""

import os
import secrets
import struct
import zlib
from decimal import Decimal

from saturday.agent.graph import build_graph
from saturday.agent.icred import textos as textos_icred
from saturday.agent.textos import (
    CONSENTIMENTO_C6,
    OFERTA_CONTRATO_NOVO,
    VERSAO_CONSENTIMENTO_C6,
)
from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import (
    Consentimento,
    ConsultaGranatech,
    ConsultaIcred,
    Conversa,
    Mensagem,
    PropostaGranatech,
    Turno,
    UsuarioPainel,
)
from saturday.dados.sessao import criar_engine, criar_factory
from saturday.dados.sessao import sessao as abrir
from saturday.painel.auditoria import auditar
from saturday.painel.sessoes import agora, criar_usuario, gerar_hash
from saturday.portabilidade.mensagem import mensagem_oferta
from saturday.settings import get_settings
from saturday.storage.base import criar_storage
from saturday.web.composicao import criar_checkpointer
from sqlalchemy import select

CONVERSA = "seed-painel-clt"
CONVERSA_C6 = "seed-painel-c6-novo"
CONVERSA_PORTABILIDADE = "seed-painel-portabilidade"
CONVERSA_ICRED = "seed-painel-icred"
CONVERSA_OUTRO_TITULAR = "seed-painel-icred-outro-titular"
CONVERSA_RECUSADO = "seed-painel-c6-recusado"
CONVERSA_PAGA = "seed-painel-clt-paga"
CPF = "00189004967"  # fictício, o mesmo dos testes
FAIXA = {"min": 1234.56, "max": 1500.99}
PORTABILIDADE = {
    "ok": True,
    "troco_total": 2743.47,
    "troco_faixa": {"min": 2469.12, "max": 3001.98},
    "contratos": [
        {"banco": "BMG", "elegivel": True, "troco_faixa": FAIXA},
        {"banco": "PAN", "elegivel": True, "troco_faixa": FAIXA},
    ],
}
PACOTE_ICRED = [
    {
        "tipo": "port_refin",
        "banco": "BMG",
        "taxa": "1.66",
        "prazo": 96,
        "parcela": "210.50",
        "liberado": "3200.00",
    },
    {
        "tipo": "novo",
        "banco": "iCred",
        "taxa": "1.80",
        "prazo": 84,
        "parcela": "98.40",
        "liberado": "4100.00",
    },
]
GESTOR = "gestor@exemplo.test"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FALAS = [
    "oi, quero saber do crédito do trabalhador",
    "qual a taxa de juros?",
    "consigo fazer mesmo negativado?",
    "quanto tempo demora para cair na conta?",
    "quero falar com uma pessoa",
    "meu contrato já foi aprovado?",
    "preciso mudar a conta do depósito",
]


def imagem_png(largura: int = 480, altura: int = 640) -> bytes:
    """Um degradê, para a miniatura ter o que revelar; nada binário no repositório."""

    linhas = b"".join(
        b"\x00"
        + b"".join(
            bytes((40 + 180 * x // largura, 90 + 120 * y // altura, 220))
            for x in range(largura)
        )
        for y in range(altura)
    )

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        corpo = tipo + dados
        return (
            struct.pack(">I", len(dados)) + corpo + struct.pack(">I", zlib.crc32(corpo))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
        + bloco(b"IDAT", zlib.compress(linhas))
        + bloco(b"IEND", b"")
    )


def pdf(linhas: list[str]) -> bytes:
    """PDF mínimo de uma página, com texto fictício."""

    texto = "BT /F1 22 Tf 60 760 Td " + " ".join(
        f"({linha}) Tj 0 -34 Td" for linha in linhas
    )
    fluxo = (texto + " ET").encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(fluxo)).encode()
        + b" >>\nstream\n"
        + fluxo
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for i, corpo in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += f"{i} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    saida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posicoes)
    saida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n".encode()
    return bytes(saida + f"startxref\n{xref}\n%%EOF\n".encode())


def prova(conversa, tipo: str, texto: str = "pedido do seed", versao: str = "seed"):
    """Prova de um SIM; o funil conta a conversa pela existência dela."""

    return Consentimento(
        conversa_id=conversa.id,
        tipo=tipo,
        texto_mostrado=texto,
        versao=versao,
        resposta_literal="sim",
        cpf=CPF,
    )


def fala_da_ia(
    sessao, conversa, texto: str, chave: str | None, *caminho: str, etapa: str = "inss"
) -> None:
    """Fala com a procedência que o turno gravaria (decisão 0018).

    Sem chave, quem escreveu foi o modelo: o turno leva a chamada ao `llm`. A
    etapa do turno é o que diz o público da conversa ao funil (decisão 0031).
    """

    # Mesmas chaves que `TurnMetrics.resumo` grava: o painel conta com todas elas.
    llm = {
        "nome": "llm",
        "latencia_ms": 900,
        "custo_usd": None,
        "status": "ok",
        "tokens_entrada": None,
        "tokens_saida": None,
    }
    chamadas = [] if chave else [llm]
    turno = Turno(
        conversa_id=conversa.id,
        caminho=["__start__", *caminho],
        status="answered",
        etapa=etapa,
        chamadas=chamadas,
    )
    sessao.add(turno)
    sessao.flush()
    repositorios.registrar_saida(
        sessao, conversa, conteudo=texto, turno_id=turno.id, chave_mensagem=chave
    )


settings = get_settings()
fabrica = criar_factory(criar_engine(settings))
checkpointer, pool = criar_checkpointer(settings)

with abrir(fabrica) as sessao:
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA,
        canal="whatsapp",
        telefone="5511900000001",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao,
        conversa,
        message_id="seed-painel-1",
        conteudo="quero falar com uma pessoa",
    ):
        repositorios.registrar_saida(
            sessao, conversa, conteudo="Vou chamar alguém da equipe."
        )
    atendimento.entrar_em_handoff(sessao, conversa, "handoff")
    if sessao.scalar(
        select(ConsultaGranatech.id).where(ConsultaGranatech.id_externo == "seed-1")
    ):
        print("consulta do seed já existe")
    else:
        sessao.add(
            ConsultaGranatech(
                id_externo="seed-1",
                teste=True,
                cpf=CPF,
                conversa_id=conversa.id,
                status="PROCESSING",
            )
        )
        sessao.add(prova(conversa, "consulta"))
        sessao.add(
            Turno(
                conversa_id=conversa.id,
                caminho=["__start__", "clt"],
                etapa="consultando",
            )
        )

    # Para o funil da Operação ter número em todas as etapas: uma conversa CLT
    # que foi do SIM ao pagamento. A proposta não leva a marca de teste, que a
    # tiraria do funil; por isso ela aparece também na aba Granatech.
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_PAGA,
        canal="whatsapp",
        telefone="5511900000006",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao, conversa, message_id="seed-paga-1", conteudo="sim"
    ):
        fala_da_ia(
            sessao,
            conversa,
            "Boa notícia: saiu a sua oferta.",
            "oferta_sem_seguro",
            "clt",
            etapa="oferta",
        )
        sessao.add_all([prova(conversa, "consulta"), prova(conversa, "proposta")])
        consulta = ConsultaGranatech(
            id_externo="seed-paga", cpf=CPF, conversa_id=conversa.id, status="SUCCESS"
        )
        sessao.add(consulta)
        sessao.flush()
        sessao.add(
            PropostaGranatech(
                consulta_id=consulta.id,
                conversa_id=conversa.id,
                id_externo="seed-paga",
                estado_envio="criada",
                valor_parcela=Decimal("210.50"),
                numero_parcelas=24,
                status="PAYED",
            )
        )

build_graph(checkpointer).update_state(
    {"configurable": {"thread_id": CONVERSA}},
    {
        "status": "handoff",
        "handoff_reason": "pediu_humano",
        "publico": "clt",
        "clt": {
            "etapa": "consultando",
            "dados": {
                "nome": "Maria Silva",
                "cpf": CPF,
                "nascimento": "1990-05-20",
                "email": "maria@exemplo.test",
            },
        },
    },
)
with abrir(fabrica) as sessao:
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_C6,
        canal="whatsapp",
        telefone="5567900000002",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao, conversa, message_id="seed-c6-1", conteudo="sim"
    ):
        fala_da_ia(
            sessao,
            conversa,
            OFERTA_CONTRATO_NOVO.format(
                valor="4.321,09", parcela="99,00", parcelas=108, taxa="1,85"
            ),
            "textos:oferta_contrato_novo",
            "simulate_c6",
        )
        repositorios.registrar_entrada(
            sessao, conversa, message_id="seed-c6-2", conteudo="quero"
        )
        sessao.add(
            Consentimento(
                conversa_id=conversa.id,
                tipo="simulacao_c6",
                texto_mostrado=CONSENTIMENTO_C6,
                versao=VERSAO_CONSENTIMENTO_C6,
                resposta_literal="sim",
                wamid="seed-c6-1",
                cpf=CPF,
            )
        )
        sessao.add(
            Turno(
                conversa_id=conversa.id,
                caminho=["__start__", "classify_intent", "handoff"],
                status="handoff",
                motivo="aceitou_contrato_novo",
                etapa="inss",
            )
        )
    atendimento.entrar_em_handoff(sessao, conversa, "handoff")

build_graph(checkpointer).update_state(
    {"configurable": {"thread_id": CONVERSA_C6}},
    {
        "status": "handoff",
        "handoff_reason": "aceitou_contrato_novo",
        "publico": "inss",
        "cliente": {"cpf": CPF, "uf": "MS", "c6_autorizado": True},
        # Convênio e produto são códigos fictícios, no formato do simulador.
        "c6_novo": {
            "situacao": "aceito",
            "valor": "4321.09",
            "parcela": "99.00",
            "parcelas": 108,
            "taxa": "1.85",
            "convenio": "000020",
            "produto": "0001",
        },
    },
)
with abrir(fabrica) as sessao:
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_PORTABILIDADE,
        canal="whatsapp",
        telefone="5567900000003",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao, conversa, message_id="seed-port-1", conteudo="segue o meu extrato"
    ):
        fala_da_ia(
            sessao,
            conversa,
            mensagem_oferta(PORTABILIDADE, "MS"),
            "inss:oferta",
            "calculate_portability",
            "present_offer",
        )
        repositorios.registrar_entrada(
            sessao,
            conversa,
            message_id="seed-port-2",
            conteudo="quanto sobra no total?",
        )
        # O modelo não deveria citar valor; este está fora da oferta, de propósito.
        fala_da_ia(
            sessao,
            conversa,
            "A sobra fica em torno de R$ 3.500,00, somando os dois contratos.",
            None,
            "classify_intent",
            "generate_answer",
        )

    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_ICRED,
        canal="whatsapp",
        telefone="5567900000004",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao, conversa, message_id="seed-icred-1", conteudo="sim"
    ):
        fala_da_ia(
            sessao,
            conversa,
            textos_icred.oferta(PACOTE_ICRED),
            "icred:oferta",
            "icred",
        )
        repositorios.registrar_entrada(
            sessao,
            conversa,
            message_id="seed-icred-2",
            conteudo="esse valor cai na conta mesmo?",
        )
        fala_da_ia(
            sessao,
            conversa,
            "Sim: os R$ 7.300,00 caem na sua conta depois da assinatura.",
            None,
            "classify_intent",
            "generate_answer",
        )
        sessao.add(prova(conversa, "icred_consulta"))
        sessao.add(
            ConsultaIcred(
                chave="seed-icred-oferta",
                cpf=CPF,
                conversa_id=conversa.id,
                estado="concluida",
                situacao="COM_OFERTA",
                contratos=PACOTE_ICRED,
            )
        )

    # Consulta aberta de um titular, e depois o extrato de outro: a consulta
    # fica `desistida` e deixa de ser a da conversa (issue 42).
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_OUTRO_TITULAR,
        canal="whatsapp",
        telefone="5567900000007",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao,
        conversa,
        message_id="seed-outro-titular-1",
        conteudo="agora o extrato do meu marido",
    ):
        fala_da_ia(
            sessao,
            conversa,
            textos_icred.PEDIR_SIM,
            "icred:pedir_sim",
            "read_statement",
            "icred_porta",
        )
        sessao.add(prova(conversa, "icred_consulta"))
        sessao.add(
            ConsultaIcred(
                chave="seed-icred-outro-titular",
                cpf=CPF,
                conversa_id=conversa.id,
                estado="desistida",
            )
        )

    # Contrato novo recusado e, depois, a portabilidade: a fala antiga do C6
    # é conferida contra a oferta do próprio ramo, e o cartão a marca "recusada".
    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        CONVERSA_RECUSADO,
        canal="whatsapp",
        telefone="5567900000005",
        phone_number_id="100000000000001",
    )
    if repositorios.registrar_entrada(
        sessao, conversa, message_id="seed-recusado-1", conteudo="sim"
    ):
        fala_da_ia(
            sessao,
            conversa,
            OFERTA_CONTRATO_NOVO.format(
                valor="4.321,09", parcela="99,00", parcelas=108, taxa="1,85"
            ),
            "textos:oferta_contrato_novo",
            "simulate_c6",
        )
        sessao.add(
            prova(conversa, "simulacao_c6", CONSENTIMENTO_C6, VERSAO_CONSENTIMENTO_C6)
        )
        repositorios.registrar_entrada(
            sessao, conversa, message_id="seed-recusado-2", conteudo="esse não quero"
        )
        fala_da_ia(
            sessao,
            conversa,
            mensagem_oferta(PORTABILIDADE, "MS"),
            "inss:oferta",
            "decline_c6",
            "calculate_portability",
            "present_offer",
        )

grafo = build_graph(checkpointer)
grafo.update_state(
    {"configurable": {"thread_id": CONVERSA_RECUSADO}},
    {
        "status": "answered",
        "publico": "inss",
        "cliente": {"cpf": CPF, "uf": "MS", "c6_autorizado": True},
        "c6_novo": {
            "situacao": "recusado",
            "valor": "4321.09",
            "parcela": "99.00",
            "parcelas": 108,
            "taxa": "1.85",
            "convenio": "000020",
            "produto": "0001",
        },
        "portability_result": PORTABILIDADE,
        "oferta_pendente": True,
    },
)
grafo.update_state(
    {"configurable": {"thread_id": CONVERSA_PORTABILIDADE}},
    {
        "status": "answered",
        "publico": "inss",
        "cliente": {"uf": "MS"},
        "portability_result": PORTABILIDADE,
        "oferta_pendente": True,
    },
)
grafo.update_state(
    {"configurable": {"thread_id": CONVERSA_ICRED}},
    {
        "status": "answered",
        "publico": "inss",
        "cliente": {"uf": "MS"},
        "icred": {"etapa": "oferta", "cpf": CPF, "contratos": PACOTE_ICRED},
    },
)
grafo.update_state(
    {"configurable": {"thread_id": CONVERSA_OUTRO_TITULAR}},
    {
        "status": "answered",
        "publico": "inss",
        "cliente": {"uf": "MS"},
        # O pedido de SIM ao novo titular; a consulta do anterior saiu do estado.
        "icred": {"etapa": "sim", "pedido": "icred-1", "cpf": "52998224725"},
    },
)
senha = os.environ.get("PAINEL_LOCAL_SENHA") or secrets.token_urlsafe(12)
with abrir(fabrica) as sessao:
    gestor = sessao.scalar(select(UsuarioPainel).where(UsuarioPainel.email == GESTOR))
    if gestor is None:
        gestor = criar_usuario(sessao, GESTOR, senha, "gestor", "Gestor Local")
    else:
        gestor.senha_hash = gerar_hash(senha)

    # A equipe, para a aba Membros ter quem mostrar: uma atendente com carga e
    # atividade, um ausente, uma desativada e uma com a troca de senha
    # pendente. A senha é a mesma do gestor.
    equipe = {}
    for email, nome, cargo in [
        ("bia@exemplo.test", "Bia Souza", "Atendente CLT"),
        ("caio@exemplo.test", "Caio Lima", "Atendente INSS"),
        ("dora@exemplo.test", "Dora Reis", None),
        ("eva@exemplo.test", "Eva Prado", None),
    ]:
        pessoa = sessao.scalar(
            select(UsuarioPainel).where(UsuarioPainel.email == email)
        )
        if pessoa is None:
            pessoa = criar_usuario(sessao, email, senha, "atendente", nome)
        else:
            pessoa.senha_hash = gerar_hash(senha)
        pessoa.cargo = cargo
        equipe[email] = pessoa
    gestor.cargo = "Gestão do atendimento"
    bia = equipe["bia@exemplo.test"]
    bia.ultimo_acesso_em = agora()
    equipe["caio@exemplo.test"].disponivel = False
    equipe["dora@exemplo.test"].ativo = False
    # Recém-cadastrada pelo gestor: entra e só vê a troca de senha (decisão 0030).
    equipe["eva@exemplo.test"].trocar_senha = True

    for n in range(14):
        situacao = ("ia", "handoff", "assumida")[n % 3]
        conversa = repositorios.obter_ou_criar_conversa(
            sessao,
            f"seed-painel-lista-{n}",
            canal="whatsapp",
            telefone=f"55119000001{n:02d}",
            phone_number_id="100000000000001",
        )
        if not repositorios.registrar_entrada(
            sessao,
            conversa,
            message_id=f"seed-lista-{n}",
            conteudo=FALAS[n % len(FALAS)],
        ):
            continue
        repositorios.registrar_saida(sessao, conversa, conteudo="Claro, já te explico.")
        if situacao == "handoff":
            atendimento.entrar_em_handoff(sessao, conversa, "handoff")
        elif situacao == "assumida":
            # Metade com a Bia, com o rastro que o painel deixaria.
            dono = bia if n % 2 else gestor
            atendimento.assumir(sessao, conversa, dono.id)
            auditar(sessao, dono.id, "assumir", str(conversa.id))
            repositorios.registrar_saida(
                sessao,
                conversa,
                conteudo="Oi, aqui é da equipe. Já vejo isso.",
                autor="atendente",
                usuario_id=dono.id,
            )
            auditar(sessao, dono.id, "enviar_mensagem", str(conversa.id))

    conversa = repositorios.obter_ou_criar_conversa(
        sessao,
        "seed-painel-anexos",
        canal="whatsapp",
        telefone="5511900000199",
        phone_number_id="100000000000001",
    )
    if sessao.scalar(select(Mensagem.id).where(Mensagem.conversa_id == conversa.id)):
        print("conversa de anexos já existe")
    else:
        try:
            storage = criar_storage(settings)
            arquivos = [
                (
                    "Segue a foto do documento",
                    imagem_png(),
                    "image/png",
                    "rg-frente.png",
                ),
                (
                    "E o holerite",
                    pdf(
                        [
                            "Holerite (ficticio)",
                            "Funcionaria: Maria Silva",
                            "Competencia: 10/2026",
                        ]
                    ),
                    "application/pdf",
                    "holerite-outubro.pdf",
                ),
                ("", b"arquivo ficticio do seed", DOCX, "carta-de-margem.docx"),
            ]
            for i, (texto, dados, mime, nome) in enumerate(arquivos):
                chave = storage.salvar(dados, mime_type=mime)
                repositorios.registrar_entrada(
                    sessao,
                    conversa,
                    message_id=f"seed-anexo-{i}",
                    conteudo=texto,
                    anexos=[{"chave": chave, "mime_type": mime, "nome": nome}],
                )
            atendimento.assumir(sessao, conversa, gestor.id)
        except Exception as exc:  # noqa: BLE001 -- sem storage o resto do seed ainda serve
            print(f"sem anexos: o S3 local não respondeu ({type(exc).__name__})")

if pool is not None:
    pool.close()
# Os caminhos que os prints costumam pedir, para não consultar o banco atrás de id.
with abrir(fabrica) as sessao:
    for pessoa in sessao.scalars(select(UsuarioPainel).order_by(UsuarioPainel.email)):
        assumida = sessao.scalar(
            select(Conversa.id).where(Conversa.atendente_id == pessoa.id).limit(1)
        )
        conversa_dela = f"  /conversas/{assumida}" if assumida else ""
        print(f"{pessoa.email}  /membros/{pessoa.id}{conversa_dela}")
    for nome, ref in [
        ("contrato novo no C6", CONVERSA_C6),
        ("portabilidade", CONVERSA_PORTABILIDADE),
        ("iCred", CONVERSA_ICRED),
        ("C6 recusado e portabilidade", CONVERSA_RECUSADO),
    ]:
        alvo = sessao.scalar(select(Conversa.id).where(Conversa.conversation_id == ref))
        print(f"{nome}  /conversas/{alvo}")
print(f"seed pronto: entre com {GESTOR} e a senha {senha}")
