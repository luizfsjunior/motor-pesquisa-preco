import asyncio

import typer

from app.database.session import init_db
from app.services.monitor import PriceMonitorService
from app.utils.export import export_csv, export_excel
from app.utils.logging_setup import setup_logging

app = typer.Typer(help="Motor de pesquisa de preços multi-marketplace")


@app.command("init-db")
def init_db_cmd() -> None:
    """Cria tabelas no SQLite."""
    setup_logging()
    init_db()
    typer.echo("Database initialized.")


@app.command("run-once")
def run_once() -> None:
    """Executa um ciclo completo de scraping."""
    setup_logging()
    init_db()
    service = PriceMonitorService()
    stats = asyncio.run(service.run_cycle())
    typer.echo(f"Cycle done: {stats}")
    if stats.get("digest_sent"):
        typer.echo("Telegram: fallback digest (menor preço ou aviso sem dados) enviado.")
    elif stats.get("alerts"):
        typer.echo("Telegram: alerta(s) de promoção enviado(s).")


@app.command("export-csv")
def export_csv_cmd() -> None:
    path = export_csv()
    typer.echo(f"CSV exported to {path}")


@app.command("export-excel")
def export_excel_cmd() -> None:
    path = export_excel()
    typer.echo(f"Excel exported to {path}")


if __name__ == "__main__":
    app()
