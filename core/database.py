import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import DB_PATH

logger = logging.getLogger(__name__)

Base = declarative_base()

engine = create_engine(DB_PATH, echo=False, connect_args={"check_same_thread": False})


# mode wal evite les verrous avec plusieurs thread
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # L'import enregistre les modèles sur Base.metadata : sans lui create_all()
    # ne crée aucune table si core.models n'a pas déjà été importé ailleurs.
    import core.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _purge_music()


# Colonnes apparues après coup, par table.
_LATER_COLUMNS = {
    "medias": {
        "series_overview": "VARCHAR",
        "still_path": "VARCHAR",
        "actors": "VARCHAR",
    },
    "downloads": {
        "extracted_to": "VARCHAR",
    },
}


def _add_missing_columns():
    """Ajoute les colonnes apparues après la création d'une base existante.

    create_all() ne fait rien sur une table déjà présente : sans ceci, une base
    d'avant l'ajout de `still_path` provoquerait « no such column » à la première
    requête.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table, columns in _LATER_COLUMNS.items():
            if table not in tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name in existing:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                )
                logger.info(f"Database migrated: added {table}.{name}")


def _purge_music():
    """Retire les traces de l'ancienne prise en charge audio.

    Les morceaux indexés par les versions précédentes ne sont plus affichables :
    on les supprime, ainsi que les tables de playlists devenues sans objet.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "medias" in tables:
            result = connection.execute(
                text("DELETE FROM medias WHERE media_type = 'music'")
            )
            if result.rowcount:
                logger.info(f"Removed {result.rowcount} music item(s) from the library")

        for table in ("playlist_items", "playlists"):
            if table in tables:
                connection.execute(text(f"DROP TABLE {table}"))
                logger.info(f"Dropped obsolete table: {table}")
