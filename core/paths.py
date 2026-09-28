from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    configured = (os.environ.get("AERIE_DATA_DIR") or "").strip()
    if configured:
        return Path(configured)
    return project_root() / "data"


def cache_dir() -> Path:
    return data_dir() / "cache"


def briefs_dir() -> Path:
    return data_dir() / "briefs"


def city_cache_path() -> Path:
    return cache_dir() / "city.json"


def plugins_dir() -> Path:
    """已安装功能包（.aeriepack 解包后）的根目录。

    打包态 data_dir 指向 userData/data，插件放同级 userData/plugins：
    免管理员、卸载后仍保留（deleteAppDataOnUninstall:false）。
    开发态落在项目根 plugins/，与源码同级便于调试。
    """
    configured = (os.environ.get("AERIE_PLUGINS_DIR") or "").strip()
    if configured:
        return Path(configured)
    return data_dir().parent / "plugins"


def models_dir() -> Path:
    """随核心分发/全局共享的模型目录；功能包私有模型放在各包自己的 models/ 下。"""
    configured = (os.environ.get("AERIE_MODELS_DIR") or "").strip()
    if configured:
        return Path(configured)
    return project_root() / "models"
