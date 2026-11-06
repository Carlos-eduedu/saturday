def main() -> None:
    import uvicorn

    from saturday.log import configurar_logging
    from saturday.settings import get_settings

    settings = get_settings()
    configurar_logging(settings.log_level)
    settings.validar_para_subir()

    # Um único worker: o estado das conversas vive no SQLite local.
    # Escuta em todas as interfaces; a autenticação fica na aplicação.
    uvicorn.run("saturday.api:app", host="0.0.0.0", port=8000, log_config=None)  # noqa: S104
