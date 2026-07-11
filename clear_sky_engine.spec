from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path.cwd()
data_files = [
    (str(project_root / "alembic.ini"), "."),
    (str(project_root / "backend" / "migrations"), "backend/migrations"),
    (
        str(project_root / "backend" / "src" / "app" / "static"),
        "backend/src/app/static",
    ),
]
data_files += collect_data_files("alembic")

analysis = Analysis(
    [str(project_root / "backend" / "src" / "app" / "launcher.py")],
    pathex=[str(project_root / "backend" / "src")],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["alembic.testing", "pytest", "pysqlite2", "MySQLdb", "tzdata"],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ClearSkyEngine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClearSkyEngine",
)
