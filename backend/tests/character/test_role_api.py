from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_sqlite_engine
from app.main import create_app

JPEG_BYTES = b"\xff\xd8\xff\xe0"


def attribute_payload(key: str, data_type: str, base_value: object) -> dict[str, object]:
    return {
        "key": key,
        "display_name": "等级",
        "data_type": data_type,
        "base_value": base_value,
        "description": "角色当前等级",
        "update_rule": "仅在明确升级时更新",
        "allowed_operations": ["replace", "increment", "decrement"],
        "minimum": 1,
        "maximum": 100,
        "enum_options": [],
        "update_example": "完成重要冒险后增加一级",
        "no_update_example": "普通交谈不改变等级",
    }


@asynccontextmanager
async def phase3_client(
    tmp_path: Path,
    *,
    character_assets: dict[str, str] | None = None,
) -> AsyncGenerator[AsyncClient]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    for role_name, extension in (character_assets or {}).items():
        role_dir = config.paths.characters_dir / role_name
        role_dir.mkdir(parents=True, exist_ok=True)
        (role_dir / f"{role_name}.{extension}").write_bytes(JPEG_BYTES)
    app = create_app(config)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        yield client


def _role_payload(name: str = "天") -> dict[str, object]:
    return {
        "name": name,
        "persona": "冷静的冒险者",
        "system_prompt": "保持角色自主性",
        "world_book": "天空城居民",
        "attributes": [attribute_payload("level", "integer", 10)],
    }


async def test_role_crud_keeps_name_immutable_and_returns_typed_attributes(
    tmp_path: Path,
) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        created = await client.post("/api/roles", json=_role_payload())
        assert created.status_code == 201, created.json()
        role = created.json()
        assert role["name"] == "天"
        assert role["attributes"][0]["data_type"] == "integer"
        assert role["effective_base_values"] == {"level": 10}
        assert role["portrait_url"] == "/api/assets/characters/%E5%A4%A9/default"
        assert role["referenced_world_ids"] == []
        assert role["version"] == 1

        fetched = await client.get(f"/api/roles/{role['id']}")
        listed = await client.get("/api/roles")
        assert fetched.status_code == 200
        assert fetched.json() == role
        assert listed.json() == [role]

        updated = await client.patch(
            f"/api/roles/{role['id']}",
            json={
                "persona": "谨慎但坚定",
                "attributes": [attribute_payload("level", "integer", 12)],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "天"
        assert updated.json()["persona"] == "谨慎但坚定"
        assert updated.json()["effective_base_values"] == {"level": 12}
        assert updated.json()["version"] == 2

        immutable_name = await client.patch(f"/api/roles/{role['id']}", json={"name": "新名字"})
        assert immutable_name.status_code == 422


async def test_duplicate_role_name_returns_conflict_without_leaking_database_context(
    tmp_path: Path,
) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        assert (await client.post("/api/roles", json=_role_payload())).status_code == 201

        duplicate = await client.post("/api/roles", json=_role_payload())

        assert duplicate.status_code == 409
        assert duplicate.json() == {"detail": "角色名称已存在"}
        assert "INSERT INTO" not in duplicate.text


async def test_role_requires_a_default_portrait(tmp_path: Path) -> None:
    async with phase3_client(tmp_path) as client:
        response = await client.post("/api/roles", json=_role_payload())

    assert response.status_code == 409


async def test_invalid_attribute_metadata_returns_validation_error(tmp_path: Path) -> None:
    invalid_attribute = attribute_payload("level", "integer", 10)
    invalid_attribute["minimum"] = 20
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        response = await client.post(
            "/api/roles", json={**_role_payload(), "attributes": [invalid_attribute]}
        )

    assert response.status_code == 422


async def test_referenced_role_delete_returns_referencing_world_ids(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        created = await client.post("/api/roles", json=_role_payload())
        role_id = created.json()["id"]
        config = AppConfig.for_local_app_data(tmp_path)
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO world (id, active_branch_id, created_at, updated_at, last_played_at)
                    VALUES (7, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO world_role_state (
                        world_id, role_id, kind, enabled, change_values_json,
                        version, created_at, updated_at
                    ) VALUES (
                        7, :role_id, 'player', 1, '{}', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"role_id": role_id},
            )
        engine.dispose()

        response = await client.delete(f"/api/roles/{role_id}")

        assert response.status_code == 409
        assert response.json()["detail"]["world_ids"] == [7]
        fetched = await client.get(f"/api/roles/{role_id}")
        assert fetched.status_code == 200
        assert fetched.json()["referenced_world_ids"] == [7]


async def test_unreferenced_role_deletes_cleanly(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        created = await client.post("/api/roles", json=_role_payload())
        role_id = created.json()["id"]

        deleted = await client.delete(f"/api/roles/{role_id}")

        assert deleted.status_code == 204
        assert deleted.content == b""
        assert (await client.get(f"/api/roles/{role_id}")).status_code == 404
