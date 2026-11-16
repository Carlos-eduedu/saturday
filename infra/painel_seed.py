"""Casos para conferir o painel local no navegador, com dados fictícios.

Cria uma conversa do ramo CLT que o SQL não consegue criar, porque a ficha mora
no checkpoint do grafo:

- ficha preenchida (nome, CPF, nascimento, e-mail), para ver e editar;
- com humano (handoff e alerta aberto), para assumir e devolver à IA;
- consulta da Granatech parada em PROCESSING, para o "atualizar detalhe".

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

from saturday.agent.graph import build_graph
from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import ConsultaGranatech, Mensagem, UsuarioPainel
from saturday.dados.sessao import criar_engine, criar_factory
from saturday.dados.sessao import sessao as abrir
from saturday.painel.sessoes import criar_usuario, gerar_hash
from saturday.settings import get_settings
from saturday.storage.base import criar_storage
from saturday.web.composicao import criar_checkpointer
from sqlalchemy import select

CONVERSA = "seed-painel-clt"
CPF = "00189004967"  # fictício, o mesmo dos testes
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
senha = os.environ.get("PAINEL_LOCAL_SENHA") or secrets.token_urlsafe(12)
with abrir(fabrica) as sessao:
    gestor = sessao.scalar(select(UsuarioPainel).where(UsuarioPainel.email == GESTOR))
    if gestor is None:
        gestor = criar_usuario(sessao, GESTOR, senha, "gestor", "Gestor Local")
    else:
        gestor.senha_hash = gerar_hash(senha)

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
            atendimento.assumir(sessao, conversa, gestor.id)

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
print(f"seed pronto: entre com {GESTOR} e a senha {senha}")
