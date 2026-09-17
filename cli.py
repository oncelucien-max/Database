import json
import logging

import click

from db_manager import DbConfig, DbManager, UnknownTableError

logging.basicConfig(level=logging.INFO)


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = DbManager(DbConfig.from_env())
    ctx.call_on_close(ctx.obj.close)


@cli.command()
@click.pass_obj
def health(db: DbManager):
    click.echo("OK" if db.health_check() else "FAIL")


@cli.command("list-tables")
@click.pass_obj
def list_tables(db: DbManager):
    for table in db.list_tables():
        click.echo(table)


@cli.command("describe")
@click.argument("table")
@click.pass_obj
def describe(db: DbManager, table: str):
    try:
        for col in db.list_columns(table):
            click.echo(f"{col['column_name']}\t{col['data_type']}\tnullable={col['is_nullable']}")
    except UnknownTableError:
        raise click.ClickException(f"Table inconnue: {table}")


@cli.command("select")
@click.argument("table")
@click.option("--limit", default=50)
@click.option("--offset", default=0)
@click.pass_obj
def select(db: DbManager, table: str, limit: int, offset: int):
    try:
        rows = db.select(table, limit=limit, offset=offset)
        click.echo(json.dumps(rows, default=str, indent=2, ensure_ascii=False))
    except UnknownTableError:
        raise click.ClickException(f"Table inconnue: {table}")


@cli.command("insert")
@click.argument("table")
@click.option("--data", required=True, help="JSON object des colonnes/valeurs")
@click.pass_obj
def insert(db: DbManager, table: str, data: str):
    try:
        row = db.insert(table, json.loads(data))
        click.echo(json.dumps(row, default=str, indent=2, ensure_ascii=False))
    except UnknownTableError:
        raise click.ClickException(f"Table inconnue: {table}")


@cli.command("update")
@click.argument("table")
@click.option("--data", required=True, help="JSON object des colonnes à modifier")
@click.option("--where", required=True, help="JSON object des conditions")
@click.pass_obj
def update(db: DbManager, table: str, data: str, where: str):
    try:
        count = db.update(table, json.loads(data), json.loads(where))
        click.echo(f"{count} ligne(s) modifiée(s)")
    except UnknownTableError:
        raise click.ClickException(f"Table inconnue: {table}")


@cli.command("delete")
@click.argument("table")
@click.option("--where", required=True, help="JSON object des conditions")
@click.confirmation_option(prompt="Confirmer la suppression ?")
@click.pass_obj
def delete(db: DbManager, table: str, where: str):
    try:
        count = db.delete(table, json.loads(where))
        click.echo(f"{count} ligne(s) supprimée(s)")
    except UnknownTableError:
        raise click.ClickException(f"Table inconnue: {table}")


if __name__ == "__main__":
    cli()
