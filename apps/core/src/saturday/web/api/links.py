"""``GET /l/{codigo}``: redireciona ao link de biometria vigente da proposta.

O banco troca o link quando a biometria precisa ser refeita; o aviso que o
cliente recebeu continua valendo porque o destino é buscado no clique. Se a
Granatech não responder, vale a última URL conhecida.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import ErroGranatech
from saturday.dados import links
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.web.dependencies import exigir_fabrica, get_agent_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["links"])


@router.get("/l/{codigo}", include_in_schema=False)
def redirecionar(
    codigo: str,
    request: Request,
    fabrica: Annotated[sessionmaker[Session], Depends(exigir_fabrica)],
) -> RedirectResponse:
    with abrir_sessao(fabrica) as sessao:
        link = links.buscar(sessao, codigo)
        if link is None:
            raise HTTPException(status_code=404, detail="link não encontrado")
        id_proposta, guardada = link.id_proposta, link.url

    destino = guardada
    granatech = get_agent_service(request).context.granatech
    if granatech is not None:
        try:
            vigente = granatech.status_proposta(id_proposta).get("url_seguranca_identidade")
        except ErroGranatech:
            logger.warning("link_curto_granatech_indisponivel")
            vigente = None
        if isinstance(vigente, str) and vigente.startswith("https://"):
            destino = vigente
            if vigente != guardada:
                with abrir_sessao(fabrica) as sessao:
                    atual = links.buscar(sessao, codigo)
                    if atual is not None:
                        atual.url = vigente
    return RedirectResponse(destino, status_code=302)
