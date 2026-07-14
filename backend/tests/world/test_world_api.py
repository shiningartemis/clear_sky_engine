from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_sqlite_engine
from app.main import create_app

JPEG_BYTES = b"\xff\xd8\xff\xe0"


def _attribute(
    key: str,
    data_type: str,
    base_value: int | str,
) -> dict[str, object]:
    numeric = data_type in {"integer", "number"}
    return {
        "key": key,
        "display_name": key,
        "data_type": data_type,
        "base_value": base_value,
        "description": f"{key} 的含义",
        "update_rule": f"仅在事件明确改变 {key} 时更新",
        "allowed_operations": (["replace", "increment", "decrement"] if numeric else ["replace"]),
        "minimum": 0 if numeric else None,
        "maximum": 10000 if numeric else None,
        "enum_options": [],
        "update_example": f"事件改变了 {key}",
        "no_update_example": f"事件没有改变 {key}",
    }


def _role_payload(
    name: str,
    *,
    attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "persona": f"{name} 的基础人设",
        "system_prompt": "保持角色自主性",
        "world_book": "天空城居民",
        "attributes": attributes or [],
    }


def _world_payload(role_id: int) -> dict[str, int]:
    return {"protagonist_role_id": role_id}


async def _create_role(
    client: AsyncClient,
    name: str = "天",
    *,
    attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    response = await client.post("/api/roles", json=_role_payload(name, attributes=attributes))
    assert response.status_code == 201, response.text
    payload: dict[str, object] = response.json()
    return payload


def _int_field(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    assert isinstance(value, int)
    return value


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


@asynccontextmanager
async def configured_world_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, int, int]]:
    async with phase3_client(tmp_path, character_assets={"天": "jpg", "莫莉莉": "png"}) as client:
        protagonist = await _create_role(client)
        npc = await _create_role(
            client,
            "莫莉莉",
            attributes=[_attribute("level", "integer", 10)],
        )
        world = await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        assert world.status_code == 201, world.text
        world_id = world.json()["id"]
        role_id = _int_field(npc, "id")
        added = await client.post(f"/api/worlds/{world_id}/roles", json={"role_id": role_id})
        assert added.status_code == 201, added.text
        yield client, world_id, role_id


async def test_create_world_is_atomic_and_uses_system_defaults(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(
            client,
            attributes=[_attribute("level", "integer", 7)],
        )
        response = await client.post(
            "/api/worlds", json=_world_payload(_int_field(protagonist, "id"))
        )

        assert response.status_code == 201, response.text
        world = response.json()
        assert world["display_name"] == f"世界 {world['id']}"
        assert world["weekday"] == "monday"
        assert world["day"] == 1
        assert world["time_slot"] == "morning"
        assert world["player_role"]["name"] == "天"
        assert world["npc_count"] == 0
        assert (await client.get("/api/worlds")).json() == [world]
        refreshed = (await client.get(f"/api/roles/{protagonist['id']}")).json()
        for field in ("persona", "system_prompt", "world_book", "attributes", "version"):
            assert refreshed[field] == protagonist[field]
        assert refreshed["referenced_world_ids"] == [world["id"]]


async def test_same_existing_role_can_be_protagonist_in_multiple_worlds(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(client)

        first = await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        second = await client.post(
            "/api/worlds", json=_world_payload(_int_field(protagonist, "id"))
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["id"] != second.json()["id"]
        refreshed = (await client.get(f"/api/roles/{protagonist['id']}")).json()
        assert refreshed["referenced_world_ids"] == [first.json()["id"], second.json()["id"]]


async def test_world_creation_rejects_unknown_or_assetless_protagonist(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        missing = await client.post("/api/worlds", json=_world_payload(999))
        protagonist = await _create_role(client)
        config = AppConfig.for_local_app_data(tmp_path)
        (config.paths.characters_dir / "天" / "天.jpg").unlink()
        assetless = await client.post(
            "/api/worlds", json=_world_payload(_int_field(protagonist, "id"))
        )

        assert missing.status_code == 404
        assert missing.json()["detail"] == "主角角色不存在"
        assert assetless.status_code == 409
        assert assetless.json()["detail"] == "主角缺少有效的同名默认立绘"
        assert (await client.get("/api/worlds")).json() == []
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM world")).scalar_one() == 0
            assert connection.execute(text("SELECT COUNT(*) FROM world_branch")).scalar_one() == 0
            assert (
                connection.execute(text("SELECT COUNT(*) FROM world_role_state")).scalar_one() == 0
            )
        engine.dispose()


@pytest.mark.parametrize("unexpected", ["world_name", "day", "weekday"])
async def test_world_creation_rejects_client_owned_system_fields(
    tmp_path: Path,
    unexpected: str,
) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(client)
        response = await client.post(
            "/api/worlds",
            json={**_world_payload(_int_field(protagonist, "id")), unexpected: "客户端值"},
        )

    assert response.status_code == 422


async def test_world_creation_rejects_legacy_inline_role_fields(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        response = await client.post(
            "/api/worlds",
            json={"protagonist_name": "天", "protagonist_persona": "谨慎的主角"},
        )

        assert response.status_code == 422
        assert (await client.get("/api/worlds")).json() == []
        assert (await client.get("/api/roles")).json() == []


async def test_forced_player_unique_conflict_rolls_back_every_world_row(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg", "冲突角色": "jpg"}) as client:
        protagonist = await _create_role(client)
        conflict_role = await _create_role(client, "冲突角色")
        conflict_role_id = _int_field(conflict_role, "id")
        config = AppConfig.for_local_app_data(tmp_path)
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER force_player_conflict
                    BEFORE INSERT ON world_role_state
                    WHEN NEW.kind = 'player'
                    BEGIN
                        INSERT INTO world_role_state (
                            world_id, role_id, kind, enabled, change_values_json,
                            version, created_at, updated_at
                        ) VALUES (
                            NEW.world_id, {conflict_role_id}, 'player', 1, '{{}}',
                            1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        );
                    END
                    """
                )
            )

        response = await client.post(
            "/api/worlds", json=_world_payload(_int_field(protagonist, "id"))
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "世界创建冲突"
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM world")).scalar_one() == 0
            assert connection.execute(text("SELECT COUNT(*) FROM world_branch")).scalar_one() == 0
            assert (
                connection.execute(text("SELECT COUNT(*) FROM world_role_state")).scalar_one() == 0
            )
            assert connection.execute(text("SELECT COUNT(*) FROM role")).scalar_one() == 2
        engine.dispose()


async def test_world_role_effective_attributes_are_read_only(tmp_path: Path) -> None:
    async with configured_world_client(tmp_path) as (client, world_id, role_id):
        response = await client.get(f"/api/worlds/{world_id}/roles/{role_id}/effective-attributes")
        patch_response = await client.patch(
            f"/api/worlds/{world_id}/roles/{role_id}/effective-attributes",
            json={"level": 99},
        )

        assert response.status_code == 200
        assert response.json()["values"] == {"level": 10}
        assert patch_response.status_code == 405


async def test_duplicate_npc_and_player_removal_are_conflicts(tmp_path: Path) -> None:
    async with configured_world_client(tmp_path) as (client, world_id, role_id):
        duplicate = await client.post(f"/api/worlds/{world_id}/roles", json={"role_id": role_id})
        world = (await client.get("/api/worlds")).json()[0]
        player_id = world["player_role"]["id"]
        player_removal = await client.delete(f"/api/worlds/{world_id}/roles/{player_id}")

        assert duplicate.status_code == 409
        assert player_removal.status_code == 409


async def test_world_rejects_the_twenty_first_npc(tmp_path: Path) -> None:
    npc_names = [f"NPC{index:02d}" for index in range(1, 22)]
    assets = {"天": "jpg", **dict.fromkeys(npc_names, "jpg")}
    async with phase3_client(tmp_path, character_assets=assets) as client:
        protagonist = await _create_role(client)
        role_ids: list[int] = []
        for name in npc_names:
            role = await client.post("/api/roles", json=_role_payload(name))
            assert role.status_code == 201, role.text
            role_ids.append(role.json()["id"])
        world = await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        world_id = world.json()["id"]
        for role_id in role_ids[:20]:
            added = await client.post(f"/api/worlds/{world_id}/roles", json={"role_id": role_id})
            assert added.status_code == 201, added.text

        rejected = await client.post(
            f"/api/worlds/{world_id}/roles", json={"role_id": role_ids[20]}
        )

        assert rejected.status_code == 409
        world_roles = await client.get(f"/api/worlds/{world_id}/roles")
        assert len(world_roles.json()) == 21


async def test_location_rule_replacement_is_atomic(tmp_path: Path) -> None:
    async with configured_world_client(tmp_path) as (client, world_id, role_id):
        url = f"/api/worlds/{world_id}/roles/{role_id}/location-rules"
        first = await client.put(
            url,
            json=[
                {
                    "weekday_mask": 1,
                    "time_slot": "morning",
                    "mode": "fixed",
                    "priority": 1,
                    "enabled": True,
                    "candidates": [{"location_id": "the_home", "weight": 1}],
                }
            ],
        )
        conflict = await client.put(
            url,
            json=[
                {
                    "weekday_mask": 1,
                    "time_slot": "morning",
                    "mode": "random",
                    "priority": 2,
                    "enabled": True,
                    "candidates": [
                        {"location_id": "the_school", "weight": 1},
                        {"location_id": "the_school", "weight": 2},
                    ],
                }
            ],
        )

        assert first.status_code == 200, first.text
        assert conflict.status_code == 409
        config = AppConfig.for_local_app_data(tmp_path)
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT candidate.location_id
                    FROM character_location_candidate AS candidate
                    JOIN character_location_rule AS rule ON rule.id = candidate.rule_id
                    WHERE rule.world_id = :world_id AND rule.role_id = :role_id
                    """
                ),
                {"world_id": world_id, "role_id": role_id},
            ).scalars()
            assert list(rows) == ["the_home"]
        engine.dispose()


async def test_location_selection_rejects_invalid_id_and_does_not_advance_time(
    tmp_path: Path,
) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(client)
        world = (
            await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        ).json()
        invalid = await client.post(
            f"/api/worlds/{world['id']}/location", json={"location_id": "unknown"}
        )
        selected = await client.post(
            f"/api/worlds/{world['id']}/location", json={"location_id": "the_school"}
        )
        refreshed = (await client.get("/api/worlds")).json()[0]

        assert invalid.status_code == 422
        assert selected.status_code == 200
        assert selected.json()["player_location_id"] == "the_school"
        assert {key: selected.json()[key] for key in ("day", "weekday", "time_slot")} == {
            "day": world["day"],
            "weekday": world["weekday"],
            "time_slot": world["time_slot"],
        }
        assert refreshed["day"] == 1
        assert refreshed["weekday"] == "monday"
        assert refreshed["time_slot"] == "morning"
        config = AppConfig.for_local_app_data(tmp_path)
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.connect() as connection:
            branch = connection.execute(
                text("SELECT current_location_id, state_version FROM world_branch WHERE id = :id"),
                {"id": world["active_branch_id"]},
            ).one()
            assert branch == ("the_school", 2)
        engine.dispose()


async def test_world_map_has_player_marker_and_no_visible_portrait_strip(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(client)
        world = (
            await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        ).json()

        response = await client.get(
            f"/api/worlds/{world['id']}/game-view", params={"scene_id": "the_world_map"}
        )

        assert response.status_code == 200, response.text
        view = response.json()
        assert view["scene_id"] == "the_world_map"
        assert (view["day"], view["weekday"], view["time_slot"]) == (
            1,
            "monday",
            "morning",
        )
        assert view["player_marker_url"].endswith("/%E5%A4%A9/default")
        assert view["visible_roles"] == []
        assert [item["scene_id"] for item in view["locations"]] == [
            "the_home",
            "the_dungeon",
            "the_mall",
            "the_guild",
            "the_hotel",
            "the_school",
        ]


async def test_location_view_contains_only_backend_resolved_visible_roles(tmp_path: Path) -> None:
    assets = {"天": "jpg", "莫莉莉": "png", "安可儿": "png", "离线者": "jpg"}
    async with phase3_client(tmp_path, character_assets=assets) as client:
        protagonist = await _create_role(client)
        npc_ids: list[int] = []
        for name in ("莫莉莉", "安可儿", "离线者"):
            role = await client.post("/api/roles", json=_role_payload(name))
            npc_ids.append(role.json()["id"])
        world = (
            await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        ).json()
        world_id = world["id"]
        for role_id in reversed(npc_ids):
            assert (
                await client.post(f"/api/worlds/{world_id}/roles", json={"role_id": role_id})
            ).status_code == 201
        for role_id, location_id in zip(
            npc_ids,
            ("the_home", "the_home", "the_school"),
            strict=True,
        ):
            assert (
                await client.put(
                    f"/api/worlds/{world_id}/roles/{role_id}/location-rules",
                    json=[
                        {
                            "weekday_mask": 1,
                            "time_slot": "morning",
                            "mode": "fixed",
                            "priority": 1,
                            "enabled": True,
                            "candidates": [{"location_id": location_id, "weight": 1}],
                        }
                    ],
                )
            ).status_code == 200
        assert (
            await client.patch(
                f"/api/worlds/{world_id}/roles/{npc_ids[1]}", json={"enabled": False}
            )
        ).status_code == 200

        response = await client.get(
            f"/api/worlds/{world_id}/game-view", params={"scene_id": "the_home"}
        )

        assert response.status_code == 200, response.text
        visible = response.json()["visible_roles"]
        assert [item["role_id"] for item in visible] == [
            world["player_role"]["id"],
            npc_ids[0],
        ]


async def test_world_deletion_keeps_global_player_role(tmp_path: Path) -> None:
    async with phase3_client(tmp_path, character_assets={"天": "jpg"}) as client:
        protagonist = await _create_role(client)
        world = (
            await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        ).json()
        player_id = world["player_role"]["id"]

        deleted = await client.delete(f"/api/worlds/{world['id']}")

        assert deleted.status_code == 204
        assert (await client.get(f"/api/roles/{player_id}")).status_code == 200
        assert (await client.get("/api/worlds")).json() == []


async def test_effective_attributes_follow_replaced_base_definition_set(tmp_path: Path) -> None:
    initial = [_attribute("level", "integer", 10), _attribute("money", "integer", 1000)]
    async with phase3_client(tmp_path, character_assets={"天": "jpg", "莫莉莉": "png"}) as client:
        protagonist = await _create_role(client)
        npc = await client.post("/api/roles", json=_role_payload("莫莉莉", attributes=initial))
        role_id = npc.json()["id"]
        world = await client.post("/api/worlds", json=_world_payload(_int_field(protagonist, "id")))
        world_id = world.json()["id"]
        await client.post(f"/api/worlds/{world_id}/roles", json={"role_id": role_id})
        config = AppConfig.for_local_app_data(tmp_path)
        engine = create_sqlite_engine(config.paths.database_path)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE world_role_state
                    SET change_values_json = :changes
                    WHERE world_id = :world_id AND role_id = :role_id
                    """
                ),
                {"changes": '{"level": 1, "money": -50}', "world_id": world_id, "role_id": role_id},
            )
        engine.dispose()
        replacement = [
            _attribute("level", "integer", 10),
            _attribute("title", "string", "大魔法师"),
            _attribute("independent_skill", "string", "fire ball"),
        ]
        updated = await client.patch(f"/api/roles/{role_id}", json={"attributes": replacement})
        assert updated.status_code == 200, updated.text

        response = await client.get(f"/api/worlds/{world_id}/roles/{role_id}/effective-attributes")

        assert response.status_code == 200, response.text
        assert response.json()["values"] == {
            "level": 11,
            "title": "大魔法师",
            "independent_skill": "fire ball",
        }
