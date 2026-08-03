from pathlib import Path


viewer_root = Path(SPECPATH)

analysis = Analysis(
    [str(viewer_root / "launcher.py")],
    pathex=[str(viewer_root / "src")],
    binaries=[],
    datas=[
        (str(viewer_root.parent / "LegendManager" / "data" / "jp_v2_4_presets.json"), "legend_data"),
        (str(viewer_root.parent / "LegendManager" / "data" / "tags_catalog.json"), "legend_data"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.Qt3D", "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtPdf", "PySide6.QtPositioning", "PySide6.QtQuick", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine", "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="LegendViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
