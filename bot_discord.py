#!/usr/bin/env python3
"""
bot_discord.py - Bot de DISCORD para Termux: ofuscador (Prometheus) +
embellecedor de Lua ("deofuscador" de mejor esfuerzo).

Usa slash commands. En Discord podés adjuntar el archivo directo como
parámetro del comando, así que no hace falta el paso de "mandá el archivo
y después elegí qué hacer" como en la versión de Telegram.

CONFIGURACIÓN DEL TOKEN
------------------------
Nunca pongas el token directo en este archivo ni lo subas a git.
Se lee de la variable de entorno DISCORD_TOKEN, o de un archivo .env local.

    export DISCORD_TOKEN="tu_token_aca"
    python bot_discord.py

Requisitos:
    pkg install python lua51 git
    pip install -r requirements-discord.txt

Para invitar al bot a tu server necesitás también el "Application ID" y
generar un link de invitación con los scopes `bot` + `applications.commands`
desde el Developer Portal (https://discord.com/developers/applications).
"""

import io
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import core
from lua_beautify import beautify

TOKEN = core.load_token("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit(
        "No encontré DISCORD_TOKEN. Definilo con `export DISCORD_TOKEN=...` "
        "o creá un archivo .env (mirá .env.example)."
    )

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


async def _read_attachment(attachment: discord.Attachment):
    if not attachment.filename.lower().endswith(".lua"):
        raise ValueError("El archivo tiene que tener extensión .lua")
    if attachment.size and attachment.size > core.MAX_FILE_SIZE:
        raise ValueError("El archivo es muy grande (límite 2 MB).")
    return await attachment.read()


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Bot de Discord conectado como {bot.user}. Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"[AVISO] no pude sincronizar slash commands: {e}")
    if not core.LUA_BIN:
        print(
            "[AVISO] No se detectó un runtime de Lua (lua5.1/luajit). "
            "El comando /obfuscar va a fallar hasta que instales uno:\n"
            "    pkg install lua51\n"
        )


@bot.tree.command(name="ayuda", description="Muestra cómo usar el bot")
async def ayuda(interaction: discord.Interaction):
    msg = (
        "**Bot Ofuscador / Embellecedor de Lua**\n\n"
        "🔒 `/obfuscar archivo:<tu .lua> preset:<Minify|Weak|Medium|Strong>` "
        "— ofusca de verdad con Prometheus.\n"
        "🔓 `/deofuscar archivo:<tu .lua>` — reformatea + renombra variables "
        "de forma heurística.\n\n"
        "⚠️ `/deofuscar` NO revierte cifrado de strings ni deshace una "
        "máquina virtual (Vmify, presets Medium/Strong). Eso no es "
        "reversible de forma genérica para ningún ofuscador serio."
    )
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="obfuscar", description="Ofusca un archivo .lua con Prometheus")
@app_commands.describe(archivo="Archivo .lua a ofuscar", preset="Preset de ofuscación")
@app_commands.choices(
    preset=[app_commands.Choice(name=p, value=p) for p in core.PRESETS]
)
async def obfuscar(interaction: discord.Interaction, archivo: discord.Attachment, preset: app_commands.Choice[str] = None):
    await interaction.response.defer(thinking=True)
    preset_name = preset.value if preset else "Medium"

    try:
        data = await _read_attachment(archivo)
    except ValueError as e:
        await interaction.followup.send(f"❌ {e}")
        return

    workdir = core.make_workdir()
    local_name = core.safe_filename(archivo.filename)
    local_path = workdir / local_name
    local_path.write_bytes(data)
    out_path = workdir / f"{local_path.stem}.obfuscated.lua"

    try:
        core.run_prometheus(local_path, preset_name, out_path)
        await interaction.followup.send(
            content=f"✅ Ofuscado con preset **{preset_name}**.",
            file=discord.File(str(out_path), filename=out_path.name),
        )
    except Exception as e:
        await interaction.followup.send(f"❌ {e}")
        traceback.print_exc()
    finally:
        core.cleanup(workdir)


@bot.tree.command(name="deofuscar", description="Embellece un .lua (reformatea + renombra variables, best-effort)")
@app_commands.describe(archivo="Archivo .lua a embellecer")
async def deofuscar(interaction: discord.Interaction, archivo: discord.Attachment):
    await interaction.response.defer(thinking=True)

    try:
        data = await _read_attachment(archivo)
    except ValueError as e:
        await interaction.followup.send(f"❌ {e}")
        return

    try:
        src = data.decode("utf-8", errors="replace")
        pretty, rename_map, _report = beautify(src)
        buf = io.BytesIO(pretty.encode("utf-8"))
        out_name = f"embellecido_{core.safe_filename(archivo.filename)}"
        await interaction.followup.send(
            content=(
                f"✅ Listo. Variables renombradas: {len(rename_map)}.\n"
                f"Recordá: esto es formato + renombrado heurístico, no revierte "
                f"cifrado de strings ni una VM (Vmify)."
            ),
            file=discord.File(buf, filename=out_name),
        )
    except Exception as e:
        await interaction.followup.send(f"❌ {e}")
        traceback.print_exc()


def main():
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
