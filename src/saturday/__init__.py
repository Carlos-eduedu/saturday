def main() -> None:
    import uvicorn

    # Escuta em todas as interfaces; a autenticação fica na aplicação.
    uvicorn.run("saturday.api:app", host="0.0.0.0", port=8000)  # noqa: S104
