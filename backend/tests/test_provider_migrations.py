from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.migrations import upgrade_database


def test_provider_tables_upgrade_with_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"

    upgrade_database(database_path, alembic_ini)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert {"ai_provider", "ai_model"}.issubset(inspector.get_table_names())
    model_foreign_keys = inspector.get_foreign_keys("ai_model")
    assert model_foreign_keys == [
        {
            "name": "fk_ai_model_provider_id_ai_provider",
            "constrained_columns": ["provider_id"],
            "referred_schema": None,
            "referred_table": "ai_provider",
            "referred_columns": ["id"],
            "options": {"ondelete": "CASCADE"},
        }
    ]


def test_provider_and_model_unique_constraints_reject_duplicates(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    upgrade_database(database_path, alembic_ini)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_provider "
                "(name, provider_type, base_url, enabled, extra_json) "
                "VALUES ('Primary', 'openai_compatible', 'https://example.test/v1', 1, '{}')"
            )
        )
        provider_id = connection.execute(
            text("SELECT id FROM ai_provider WHERE name = 'Primary'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO ai_model "
                "(provider_id, display_name, remote_model, "
                "capabilities_json, defaults_json, enabled) "
                "VALUES (:provider_id, 'Model A', 'model-a', '{}', '{}', 1)"
            ),
            {"provider_id": provider_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_provider "
                "(name, provider_type, base_url, enabled, extra_json) "
                "VALUES ('Primary', 'deepseek', 'https://api.deepseek.com', 1, '{}')"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_model "
                "(provider_id, display_name, remote_model, "
                "capabilities_json, defaults_json, enabled) "
                "VALUES (:provider_id, 'Duplicate', 'model-a', '{}', '{}', 1)"
            ),
            {"provider_id": provider_id},
        )
