"""
core.py - lógica compartida entre bot.py (Telegram) y bot_discord.py (Discord).

Contiene todo lo que NO depende de la plataforma de chat:
- localizar el runtime de Lua
- correr Prometheus
- manejo de carpetas temporales
- constantes (presets, límites de tamaño)
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROMETHEUS_DIR = BASE_DIR / "Prometheus-master"
PROMETHEUS_CLI = PROMETHEUS_DIR / "cli.lua"

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
LUA_RUNTIME_CANDIDATES = ["lua5.1", "luajit", "lua5.3", "lua5.4", "lua"]
PRESETS = ["Minify", "Weak", "Medium", "Strong"]


def find_lua_runtime():
    for candidate in LUA_RUNTIME_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    return None


LUA_BIN = find_lua_runtime()


def load_token(env_var, dotenv_key=None):
    """Lee un token desde variable de entorno o desde .env (fallback)."""
    token = os.environ.get(env_var)
    if token:
        return token.strip()
    dotenv_key = dotenv_key or env_var
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{dotenv_key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def make_workdir():
    return Path(tempfile.mkdtemp(prefix="luabot_"))


def cleanup(path: Path):
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    if not name.endswith(".lua"):
        name += ".lua"
    return name


def run_prometheus(input_path: Path, preset: str, out_path: Path):
    if not LUA_BIN:
        raise RuntimeError(
            "No hay ningún runtime de Lua instalado (lua5.1 / luajit). "
            "Instalá uno con: pkg install lua51"
        )
    if preset not in PRESETS:
        raise ValueError(f"Preset inválido: {preset}. Opciones: {', '.join(PRESETS)}")
    cmd = [
        LUA_BIN,
        str(PROMETHEUS_CLI),
        "--preset",
        preset,
        "--out",
        str(out_path),
        str(input_path),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(PROMETHEUS_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Prometheus falló (código {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    if not out_path.exists():
        raise RuntimeError(
            "Prometheus terminó pero no generó el archivo de salida.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
