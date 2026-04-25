from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    dsn: str
    connect_timeout: int = 5
    application_name: str = "agripivot-backend"
    autocommit: bool = False


class PostgresDependencyMissingError(RuntimeError):
    """Raised when psycopg is required but unavailable."""


class PostgresDatabase:
    def __init__(self, config: PostgresConfig) -> None:
        self._config = config

    @property
    def config(self) -> PostgresConfig:
        return self._config

    @contextmanager
    def connection(self) -> Iterator["Connection[dict[str, Any]]"]:
        psycopg = _load_psycopg()
        dict_row = _load_dict_row()
        connection = psycopg.connect(
            conninfo=self._config.dsn,
            connect_timeout=self._config.connect_timeout,
            application_name=self._config.application_name,
            autocommit=self._config.autocommit,
            row_factory=dict_row,
        )

        try:
            yield connection
            if not self._config.autocommit:
                connection.commit()
        except Exception:
            if not self._config.autocommit:
                connection.rollback()
            raise
        finally:
            connection.close()


def apply_sql_file(database: PostgresDatabase, sql_path: str | Path) -> None:
    script = Path(sql_path).read_text(encoding="utf-8")
    with database.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(script)


def to_jsonb(value: object) -> Any:
    _load_psycopg()
    jsonb_adapter = import_module("psycopg.types.json").Jsonb
    return jsonb_adapter(value)


def _load_psycopg() -> Any:
    try:
        return import_module("psycopg")
    except ModuleNotFoundError as exc:
        raise PostgresDependencyMissingError(
            "psycopg is required for Postgres persistence. Install psycopg before using app.db.postgres."
        ) from exc


def _load_dict_row() -> Any:
    return import_module("psycopg.rows").dict_row
