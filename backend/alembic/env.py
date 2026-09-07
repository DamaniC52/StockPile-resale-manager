from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- EDIT 1: tell Alembic what the schema SHOULD look like ---------------
#
# `import app.models` looks unused, and linters will say so. It is load-bearing:
# a model class only registers itself into Base.metadata when its module is
# imported. app/models/__init__.py imports all seven, so this one line makes
# every table visible to autogenerate. Without it, Alembic sees empty metadata,
# concludes your tables shouldn't exist, and generates a migration that creates
# nothing -- or, run against a populated database, DROPS everything.
import app.models  # noqa: F401  (imported for its side effect: model registration)
from app.core.config import get_settings
from app.db.base import Base

# THE key line. Autogenerate diffs the live database against this object.
target_metadata = Base.metadata

# --- EDIT 2: read the database URL from Settings, not from alembic.ini ----
#
# alembic.ini is committed to Git, so a real connection string there would be
# committed credentials. And on Render the URL only exists as an environment
# variable at runtime. Reading it from Settings gives ONE source of truth for
# the database URL, shared with the application itself.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect a column's TYPE changing (String(20) -> String(40)).
            # Off by default because type comparison across dialects is fuzzy;
            # on Postgres alone it is reliable and catches real drift.
            compare_type=True,
            # Detect server_default changes. Also off by default, and also
            # worth having -- otherwise editing a DEFAULT in a model silently
            # never reaches the database.
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
