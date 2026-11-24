import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from core.config.settings import get_settings
from core.database import Base, create_engine
from modules.conversations import models as _conversation_models  # noqa: F401
from modules.identity import models as _identity_models  # noqa: F401
from modules.knowledge import models as _knowledge_models  # noqa: F401
from modules.usage import models as _usage_models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
