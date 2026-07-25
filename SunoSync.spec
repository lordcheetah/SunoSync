# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Resolve everything relative to this spec file so the build does not depend on
# the directory PyInstaller happens to be invoked from. Note SPECPATH is already
# the spec's *directory*, not the spec file itself.
SPEC_DIR = os.path.abspath(SPECPATH)

# Collect data needed for customtkinter
datas = []
binaries = []
hiddenimports = ['PIL._tkinter_finder', 'babel.numbers']

# Collect CustomTkinter assets
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Data files shipped inside the bundle. Note that ui/, core/ and services/ are
# deliberately NOT listed here: they are Python packages reached through normal
# imports and are already frozen into the archive. Listing them as `datas` also
# copied the raw .py sources into the exe.
_BUNDLED_DATA = [
    ('assets', 'assets'),
    ('resources', 'resources'),
    ('CHANGELOG.txt', '.'),
]

# Fail loudly at build time rather than shipping an exe with missing resources.
_missing = [src for src, _ in _BUNDLED_DATA if not os.path.exists(os.path.join(SPEC_DIR, src))]
if _missing:
    raise SystemExit(
        "SunoSync.spec: required data path(s) not found: "
        + ", ".join(_missing)
        + "\nBuild aborted so the missing resources are not silently omitted."
    )

_ICON = os.path.join(SPEC_DIR, 'resources', 'icon.ico')

# Packages SunoSync never uses. Without these, building outside a clean venv
# lets PyInstaller follow optional-import probes (sentry_sdk tries to detect
# every framework it can integrate with) into whatever else happens to be
# installed system-wide. On one dev machine that pulled in torch, PySide6,
# scipy and numpy and produced a 396 MB executable instead of ~40 MB.
#
# Build in a clean virtualenv as well — this list is a backstop, not a substitute.
_EXCLUDES = [
    # ML / scientific stacks
    'torch', 'torchvision', 'torchaudio', 'tensorflow', 'jax', 'numpy', 'scipy',
    'pandas', 'sklearn', 'sympy', 'numba', 'llvmlite', 'transformers',
    'huggingface_hub', 'hf_xet', 'safetensors', 'onnx', 'onnxruntime',
    # Other GUI toolkits (SunoSync uses tkinter/customtkinter)
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'shiboken2', 'shiboken6', 'wx', 'kivy',
    # Plotting / imaging we do not use
    'matplotlib', 'seaborn', 'plotly', 'cv2', 'skimage',
    # Notebook / dev tooling
    'IPython', 'jupyter', 'jupyterlab', 'notebook', 'nbconvert', 'nbformat',
    'zmq', 'tornado', 'pytest', '_pytest', 'ruff', 'setuptools', 'pip',
    # Misc heavy transitive deps
    'grpc', 'google', 'boto3', 'botocore', 'selenium', 'playwright',
    'tokenizers', 'pypdfium2', 'pydantic', 'pydantic_core', 'lxml', 'primp',
    'sqlalchemy', 'openai', 'anthropic', 'httpx', 'aiohttp',
]

a = Analysis(
    ['main.py'],
    pathex=[SPEC_DIR],
    binaries=binaries,
    datas=datas + _BUNDLED_DATA,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SunoSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON if os.path.exists(_ICON) else None,
)
