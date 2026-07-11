from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import AppConfig
from app.main import create_app


async def test_static_site_serves_assets_and_spa_fallback(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>Clear Sky Engine</h1>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ready')", encoding="utf-8")
    app = create_app(AppConfig.for_local_app_data(tmp_path), static_dir=static_dir)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        index = await client.get("/")
        asset = await client.get("/assets/app.js")
        fallback = await client.get("/worlds/example")
        unknown_api = await client.get("/api/does-not-exist")

    assert index.status_code == 200
    assert index.text == "<h1>Clear Sky Engine</h1>"
    assert asset.status_code == 200
    assert asset.text == "console.log('ready')"
    assert fallback.status_code == 200
    assert fallback.text == index.text
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"].startswith("application/json")
