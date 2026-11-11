def main() -> None:
    import sys

    # `saturday criar-usuario ...` cria usuário do painel; sem argumento, sobe a API.
    if sys.argv[1:2] == ["criar-usuario"]:
        from saturday.painel.cli import criar_usuario_cli

        raise SystemExit(criar_usuario_cli(sys.argv[2:]))

    import uvicorn

    from saturday.log import configurar_logging
    from saturday.settings import get_settings

    settings = get_settings()
    configurar_logging(settings.log_level)
    settings.validar_para_subir()

    # Um processo por padrão. A partir da Fase 1 o estado vive no Postgres e o
    # turno é serializado por `pg_advisory_xact_lock`, então subir mais de um
    # worker é seguro — é escolha de implantação, não requisito do código.
    # Escuta em todas as interfaces; a autenticação fica na aplicação.
    uvicorn.run(
        "saturday.web.application:get_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8000,
        workers=1,
        log_config=None,
    )
