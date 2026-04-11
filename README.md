# 🔍 LinkedIn X-Ray Telegram Bot

A production-ready Telegram bot for **role + location talent discovery**
using automated Google X-ray search via SerpAPI.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🎯 X-ray search | `site:linkedin.com/in` query targeting LinkedIn profiles |
| 🔄 Progressive fallback | Synonyms → broader location → national → fail gracefully |
| 📊 Structured output | Name · Title · Company · LinkedIn URL per result |
| 💾 CSV export | Cumulative per-user export via `/export` |
| ⚡ Async | Full async stack: httpx + python-telegram-bot v20 |
| 🔁 Retry logic | Tenacity-powered retries on API failures |
| 📝 Logging | Rotating log files + coloured console via loguru |
| 🧪 Tests | Pytest unit tests for parser + query builder |

---

## 📁 Project Structure

```
linkedin_bot/
├── main.py                    # Entrypoint — starts the bot
├── config.py                  # Settings loaded from .env
├── models.py                  # Pydantic data models (Person, SearchResult)
├── requirements.txt
├── .env.example               # Copy to .env and fill in your keys
│
├── bot/
│   ├── handlers.py            # Telegram command handlers (/search /export /help)
│   └── formatters.py          # MarkdownV2 message formatting
│
├── scraper/
│   ├── xray_scraper.py        # SerpAPI client + X-ray query builder
│   └── search_service.py      # Orchestrates scraper + parser + storage
│
├── parser/
│   └── linkedin_parser.py     # Extracts Person from Google result snippets
│
├── utils/
│   ├── synonyms.py            # Job-title synonyms + location expansion
│   ├── storage.py             # Async CSV read/write
│   └── logger.py              # Loguru setup
│
├── tests/
│   └── test_parser.py         # Unit tests
│
├── data/                      # CSV files written here (auto-created)
└── logs/                      # Rotating log files (auto-created)
```

---

## 🚀 Quick Start

### 1. Clone and install

```bash
git clone <your-repo>
cd linkedin_bot
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SERPAPI_KEY=abc123def456...
```

**Getting your keys:**

| Key | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot` |
| `SERPAPI_KEY` | Sign up at [serpapi.com](https://serpapi.com) — 100 free searches/month |

### 3. Run

```bash
python main.py
```

You should see:
```
2024-01-15 10:30:00 | INFO     | main:main:55 — Starting LinkedIn X-ray Bot…
2024-01-15 10:30:01 | INFO     | main:main:60 — Bot is running. Press Ctrl+C to stop.
```

### 4. Run tests

```bash
pip install pytest
pytest tests/ -v
```

---

## 💬 Usage

### Search for professionals

```
/search bookkeeper | Birmingham, Alabama
/search software engineer | Austin, TX
/search project manager | Chicago
/search office manager | New York, NY
```

### Export results

```
/export
```

Downloads a CSV with all results from your previous searches.

### Get help

```
/help
```

---

## 📤 Example Output

```
🔍 Search Results
📌 Role: bookkeeper
📍 Location: Birmingham, Alabama
👥 Found: 12 professionals
──────────────────────────────

1. 👤 Sarah Johnson
   💼 Bookkeeper
   🏢 ABC Construction LLC
   🔗 LinkedIn Profile

2. 👤 Michael Chen
   💼 Staff Bookkeeper
   🏢 Regional Healthcare Group
   🔗 LinkedIn Profile

...

📥 Use /export to download results as CSV.
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | required | From @BotFather |
| `SERPAPI_KEY` | required | From serpapi.com |
| `MAX_RESULTS` | 15 | Max people returned per search |
| `SEARCH_PAGES` | 2 | Google pages fetched per query (1 page = 10 results) |
| `REQUEST_DELAY` | 1.0 | Seconds between API calls |
| `DATA_DIR` | data | CSV export directory |
| `LOG_LEVEL` | INFO | DEBUG / INFO / WARNING / ERROR |

---

## 🔍 How X-Ray Search Works

The bot builds Google queries that force results from LinkedIn profile pages:

```
site:linkedin.com/in ("bookkeeper" OR "accounts payable" OR "accounts receivable") "Birmingham, Alabama"
```

**Fallback escalation (automatic):**

| Level | Strategy |
|---|---|
| 0 | Exact title + exact location |
| 1 | Title + synonyms + exact location |
| 2 | Title + synonyms + state/country only |
| 3 | Title + synonyms (no location filter) |
| 4 | Return "no results" message |

---

## 🛡️ Rate Limits & Ethics

- SerpAPI free tier: **100 searches/month** → upgrade for production use
- The bot adds a configurable delay between API calls (`REQUEST_DELAY`)
- Only public LinkedIn profile data visible in Google snippets is used
- No direct LinkedIn scraping — all data is from Google's index

---

## 🔧 Extending the Bot

**Add new job title synonyms:**
Edit `utils/synonyms.py` → `TITLE_SYNONYMS` dict.

**Support a different search API:**
Replace `SerpAPIClient` in `scraper/xray_scraper.py` — the `search()` method
just needs to return a list of dicts with `link`, `title`, `snippet` keys.

**Add a database backend:**
Replace `utils/storage.py` — swap the CSV writer for SQLAlchemy / motor.

---

## 📦 Deployment

### systemd (Linux VPS)

```ini
# /etc/systemd/system/linkedin-bot.service
[Unit]
Description=LinkedIn X-Ray Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/linkedin_bot
ExecStart=/home/ubuntu/linkedin_bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable linkedin-bot
sudo systemctl start linkedin-bot
sudo journalctl -u linkedin-bot -f
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t linkedin-bot .
docker run -d --env-file .env --name linkedin-bot linkedin-bot
```
