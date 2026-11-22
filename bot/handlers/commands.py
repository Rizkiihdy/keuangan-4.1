"""
Command handlers — thin Telegram command handlers.

Each handler:
1. Extracts data from the Telegram Update
2. Registers the user
3. Delegates ALL logic to Brain
4. Sends Brain's response back to Telegram

No business logic lives here. No AI calls. No Sheet calls.
All of that is Brain's responsibility.
"""

from __future__ import annotations

import logging
import re

from telegram import Update, BotCommand
from telegram.ext import ContextTypes

from brain.brain import Brain
from utils.security import require_auth
from utils.formatting import fname
from config import (
    BOT_NAME, EXPENSE_CATEGORIES, INCOME_CATEGORIES,
    DAFTAR_AKUN, AKUN_KEYWORDS,
)

logger = logging.getLogger(__name__)


def _register(user, chat_id: int, registry: dict, save_fn) -> None:
    """Register user in the user registry if not already present."""
    key = str(chat_id)
    if key not in registry:
        registry[key] = {
            "first_name": user.first_name or "Kak",
            "full_name": user.full_name or "",
        }
        save_fn(registry)


# ------------------------------------------------------------------ #
# HANDLERS                                                             #
# ------------------------------------------------------------------ #

@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = fname(user)
    ctx: dict = context.bot_data
    _register(user, update.effective_chat.id, ctx.get("registry", {}), ctx.get("save_reg", lambda _: None))
    await update.message.reply_text(
        f"Halo *{name}!* 👋 Aku *{BOT_NAME}*.\n\n"
        "Aku fokus untuk mencatat keuanganmu:\n"
        "• Pengeluaran — _beli kopi 15rb_\n"
        "• Pemasukan — _gajian 5 juta_\n"
        "• Transfer — _transfer 100rb dari BCA ke GoPay_\n"
        "• Scan struk — kirim foto struk yang jelas.\n\n"
        "Semua transaksi akan masuk ke Google Sheets. 📝",
        parse_mode="Markdown",
    )
@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


@require_auth
async def ringkasan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = fname(user)
    await update.message.reply_text(f"Bentar {name}, aku rekap dulu... 📊")
    brain = Brain.get_instance()
    response = await brain.process_command_ringkasan(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def saldo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    brain = Brain.get_instance()
    response = await brain.process_command_saldo(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def hariini_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    brain = Brain.get_instance()
    response = await brain.process_command_hariini(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def mingguini_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    brain = Brain.get_instance()
    response = await brain.process_command_mingguini(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def terbesar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    brain = Brain.get_instance()
    response = await brain.process_command_terbesar(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    await update.message.reply_text(f"Bentar {name}, aku ambil transaksi terakhir... 📋")
    brain = Brain.get_instance()
    response = await brain.process_command_terakhir(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def analisa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    await update.message.reply_text(f"🔍 Bentar ya {name}, Oliv lagi baca transaksi kamu...")
    brain = Brain.get_instance()
    response = await brain.process_command_analisa(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def budget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    await update.message.reply_text(f"Bentar {name}, aku cek budget bulan ini... 💰")
    brain = Brain.get_instance()
    response = await brain.process_command_budget(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def tanya(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    if not context.args:
        await update.message.reply_text(
            f"Tanya apa nih, {name}? 🤔\n\n"
            f"Cara pakainya: `/tanya <pertanyaanmu>`\n\n"
            f"Contoh: `/tanya berapa total makan bulan ini?`",
            parse_mode="Markdown",
        )
        return
    question = " ".join(context.args)
    await update.message.reply_text(f"Hmm, biar aku pikirin dulu {name}... 🤔💭")
    brain = Brain.get_instance()
    response = await brain.process_command_tanya(update.effective_chat.id, name, question)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def networth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    brain = Brain.get_instance()
    response = await brain.process_command_networth(update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def forecast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """End-of-month spending forecast — pure Python, no AI."""
    name = fname(update.effective_user)
    from engine.financial import FinancialEngine
    from sheets import get_semua_transaksi
    try:
        txns = get_semua_transaksi()
        forecast = FinancialEngine.forecast_month_end(txns)
        confidence_label = {"high": "Tinggi ✅", "medium": "Sedang 🟡", "low": "Rendah ⚠️"}.get(
            forecast.confidence, forecast.confidence
        )
        await update.message.reply_text(
            f"🔮 *Prediksi Akhir Bulan*\n\n"
            f"📅 Hari berlalu: {forecast.days_elapsed} / sisa {forecast.days_remaining} hari\n"
            f"💸 Pengeluaran sejauh ini: `{_rp(forecast.expense_so_far)}`\n"
            f"📊 Proyeksi pengeluaran bulan ini: `{_rp(forecast.projected_expense)}`\n"
            f"💰 Pemasukan sejauh ini: `{_rp(forecast.income_so_far)}`\n"
            f"{'🟢' if forecast.projected_net >= 0 else '🔴'} Proyeksi net: `{_rp(forecast.projected_net)}`\n\n"
            f"_Akurasi prediksi: {confidence_label}_",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Forecast error: {e}")
        await update.message.reply_text(f"Aduh {name}, gagal hitung prediksi nih. 😓")


@require_auth
async def pengeluaran(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    args = context.args

    if not args or len(args) < 2:
        cats = ", ".join(EXPENSE_CATEGORIES[:6]) + ", ..."
        await update.message.reply_text(
            f"Cara pakainya, {name}:\n"
            f"`/pengeluaran <jumlah> <kategori> [memo] [payee] [akun]`\n\n"
            f"Contoh: `/pengeluaran 45000 \"Makan & Minum\" Kopi \"Kopi Kenangan\" gopay`\n\n"
            f"Kategori: _{cats}_\n\n"
            f"💡 _Atau langsung ketik: \"beli makan 45 ribu\"_",
            parse_mode="Markdown",
        )
        return

    try:
        jumlah = float(str(args[0]).replace(".", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text(f"Jumlahnya harus angka ya {name} 😄")
        return

    # Parse category (may be multi-word)
    kategori = None
    remaining = []
    if args[1] in EXPENSE_CATEGORIES:
        kategori = args[1]
        remaining = args[2:]
    else:
        for i in range(1, len(args)):
            candidate = " ".join(args[1:i + 1])
            if candidate in EXPENSE_CATEGORIES:
                kategori = candidate
                remaining = args[i + 1:]
                break

    if not kategori:
        await update.message.reply_text(f"Kategori nggak ketemu ya {name} 😅")
        return

    memo, payee, akun = "-", "-", "Cash"
    for arg in remaining:
        al = arg.lower()
        if arg in DAFTAR_AKUN or any(al == a.lower() for a in DAFTAR_AKUN):
            akun = arg
        elif len(arg) > 15 or " " in arg:
            payee = arg
        else:
            memo = arg
    if memo == "-" and remaining:
        memo = remaining[0]

    brain = Brain.get_instance()
    response = await brain.process_command_manual_pengeluaran(
        update.effective_chat.id, name, jumlah, kategori, memo, payee, akun
    )
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def pemasukan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    args = context.args

    if not args or len(args) < 2:
        await update.message.reply_text(
            f"Cara pakainya, {name}:\n"
            f"`/pemasukan <jumlah> <kategori> [memo] [payee] [akun]`\n\n"
            f"Contoh: `/pemasukan 5000000 Gaji Gaji \"Gaji Juni 2026\" bca`\n\n"
            f"Kategori: Gaji, Bonus, Dividen, Usaha, Lain-lain\n\n"
            f"💡 _Atau langsung ketik: \"gajian 5 juta\"_",
            parse_mode="Markdown",
        )
        return

    try:
        jumlah = float(str(args[0]).replace(".", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text(f"Jumlahnya harus angka ya {name} 😄")
        return

    kategori = args[1]
    memo, payee, akun = "-", "-", "Cash"
    for arg in args[2:]:
        if arg in DAFTAR_AKUN:
            akun = arg
        elif len(arg) > 15:
            payee = arg
        else:
            memo = arg

    brain = Brain.get_instance()
    response = await brain.process_command_manual_pemasukan(
        update.effective_chat.id, name, jumlah, kategori, memo, payee, akun
    )
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


# ------------------------------------------------------------------ #
# INVESTMENT, UTANG, GOALS, ASET — thin wrappers (Sheet-only, no AI) #
# ------------------------------------------------------------------ #

@require_auth
async def invest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    args = context.args
    if not args or len(args) < 5:
        await update.message.reply_text(
            f"Cara pakai: `/invest <akun> <jenis> <nama> <lot> <harga_beli> [broker] [ket]`\n\n"
            f"Akun: 1 / 2 / 3\nContoh: `/invest 1 saham BBCA 100 8500 RTI beli pagi`",
            parse_mode="Markdown",
        )
        return
    akun_no = args[0]
    if akun_no not in ("1", "2", "3"):
        await update.message.reply_text("Akun harus 1, 2, atau 3!")
        return
    sheet_name = f"Account{akun_no}"
    jenis, nama, lot_str, harga_str = args[1], args[2], args[3], args[4]
    try:
        lot = float(lot_str.replace(",", ""))
        harga = float(harga_str.replace(",", ""))
    except ValueError:
        await update.message.reply_text("Lot dan harga harus angka ya!")
        return
    total = int(lot * harga)
    broker = args[5] if len(args) > 5 else "-"
    ket = " ".join(args[6:]) if len(args) > 6 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("investasi", sheet_name)
    mgr.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Jenis": jenis, "Nama": nama,
        "Jumlah Lot": lot, "Harga Beli": harga, "Total": total, "Broker": broker, "Keterangan": ket,
    })
    await update.message.reply_text(
        f"✅ *Investasi Tercatat di Account {akun_no}!*\n"
        f"{nama} ({jenis}) — {lot} lot x {_rp(harga)} = {_rp(total)}\nBroker: {broker}",
        parse_mode="Markdown",
    )


@require_auth
async def dividen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = fname(update.effective_user)
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            f"Cara pakai: `/dividen <akun> <nama_saham> <jumlah> [broker] [ket]`\n\nContoh: `/dividen 1 BBCA 125000`",
            parse_mode="Markdown",
        )
        return
    akun_no = args[0]
    if akun_no not in ("1", "2", "3"):
        await update.message.reply_text("Akun harus 1, 2, atau 3!")
        return
    nama, jml_str = args[1], args[2]
    try:
        jml = float(jml_str.replace(",", ""))
    except ValueError:
        await update.message.reply_text("Jumlah harus angka ya!")
        return
    broker = args[3] if len(args) > 3 else "-"
    ket = " ".join(args[4:]) if len(args) > 4 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("investasi", f"Account{akun_no}")
    mgr.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Nama": nama,
        "Jumlah Lot": "", "Harga Beli": "", "Total": jml,
        "Broker": broker, "Keterangan": f"Dividen — {ket}",
    })
    await update.message.reply_text(
        f"💰 *Dividen Tercatat di Account {akun_no}!*\n{nama} — {_rp(jml)}\nBroker: {broker}",
        parse_mode="Markdown",
    )


@require_auth
async def jual_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 6:
        await update.message.reply_text(
            f"Cara pakai: `/jual <akun> <jenis> <nama> <lot> <harga_beli> <harga_jual> [broker]`",
            parse_mode="Markdown",
        )
        return
    akun_no = args[0]
    if akun_no not in ("1", "2", "3"):
        await update.message.reply_text("Akun harus 1, 2, atau 3!")
        return
    jenis, nama, lot_str, hb_str, hj_str = args[1], args[2], args[3], args[4], args[5]
    try:
        lot = float(lot_str.replace(",", ""))
        hb = float(hb_str.replace(",", ""))
        hj = float(hj_str.replace(",", ""))
    except ValueError:
        await update.message.reply_text("Semua angka harus valid ya!")
        return
    pl = int((hj - hb) * lot)
    broker = args[6] if len(args) > 6 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("investasi", f"Account{akun_no}")
    mgr.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Jenis": jenis, "Nama": nama,
        "Jumlah Lot": -lot, "Harga Beli": hb, "Total": int(lot * hj),
        "Broker": broker, "Keterangan": f"Jual — Profit/Loss: {_rp(pl)}",
    })
    emoji = "🟢" if pl >= 0 else "🔴"
    await update.message.reply_text(
        f"{emoji} *Realisasi Tercatat di Account {akun_no}!*\n{nama} — {lot} lot\n"
        f"Beli: {_rp(hb)} → Jual: {_rp(hj)}\nProfit/Loss: {_rp(pl)}",
        parse_mode="Markdown",
    )


@require_auth
async def utang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    name = fname(update.effective_user)
    if not args or len(args) < 2:
        await update.message.reply_text(
            f"Cara pakai: `/utang <nama> <jumlah> [jatuh_tempo] [ket]`\nContoh: `/utang John 500000 2026-07-15`",
            parse_mode="Markdown",
        )
        return
    nama = args[0]
    try:
        jml = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Jumlah harus angka!")
        return
    jt = args[2] if len(args) > 2 else "-"
    ket = " ".join(args[3:]) if len(args) > 3 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("utang", "Sheet1")
    mgr.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Nama": nama,
        "Jumlah": jml, "Status": "Belum Lunas", "Jatuh Tempo": jt, "Keterangan": ket,
    })
    await update.message.reply_text(
        f"📋 *Utang Tercatat!*\n{nama} — {_rp(jml)}\nJatuh tempo: {jt}",
        parse_mode="Markdown",
    )


@require_auth
async def piutang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            f"Cara pakai: `/piutang <nama> <jumlah> [jatuh_tempo] [ket]`",
            parse_mode="Markdown",
        )
        return
    nama = args[0]
    try:
        jml = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Jumlah harus angka!")
        return
    jt = args[2] if len(args) > 2 else "-"
    ket = " ".join(args[3:]) if len(args) > 3 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("utang", "Sheet1")
    mgr.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Nama": nama,
        "Jumlah": jml, "Status": "Belum Diterima", "Jatuh Tempo": jt, "Keterangan": ket,
    })
    await update.message.reply_text(
        f"📋 *Piutang Tercatat!*\n{nama} — {_rp(jml)}\nJatuh tempo: {jt}",
        parse_mode="Markdown",
    )


@require_auth
async def goal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            f"Cara pakai: `/goal <nama_goal> <target_jumlah> <deadline> [ket]`\n"
            f"Contoh: `/goal 'Motor Baru' 15000000 2026-12-31`",
            parse_mode="Markdown",
        )
        return
    try:
        target = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Target jumlah harus angka!")
        return
    deadline = args[2]
    ket = " ".join(args[3:]) if len(args) > 3 else "-"
    from sheets_manager import get_manager
    mgr = get_manager("keuangan", "Goals")
    mgr.append_row({
        "Nama Goal": args[0], "Target Jumlah": target, "Terkumpul": 0,
        "Deadline": deadline, "Status": "Aktif", "Keterangan": ket,
    })
    await update.message.reply_text(
        f"🎯 *Goal Baru!*\n{args[0]} — Target: {_rp(target)}\nDeadline: {deadline}",
        parse_mode="Markdown",
    )


@require_auth
async def tabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    name = fname(update.effective_user)
    if not args or len(args) < 2:
        await update.message.reply_text(
            f"Cara pakai: `/tabung <nama_goal> <jumlah>`\nContoh: `/tabung 'Motor Baru' 2500000`",
            parse_mode="Markdown",
        )
        return
    nama_goal = args[0]
    try:
        jml = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Jumlah harus angka!")
        return
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr_goals = get_manager("keuangan", "Goals")
    rows = mgr_goals.get_all_rows()
    goal = next((r for r in rows if r.get("Nama Goal") == nama_goal), None)
    if not goal:
        await update.message.reply_text(f"Goal '{nama_goal}' nggak ketemu nih. Cek dulu ya!")
        return
    try:
        terkumpul = float(goal.get("Terkumpul", 0)) + jml
    except ValueError:
        terkumpul = jml
    mgr_prog = get_manager("keuangan", "Progress")
    mgr_prog.append_row({
        "Tanggal": now_wib().strftime("%Y-%m-%d"), "Nama Goal": nama_goal,
        "Jumlah Masuk": jml, "Saldo Goal": terkumpul,
    })
    await update.message.reply_text(
        f"💰 *Tabungan Masuk!*\n{nama_goal} +{_rp(jml)}\nTotal terkumpul: {_rp(terkumpul)}",
        parse_mode="Markdown",
    )


@require_auth
async def aset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            f"Cara pakai: `/aset <nama> <jenis> <nilai_beli> [nilai_sekarang] [ket]`",
            parse_mode="Markdown",
        )
        return
    nama, jenis = args[0], args[1]
    try:
        nilai_beli = float(args[2].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Nilai beli harus angka!")
        return
    nilai_now = float(args[3].replace(",", "")) if len(args) > 3 else nilai_beli
    ket = " ".join(args[4:]) if len(args) > 4 else "-"
    from sheets import now_wib
    from sheets_manager import get_manager
    mgr = get_manager("keuangan", "Aset")
    mgr.append_row({
        "Nama Aset": nama, "Jenis": jenis, "Nilai Beli": nilai_beli,
        "Nilai Sekarang": nilai_now, "Tanggal Beli": now_wib().strftime("%Y-%m-%d"),
        "Keterangan": ket,
    })
    await update.message.reply_text(
        f"🏠 *Aset Tercatat!*\n{nama} ({jenis})\nBeli: {_rp(nilai_beli)}\nSekarang: {_rp(nilai_now)}",
        parse_mode="Markdown",
    )


@require_auth
async def list_sheets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sheets_manager import list_spreadsheets, list_sheets
    lines = ["📊 *Spreadsheet yang tersedia:*\n"]
    for key, spec in list_spreadsheets():
        lines.append(f"\n*{key}* — `{spec['name']}`")
        for sh in list_sheets(key):
            lines.append(f"  • {sh}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def post_init(app) -> None:
    """Set bot commands in Telegram."""
    commands = [
        BotCommand("start", "Mulai bot Oliv"),
        BotCommand("help", "Bantuan & daftar perintah"),
        BotCommand("pengeluaran", "Catat pengeluaran manual"),
        BotCommand("pemasukan", "Catat pemasukan manual"),
        BotCommand("ringkasan", "Ringkasan keuangan bulan ini"),
        BotCommand("saldo", "Cek saldo semua akun"),
        BotCommand("hariini", "Pengeluaran hari ini"),
        BotCommand("mingguini", "7 hari terakhir"),
        BotCommand("terbesar", "Top 10 pengeluaran"),
        BotCommand("analisa", "Analisa pola keuangan (AI)"),
        BotCommand("budget", "Status budget bulan ini"),
        BotCommand("terakhir", "10 transaksi terakhir"),
        BotCommand("tanya", "Tanya Oliv soal keuangan (AI)"),
        BotCommand("networth", "Snapshot net worth"),
        BotCommand("forecast", "Prediksi pengeluaran akhir bulan"),
        BotCommand("invest", "Catat investasi/beli saham"),
        BotCommand("dividen", "Catat dividen diterima"),
        BotCommand("jual", "Catat jual investasi"),
        BotCommand("utang", "Catat utang"),
        BotCommand("piutang", "Catat piutang"),
        BotCommand("goal", "Buat target tabungan"),
        BotCommand("tabung", "Nabung ke goal"),
        BotCommand("aset", "Catat pembelian aset"),
        BotCommand("sheets", "Lihat semua spreadsheet"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands set.")


def _rp(amount) -> str:
    return "Rp " + f"{float(amount):,.0f}".replace(",", ".")
