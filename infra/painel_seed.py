"""Casos para conferir o painel local no navegador, com dados fictícios.

Cria uma conversa do ramo CLT que o SQL não consegue criar, porque a ficha mora
no checkpoint do grafo:

- ficha preenchida (nome, CPF, nascimento, e-mail), para ver e editar;
- com humano (handoff e alerta aberto), para assumir e devolver à IA;
- consulta da Granatech parada em PROCESSING, para o "atualizar detalhe".

Não roda o grafo nem chama parceiro nenhum. Pode rodar de novo. Use por
`infra/painel_local.sh seed`, que já exporta o banco e os segredos fictícios.
"""

from saturday.agent.graph import build_graph
from saturday.dados import repositorios
from saturday.dados.modelos import ConsultaGranatech
from saturday.dados.sessao import criar_engine, criar_factory
from saturday.dados.sessao import sessao as abrir
from saturday.settings import get_settings
from saturday.web.composicao import criar_checkpointer
from sqlalchemy import select

CONVERSA = "seed-painel-clt"
CPF = "00189004967"  # fictício, o mesmo dos testes

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
    repositorios.mudar_atendimento(sessao, conversa, "handoff")
    repositorios.abrir_alerta(sessao, "handoff", conversa_id=conversa.id, unico=True)
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
if pool is not None:
    pool.close()
print(f"seed pronto: conversa {CONVERSA}")
