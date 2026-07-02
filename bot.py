#!/usr/bin/env python3
"""
bot.py - Bot de TELEGRAM para Termux: ofuscador (Prometheus) + embellecedor
de Lua ("deofuscador" de mejor esfuerzo).

CONFIGURACIÓN DEL TOKEN
------------------------
Nunca pongas el token directo en este archivo ni lo subas a git.
Se lee de la variable de entorno BOT_TOKEN, o de un archivo .env local
(ambos ignorados por git vía .gitignore).

    export BOT_TOKEN="tu_token_aca"
    python bot.py

Requisitos: pkg install python lua51 git   /   pip install -r requirements.txt
"""

import time
import traceback
from pathlib import Path

import telebot
from telebot import types

import core
from lua_beautify import beautify

TOKEN = core.load_token("BOT_TOKEN")
if not TOKEN:
    raise SystemExit(
        "No encontré BOT_TOKEN. Definilo con `export BOT_TOKEN=...` "
        "o creá un archivo .env (mirá .env.example)."
    )

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# Estado en memoria por usuario.
pending = {}   # user_id -> {"path", "workdir", "name"}
intent = {}    # user_id -> "obf" | "deobf", fijado por /obfuscar o /deofuscar

WELCOME = (
    "🤖 *Bot Ofuscador / Embellecedor de Lua*\n\n"
    "Mandame un archivo `.lua` directo, o usá primero un comando:\n\n"
    "🔒 `/obfuscar` — el próximo `.lua` que mandes se ofusca con Prometheus "
    "(elegís preset: Minify/Weak/Medium/Strong).\n"
    "🔓 `/deofuscar` — el próximo `.lua` que mandes se embellece "
    "(reformatea + renombra variables de forma heurística).\n\n"
    "Si mandás el archivo sin comando previo, te pregunto con botones qué "
    "querés hacer.\n\n"
    "⚠️ Importante: `/deofuscar` NO revierte cifrado de strings ni deshace "
    "una máquina virtual (Vmify, presets Medium/Strong). Eso no es "
    "reversible de forma genérica para ningún ofuscador serio — solo mejora "
    "la lectura de código minificado o poco ofuscado."
)


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.reply_to(message, WELCOME, parse_mode="Markdown")


@bot.message_handler(commands=["obfuscar", "ofuscar"])
def cmd_obfuscar(message):
    intent[message.from_user.id] = "obf"
    bot.reply_to(message, "🔒 Listo, mandame el archivo `.lua` que querés ofuscar.", parse_mode="Markdown")


@bot.message_handler(commands=["deofuscar", "desofuscar"])
def cmd_deofuscar(message):
    intent[message.from_user.id] = "deobf"
    bot.reply_to(
        message,
        "🔓 Listo, mandame el archivo `.lua` que querés embellecer.\n"
        "Recordá: esto NO revierte cifrado de strings ni una VM (Vmify).",
        parse_mode="Markdown",
    )


@bot.message_handler(content_types=["document"])
def handle_document(message):
    doc = message.document
    if not doc.file_name.lower().endswith(".lua"):
        bot.reply_to(message, "Mandame un archivo con extensión .lua, porfa.")
        return
    if doc.file_size and doc.file_size > core.MAX_FILE_SIZE:
        bot.reply_to(message, "El archivo es muy grande (límite 2 MB).")
        return

    workdir = core.make_workdir()
    local_name = core.safe_filename(doc.file_name)
    local_path = workdir / local_name

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        local_path.write_bytes(downloaded)
    except Exception as e:
        core.cleanup(workdir)
        bot.reply_to(message, f"No pude descargar el archivo: {e}")
        return

    pending[message.from_user.id] = {"path": local_path, "workdir": workdir, "name": local_name}
    user_intent = intent.pop(message.from_user.id, None)

    if user_intent == "deobf":
        bot.reply_to(message, f"Recibí `{local_name}`. Embelleciendo...", parse_mode="Markdown")
        run_deobfuscate(message.chat.id, message.from_user.id)
        return

    if user_intent == "obf":
        kb = types.InlineKeyboardMarkup()
        kb.row(*[types.InlineKeyboardButton(p, callback_data=f"preset:{p}") for p in core.PRESETS])
        bot.reply_to(
            message,
            f"Recibí `{local_name}`. Elegí el preset de ofuscación:",
            reply_markup=kb,
            parse_mode="Markdown",
        )
        return

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🔒 Ofuscar", callback_data="mode:obf"),
        types.InlineKeyboardButton("🔓 Embellecer", callback_data="mode:deobf"),
    )
    bot.reply_to(message, f"Recibí `{local_name}`. ¿Qué querés hacer?", reply_markup=kb, parse_mode="Markdown")


def run_deobfuscate(chat_id, user_id):
    state = pending.get(user_id)
    if not state:
        bot.send_message(chat_id, "No tengo ningún archivo pendiente tuyo, mandá uno de nuevo.")
        return
    try:
        src = state["path"].read_text(encoding="utf-8", errors="replace")
        pretty, rename_map, _report = beautify(src)
        out_path = state["workdir"] / f"embellecido_{state['name']}"
        out_path.write_text(pretty, encoding="utf-8")
        with open(out_path, "rb") as f:
            bot.send_document(
                chat_id,
                f,
                caption=f"✅ Listo. Variables renombradas: {len(rename_map)}.\n"
                f"Recordá: esto es formato + renombrado heurístico, no revierte "
                f"cifrado de strings ni una VM (Vmify).",
            )
    except Exception as e:
        bot.send_message(chat_id, f"Error al embellecer: {e}")
        traceback.print_exc()
    finally:
        core.cleanup(state["workdir"])
        pending.pop(user_id, None)


@bot.callback_query_handler(func=lambda c: c.data == "mode:deobf")
def cb_deobf(call):
    user_id = call.from_user.id
    if user_id not in pending:
        bot.answer_callback_query(call.id, "No tengo ningún archivo pendiente tuyo, mandá uno de nuevo.")
        return
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    run_deobfuscate(call.message.chat.id, user_id)


@bot.callback_query_handler(func=lambda c: c.data == "mode:obf")
def cb_obf(call):
    user_id = call.from_user.id
    if user_id not in pending:
        bot.answer_callback_query(call.id, "No tengo ningún archivo pendiente tuyo, mandá uno de nuevo.")
        return
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.row(*[types.InlineKeyboardButton(p, callback_data=f"preset:{p}") for p in core.PRESETS])
    bot.edit_message_text(
        "Elegí el preset de ofuscación:\n\n"
        "• *Minify* — solo compacta y renombra, no protege mucho.\n"
        "• *Weak* — array de constantes + wrap.\n"
        "• *Medium* — cifra strings + VM + anti-tamper (recomendado).\n"
        "• *Strong* — todo lo anterior + doble Vmify (más lento en runtime).",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("preset:"))
def cb_preset(call):
    user_id = call.from_user.id
    state = pending.get(user_id)
    if not state:
        bot.answer_callback_query(call.id, "No tengo ningún archivo pendiente tuyo, mandá uno de nuevo.")
        return
    preset = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id, f"Ofuscando con preset {preset}...")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    out_path = state["workdir"] / f"{Path(state['name']).stem}.obfuscated.lua"
    try:
        core.run_prometheus(state["path"], preset, out_path)
        with open(out_path, "rb") as f:
            bot.send_document(
                call.message.chat.id,
                f,
                caption=f"✅ Ofuscado con preset *{preset}*.",
                parse_mode="Markdown",
            )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ {e}")
        traceback.print_exc()
    finally:
        core.cleanup(state["workdir"])
        pending.pop(user_id, None)


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    if message.text.startswith("/"):
        return
    bot.reply_to(message, "Mandame un archivo .lua para ofuscar o embellecer. Usá /start para ver el menú.")


def main():
    if not core.LUA_BIN:
        print(
            "[AVISO] No se detectó un runtime de Lua (lua5.1/luajit). "
            "El modo Ofuscar va a fallar hasta que instales uno:\n"
            "    pkg install lua51\n"
        )
    print(f"Bot de Telegram corriendo. Runtime Lua detectado: {core.LUA_BIN or 'NINGUNO'}")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"[ERROR] polling caído, reintentando en 5s: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
