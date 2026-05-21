"""
Solana Momentum & Wallet Tracker Telegram Bot
Uses DEXScreener API (free, no key needed) + Solana RPC
"""

import asyncio
import aiohttp
import json
import os
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"   # From @BotFather
CHAT_ID        = "YOUR_CHAT_ID"              # Your chat/group ID

# DEXScreener
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"

# Solana RPC (free public endpoint — swap for Helius/QuickNode for production)
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Momentum thresholds
PRICE_CHANGE_THRESHOLD = 20    # % price change in 1h to trigger alert
VOLUME_CHANGE_THRESHOLD = 50   # % volume spike to trigger alert
MIN_LIQUIDITY_USD      = 5000  # Ignore very low liquidity pools

# Wallets to track (add addresses here)
TRACKED_WALLETS = [
    # "WALLET_ADDRESS_1",
    # "WALLET_ADDRESS_2",
]

# Poll interval (seconds)
POLL_INTERVAL = 60

# ── STATE ────────────────────────────────────────────────────────────────────
alerted_tokens  = set()   # Avoid duplicate alerts
last_signatures = {}      # Track last tx per wallet


# ── DEXScreener: Trending Solana Pairs ──────────────────────────────────────
async def fetch_trending_solana(session: aiohttp.ClientSession) -> list:
    """Fetch top Solana pairs from DEXScreener."""
    url = f"{DEXSCREENER_API}/tokens/solana"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("pairs", []) or []
    except Exception as e:
        print(f"[DEXScreener] Error: {e}")
        return []


async def fetch_pair_by_address(session: aiohttp.ClientSession, address: str) -> list:
    """Fetch specific token pairs by contract address."""
    url = f"{DEXSCREENER_API}/tokens/{address}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("pairs", []) or []
    except Exception as e:
        print(f"[DEXScreener] Error fetching {address}: {e}")
        return []


def check_momentum(pair: dict) -> dict | None:
    """Return alert data if token has strong momentum, else None."""
    try:
        chain = pair.get("chainId", "")
        if chain != "solana":
            return None

        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        if liquidity < MIN_LIQUIDITY_USD:
            return None

        price_change = pair.get("priceChange", {})
        h1  = float(price_change.get("h1", 0) or 0)
        h6  = float(price_change.get("h6", 0) or 0)
        h24 = float(price_change.get("h24", 0) or 0)

        volume = pair.get("volume", {})
        vol_h1  = float(volume.get("h1", 0) or 0)
        vol_h24 = float(volume.get("h24", 0) or 0)

        # Volume spike: h1 volume is >50% of daily (active last hour)
        vol_ratio = (vol_h1 / vol_h24 * 100) if vol_h24 > 0 else 0

        triggered = h1 >= PRICE_CHANGE_THRESHOLD or vol_ratio >= VOLUME_CHANGE_THRESHOLD

        if not triggered:
            return None

        return {
            "name":       pair.get("baseToken", {}).get("name", "Unknown"),
            "symbol":     pair.get("baseToken", {}).get("symbol", "???"),
            "address":    pair.get("baseToken", {}).get("address", ""),
            "price_usd":  pair.get("priceUsd", "N/A"),
            "h1":         h1,
            "h6":         h6,
            "h24":        h24,
            "vol_h1":     vol_h1,
            "vol_h24":    vol_h24,
            "vol_ratio":  vol_ratio,
            "liquidity":  liquidity,
            "dex_url":    pair.get("url", ""),
        }
    except Exception:
        return None


def format_momentum_alert(d: dict) -> str:
    """Format a momentum alert message."""
    emoji = "🚀" if d["h1"] > 50 else "📈"
    return (
        f"{emoji} *MOMENTUM ALERT — ${d['symbol']}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Token:* {d['name']} (`{d['address'][:6]}...{d['address'][-4:]}`)\n"
        f"💵 *Price:* ${d['price_usd']}\n"
        f"\n📊 *Price Change*\n"
        f"  • 1h:  `{d['h1']:+.1f}%`\n"
        f"  • 6h:  `{d['h6']:+.1f}%`\n"
        f"  • 24h: `{d['h24']:+.1f}%`\n"
        f"\n💹 *Volume*\n"
        f"  • 1h:  `${d['vol_h1']:,.0f}`\n"
        f"  • 24h: `${d['vol_h24']:,.0f}`\n"
        f"  • 1h is `{d['vol_ratio']:.1f}%` of daily vol\n"
        f"\n💧 *Liquidity:* `${d['liquidity']:,.0f}`\n"
        f"\n🔗 [View on DEXScreener]({d['dex_url']})\n"
        f"⏰ {datetime.utcnow().strftime('%H:%M:%S UTC')}"
    )


# ── Solana RPC: Wallet Tracker ───────────────────────────────────────────────
async def fetch_wallet_transactions(session: aiohttp.ClientSession, wallet: str) -> list:
    """Fetch recent confirmed transactions for a wallet."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [wallet, {"limit": 5}]
    }
    try:
        async with session.post(
            SOLANA_RPC,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
            return data.get("result", []) or []
    except Exception as e:
        print(f"[RPC] Wallet {wallet[:6]}... error: {e}")
        return []


async def fetch_tx_detail(session: aiohttp.ClientSession, sig: str) -> dict | None:
    """Fetch transaction details by signature."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }
    try:
        async with session.post(
            SOLANA_RPC,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
            return data.get("result")
    except Exception:
        return None


def format_wallet_alert(wallet: str, sig: str, tx: dict) -> str:
    """Format a wallet activity alert."""
    slot   = tx.get("slot", "N/A")
    fee    = tx.get("meta", {}).get("fee", 0) / 1e9  # lamports → SOL
    err    = tx.get("meta", {}).get("err")
    status = "✅ Success" if not err else f"❌ Failed"

    sol_url = f"https://solscan.io/tx/{sig}"
    wallet_short = f"{wallet[:6]}...{wallet[-4:]}"

    return (
        f"👛 *WALLET ACTIVITY — `{wallet_short}`*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Status:* {status}\n"
        f"⛽ *Fee:* `{fee:.6f} SOL`\n"
        f"🧱 *Slot:* `{slot}`\n"
        f"🔏 *Sig:* `{sig[:16]}...`\n"
        f"\n🔗 [View on Solscan]({sol_url})\n"
        f"⏰ {datetime.utcnow().strftime('%H:%M:%S UTC')}"
    )


# ── Main Polling Loop ────────────────────────────────────────────────────────
async def polling_loop(bot: Bot):
    """Main loop: check momentum + wallet activity every POLL_INTERVAL seconds."""
    print("[Bot] Polling started...")
    async with aiohttp.ClientSession() as session:
        while True:
            # 1. Momentum scan
            pairs = await fetch_trending_solana(session)
            for pair in pairs:
                alert = check_momentum(pair)
                if alert:
                    token_id = alert["address"]
                    if token_id not in alerted_tokens:
                        alerted_tokens.add(token_id)
                        msg = format_momentum_alert(alert)
                        try:
                            await bot.send_message(
                                chat_id=CHAT_ID,
                                text=msg,
                                parse_mode="Markdown",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            print(f"[Telegram] Send error: {e}")

            # 2. Wallet tracker
            for wallet in TRACKED_WALLETS:
                txs = await fetch_wallet_transactions(session, wallet)
                if not txs:
                    continue

                latest_sig = txs[0]["signature"]
                if last_signatures.get(wallet) == latest_sig:
                    continue  # No new txs

                # New transaction detected
                last_signatures[wallet] = latest_sig
                tx_detail = await fetch_tx_detail(session, latest_sig)
                if tx_detail:
                    msg = format_wallet_alert(wallet, latest_sig, tx_detail)
                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        print(f"[Telegram] Send error: {e}")

            await asyncio.sleep(POLL_INTERVAL)


# ── Telegram Commands ────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Solana Momentum Bot is live!*\n\n"
        "Commands:\n"
        "/start — Show this message\n"
        "/scan <address> — Scan a specific token\n"
        "/addwallet <address> — Track a wallet\n"
        "/wallets — List tracked wallets\n"
        "/status — Bot status",
        parse_mode="Markdown"
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scan <token_address>")
        return
    address = context.args[0]
    await update.message.reply_text(f"🔍 Scanning `{address[:8]}...`", parse_mode="Markdown")
    async with aiohttp.ClientSession() as session:
        pairs = await fetch_pair_by_address(session, address)
        if not pairs:
            await update.message.reply_text("❌ No pairs found for that address.")
            return
        for pair in pairs[:3]:  # Show top 3 pairs
            alert = check_momentum(pair)
            if alert:
                await update.message.reply_text(
                    format_momentum_alert(alert),
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            else:
                p = pair.get("priceChange", {})
                await update.message.reply_text(
                    f"📊 *{pair.get('baseToken',{}).get('symbol','?')}* — No strong momentum right now\n"
                    f"1h: `{p.get('h1',0):+.1f}%` | 24h: `{p.get('h24',0):+.1f}%`\n"
                    f"[DEXScreener]({pair.get('url','')})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )

async def cmd_addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addwallet <solana_address>")
        return
    wallet = context.args[0]
    if wallet not in TRACKED_WALLETS:
        TRACKED_WALLETS.append(wallet)
        await update.message.reply_text(f"✅ Now tracking `{wallet[:6]}...{wallet[-4:]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Already tracking that wallet.")

async def cmd_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not TRACKED_WALLETS:
        await update.message.reply_text("No wallets tracked yet. Use /addwallet <address>")
        return
    lines = [f"`{w[:6]}...{w[-4:]}`" for w in TRACKED_WALLETS]
    await update.message.reply_text(
        "👛 *Tracked Wallets:*\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✅ *Bot is running*\n"
        f"• Alerted tokens: `{len(alerted_tokens)}`\n"
        f"• Tracked wallets: `{len(TRACKED_WALLETS)}`\n"
        f"• Poll interval: `{POLL_INTERVAL}s`\n"
        f"• Momentum threshold: `{PRICE_CHANGE_THRESHOLD}%` (1h)",
        parse_mode="Markdown"
    )


# ── Entry Point ───────────────────────────────────────────────────────────────
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("scan",      cmd_scan))
    app.add_handler(CommandHandler("addwallet", cmd_addwallet))
    app.add_handler(CommandHandler("wallets",   cmd_wallets))
    app.add_handler(CommandHandler("status",    cmd_status))

    # Start polling loop in background
    asyncio.create_task(polling_loop(app.bot))

    print("[Bot] Starting Telegram polling...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
