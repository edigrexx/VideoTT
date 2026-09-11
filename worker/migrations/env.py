from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db.models import Base


def run_migrations():
    engine = create_engine(get_settings().db_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
