"""Small helpers shared by the model files. Not a table."""

from sqlalchemy import DateTime

# Every timestamp is timestamptz, so "days since last practised" never depends
# on the server's or your laptop's time zone. The aging math itself lives in
# rating.py, so the pure model and the ORM share one implementation.
TZ = DateTime(timezone=True)


def one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a text-enum CHECK: "source IN ('a', 'b')".

    Text + CHECK instead of a Postgres ENUM, so adding a value later is a
    one-line migration instead of ALTER TYPE.
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"
