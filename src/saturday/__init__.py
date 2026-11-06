def main() -> None:
    import uvicorn

    uvicorn.run("saturday.api:app", host="0.0.0.0", port=8000)
