# Solana Momentum & Wallet Tracker Bot

Telegram bot that monitors Solana tokens via DEXScreener and tracks wallet activity via Solana RPC.

---

## Setup (5 minutes)

### 1. Get a Telegram Bot Token
1. Open Telegram → search `@BotFather`
2. Send `/newbot` and follow the steps
3. Copy the token (looks like `123456:ABC-DEF...`)

### 2. Get Your Chat ID
1. Start a chat with your bot
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Copy the `"id"` value under `"chat"`

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure the Bot
Open `bot.py` and set:
```python
TELEGRAM_TOKEN = "your_token_here"
CHAT_ID        = "your_chat_id_here"
```

### 5. (Optional) Add Wallets to Track
```python
TRACKED_WALLETS = [
    "WALLET_ADDRESS_1",
    "WALLET_ADDRESS_2",
]
```
Or use the `/addwallet` command while the bot is running.

### 6. Run It
```bash
python bot.py
```

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/scan <address>` | Scan a specific token by contract address |
| `/addwallet <address>` | Start tracking a Solana wallet |
| `/wallets` | List all tracked wallets |
| `/status` | Show bot stats |

---

## Momentum Thresholds (edit in bot.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `PRICE_CHANGE_THRESHOLD` | 20% | 1h price change to trigger alert |
| `VOLUME_CHANGE_THRESHOLD` | 50% | % of daily volume in last 1h |
| `MIN_LIQUIDITY_USD` | $5,000 | Ignore pools below this liquidity |
| `POLL_INTERVAL` | 60s | How often to check DEXScreener |

---

## Upgrade Tips

- **Better RPC**: Replace `api.mainnet-beta.solana.com` with [Helius](https://helius.dev) or [QuickNode](https://quicknode.com) for higher rate limits
- **Persist alerted tokens**: Save `alerted_tokens` to a file or SQLite so alerts survive restarts
- **Filter by DEX**: Add a check for `pair.get("dexId") == "raydium"` to only alert Raydium pairs
- **Deploy 24/7**: Run on a cheap VPS (DigitalOcean $4/mo, Railway, or Render)

---

## APIs Used
- [DEXScreener API](https://docs.dexscreener.com/) — Free, no key needed
- [Solana JSON RPC](https://docs.solana.com/api/http) — Free public endpoint
