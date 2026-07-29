"""Additive schema repair for databases created by an older release.

``create_all()`` and ``Table.create(checkfirst=True)`` never add columns to a
table that already exists, so a deploy whose tables predate a newer model keeps
serving the old shape until the missing columns are ALTERed in. That is exactly
how Streamlit Cloud broke: `alerts` was created from the pre-Slice-B model and
every query touching Alert.user_id failed with UndefinedColumn.

The columns to add are derived from the ORM metadata rather than hand-listed —
a hand-maintained list silently goes stale the moment someone adds a field to a
model, which is how `portfolio_holdings.sip_amount` came to be missing from the
original repair.

Runs on SQLite and Postgres, and records what happened so the UI can show why a
repair failed rather than leaving a downstream UndefinedColumn as the only clue.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Table

from database import session as db_session
from utils.logging_config import get_logger

logger = get_logger(__name__)

SUPPORTED_DIALECTS = ("sqlite", "postgresql")


def existing_columns(table: str) -> Optional[set[str]]:
    """Columns currently on `table`, or None if reflection itself failed."""
    from sqlalchemy import inspect

    try:
        return {c["name"] for c in inspect(db_session.engine).get_columns(table)}
    except Exception:
        return None


def _render_default(default: Any) -> str:
    """DDL DEFAULT clause for a scalar, portable across SQLite and Postgres."""
    # bool before int — bool is a subclass of int, and Postgres rejects
    # BOOLEAN DEFAULT 0.
    if isinstance(default, bool):
        return f" DEFAULT {'TRUE' if default else 'FALSE'}"
    if isinstance(default, (int, float)):
        return f" DEFAULT {default}"
    if isinstance(default, str):
        return " DEFAULT '{}'".format(default.replace("'", "''"))
    return ""


def column_specs(table: Table, dialect: Any) -> list[tuple[str, str]]:
    """``(name, DDL type)`` for every addable column on `table`.

    Primary keys are skipped — they cannot be added to a populated table. Only
    the bare column is emitted; foreign-key and unique constraints are not
    retrofitted (SQLite cannot add them at all).
    """
    specs: list[tuple[str, str]] = []
    for col in table.columns:
        if col.primary_key:
            continue
        typedef = col.type.compile(dialect=dialect)
        arg = getattr(col.default, "arg", None) if col.default is not None else None
        # Callable defaults (datetime.utcnow) are applied by the ORM on insert.
        if arg is not None and not callable(arg):
            typedef += _render_default(arg)
        specs.append((col.name, typedef))
    return specs


def _probe_postgres(report: dict[str, Any], table_names: list[str]) -> None:
    """Record which database/role/schema the repair is actually touching.

    A repair that ALTERs a table in a different schema than the one queries
    resolve to looks like a silent no-op, so make that visible.
    """
    from sqlalchemy import text

    for key, stmt in (
        ("current_database", "SELECT current_database()"),
        ("current_user", "SELECT current_user"),
        ("search_path", "SHOW search_path"),
    ):
        try:
            with db_session.engine.connect() as conn:
                report[key] = conn.execute(text(stmt)).scalar()
        except Exception as exc:
            report[key] = f"<{type(exc).__name__}>"

    for table in table_names:
        try:
            with db_session.engine.connect() as conn:
                report[f"{table}_in_schemas"] = [
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT table_schema FROM information_schema.tables"
                            " WHERE table_name = :t"
                        ),
                        {"t": table},
                    )
                ]
        except Exception as exc:
            report["notes"].append(f"locate {table}: {type(exc).__name__}: {exc}")


def ensure_tables(*tables: Table, label: str = "schema") -> dict[str, Any]:
    """Create `tables` if absent, then add any columns missing from existing ones.

    Returns a report of the attempt. Failures are logged at warning/error and
    recorded — never swallowed.
    """
    from sqlalchemy import inspect, text

    engine = db_session.engine
    dialect = engine.dialect.name
    report: dict[str, Any] = {
        "dialect": dialect,
        "database": engine.url.database,
        "added": [],
        "failed": [],
        "still_missing": [],
        "notes": [],
    }

    for table in tables:
        try:
            table.create(bind=engine, checkfirst=True)
        except Exception as exc:
            report["notes"].append(f"create {table.name}: {type(exc).__name__}: {exc}")

    if dialect not in SUPPORTED_DIALECTS:
        report["notes"].append(f"no column repair for dialect {dialect!r}")
        return report

    if dialect == "postgresql":
        _probe_postgres(report, [t.name for t in tables])

    for table in tables:
        name = table.name
        existing = existing_columns(name)
        if existing is None:
            try:
                if not inspect(engine).has_table(name):
                    report["notes"].append(f"{name}: table absent, nothing to repair")
                    continue
            except Exception:
                pass
        report[f"{name}_before"] = sorted(existing) if existing is not None else "<unreadable>"

        specs = column_specs(table, engine.dialect)
        for col, typedef in specs:
            # When reflection failed, attempt the ALTER anyway rather than
            # skipping the repair on the strength of a failed lookup.
            if existing is not None and col in existing:
                continue
            if dialect == "postgresql":
                sql = f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS {col} {typedef}"
            else:
                sql = f"ALTER TABLE {name} ADD COLUMN {col} {typedef}"
            # One transaction per ALTER: on Postgres a failed statement aborts
            # the enclosing transaction, poisoning every later ALTER.
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
                report["added"].append(f"{name}.{col}")
                logger.info("[{}] added missing column {}.{}", label, name, col)
            except Exception as exc:
                detail = f"{name}.{col}: {type(exc).__name__}: {exc}"
                report["failed"].append(detail)
                logger.warning("[{}] schema repair failed — {}", label, detail)

        after = existing_columns(name)
        if after is not None:
            missing = [c for c, _ in specs if c not in after]
            if missing:
                report["still_missing"].extend(f"{name}.{m}" for m in missing)
                logger.error(
                    "[{}] schema repair incomplete on {} — still missing: {}",
                    label,
                    name,
                    ", ".join(missing),
                )

    return report
