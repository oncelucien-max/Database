import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import psycopg2
import psycopg2.extras
from psycopg2 import sql
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    minconn: int = 1
    maxconn: int = 10
    connect_timeout: int = 5

    @classmethod
    def from_env(cls) -> "DbConfig":
        return cls(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            minconn=int(os.environ.get("DB_POOL_MIN", 1)),
            maxconn=int(os.environ.get("DB_POOL_MAX", 10)),
        )


class DbError(Exception):
    pass


class UnknownTableError(DbError):
    pass


class DbManager:
    def __init__(self, config: DbConfig):
        self._config = config
        self._pool = ThreadedConnectionPool(
            minconn=config.minconn,
            maxconn=config.maxconn,
            host=config.host,
            port=config.port,
            dbname=config.dbname,
            user=config.user,
            password=config.password,
            connect_timeout=config.connect_timeout,
        )

    def close(self) -> None:
        self._pool.closeall()

    @contextmanager
    def connection(self):
        conn = self._pool.getconn()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            self._pool.putconn(conn)

    @contextmanager
    def cursor(self, dict_cursor: bool = True):
        cursor_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        with self.connection() as conn:
            cur = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cur
            finally:
                cur.close()

    def execute(self, query, params: Optional[Sequence[Any]] = None) -> int:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount

    def fetch_one(self, query, params: Optional[Sequence[Any]] = None) -> Optional[dict]:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def fetch_all(self, query, params: Optional[Sequence[Any]] = None) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_tables(self) -> list[str]:
        rows = self.fetch_all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        return [r["table_name"] for r in rows]

    def list_columns(self, table: str) -> list[dict]:
        self._assert_table_exists(table)
        return self.fetch_all(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )

    def primary_key(self, table: str) -> Optional[str]:
        self._assert_table_exists(table)
        row = self.fetch_one(
            """
            SELECT a.attname AS column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            LIMIT 1
            """,
            (f"public.{table}",),
        )
        return row["column_name"] if row else None

    def _assert_table_exists(self, table: str) -> None:
        if table not in self.list_tables():
            raise UnknownTableError(table)

    def select(self, table: str, limit: int = 50, offset: int = 0) -> list[dict]:
        self._assert_table_exists(table)
        query = sql.SQL("SELECT * FROM {table} LIMIT %s OFFSET %s").format(
            table=sql.Identifier(table)
        )
        return self.fetch_all(query, (limit, offset))

    def count(self, table: str) -> int:
        self._assert_table_exists(table)
        query = sql.SQL("SELECT COUNT(*) AS n FROM {table}").format(table=sql.Identifier(table))
        return self.fetch_one(query)["n"]

    def insert(self, table: str, data: dict) -> dict:
        self._assert_table_exists(table)
        columns = list(data.keys())
        values = list(data.values())
        query = sql.SQL("INSERT INTO {table} ({fields}) VALUES ({placeholders}) RETURNING *").format(
            table=sql.Identifier(table),
            fields=sql.SQL(", ").join(map(sql.Identifier, columns)),
            placeholders=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
        )
        with self.cursor() as cur:
            cur.execute(query, values)
            return cur.fetchone()

    def update(self, table: str, data: dict, where: dict) -> int:
        self._assert_table_exists(table)
        set_clause = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in data
        )
        where_clause = sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in where
        )
        query = sql.SQL("UPDATE {table} SET {set_clause} WHERE {where_clause}").format(
            table=sql.Identifier(table), set_clause=set_clause, where_clause=where_clause
        )
        params = list(data.values()) + list(where.values())
        return self.execute(query, params)

    def delete(self, table: str, where: dict) -> int:
        self._assert_table_exists(table)
        where_clause = sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in where
        )
        query = sql.SQL("DELETE FROM {table} WHERE {where_clause}").format(
            table=sql.Identifier(table), where_clause=where_clause
        )
        return self.execute(query, list(where.values()))

    def health_check(self) -> bool:
        try:
            with self.cursor(dict_cursor=False) as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            return False
