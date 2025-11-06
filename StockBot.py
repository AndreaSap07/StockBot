import threading
import time
import yfinance as yf
from datetime import date, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import matplotlib.pyplot as plt
import io



# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

STOCKS = {
    "NVDA": {"upper": 130.0, "lower": 110.0, "pct_trigger": 2.0},
    "SPY": {"upper": 550.0, "lower": 520.0, "pct_trigger": 1.5},
    "AAPL": {"upper": 200.0, "lower": 160.0, "pct_trigger": 2.0},
    "TSLA": {"upper": 300.0, "lower": 220.0, "pct_trigger": 3.0},
    "AMZN": {"upper": 190.0, "lower": 160.0, "pct_trigger": 2.5},
}

CHECK_INTERVAL = 300  # seconds (5 minutes)


# === PRICE HELPERS ===
def get_price(symbol):
    data = yf.Ticker(symbol)
    hist = data.history(period="1d")
    if hist.empty:
        return None
    return hist["Close"].iloc[-1]


def get_prev_close(symbol):
    data = yf.Ticker(symbol)
    hist = data.history(period="2d")
    if len(hist) < 2:
        return None
    return hist["Close"].iloc[-2]


def pct_change(now, then):
    return ((now - then) / then * 100) if (now and then) else None


# === REPORTING ===
def get_stock_report(symbol):
    today = date.today()
    ticker = yf.Ticker(symbol)

    def get_price_on(days_ago):
        d = today - timedelta(days=days_ago)
        hist = ticker.history(start=d - timedelta(days=1), end=d)
        if len(hist) == 0:
            return None
        return hist["Close"].iloc[-1]

    prices = {
        "today": get_price_on(0),
        "1d": get_price_on(1),
        "1w": get_price_on(7),
        "1m": get_price_on(30),
        "1y": get_price_on(365),
    }

    def fmt_change(now, then):
        c = pct_change(now, then)
        return f"{c:+.2f}%" if c is not None else "N/A"

    today_price = prices["today"]
    today_str = f"${today_price:.2f}" if today_price else "N/A"

    return f"""
*{symbol}*
💰 Today: {today_str}
🕐 1D: {fmt_change(prices['today'], prices['1d'])}
📅 1W: {fmt_change(prices['today'], prices['1w'])}
🗓️ 1M: {fmt_change(prices['today'], prices['1m'])}
📆 1Y: {fmt_change(prices['today'], prices['1y'])}
""".strip()


def generate_full_report():
    message = f"📊 *Daily Stock Report* ({date.today().strftime('%d %b %Y')})\n\n"
    reports = [get_stock_report(s) for s in STOCKS.keys()]
    message += "\n\n".join(reports)
    return message


# === TELEGRAM COMMAND ===
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(generate_full_report(), parse_mode="Markdown")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /chart SYMBOL\nExample: /chart NVDA")
        return

    symbol = context.args[0].upper()
    await send_stock_chart(symbol, update.message.chat_id)



# === BACKGROUND THREAD FOR PRICE CHECKING ===
def monitor_prices(bot):
    while True:
        try:
            for symbol, limits in STOCKS.items():
                price = get_price(symbol)
                prev = get_prev_close(symbol)
                if not price or not prev:
                    continue

                change = pct_change(price, prev)
                print(f"{symbol}: ${price:.2f} ({change:+.2f}%)")

                # Price threshold alerts
                if price >= limits["upper"]:
                    bot.send_message(chat_id=CHAT_ID,
                                     text=f"🚀 *{symbol}* crossed upper threshold!\nCurrent: ${price:.2f}",
                                     parse_mode="Markdown")
                elif price <= limits["lower"]:
                    bot.send_message(chat_id=CHAT_ID,
                                     text=f"⚠️ *{symbol}* dropped below threshold!\nCurrent: ${price:.2f}",
                                     parse_mode="Markdown")

                # % change alerts
                if abs(change) >= limits["pct_trigger"]:
                    direction = "up" if change > 0 else "down"
                    bot.send_message(chat_id=CHAT_ID,
                                     text=f"📈 *{symbol}* moved {direction} by {change:+.2f}% since yesterday.\nCurrent: ${price:.2f}",
                                     parse_mode="Markdown")

            # Daily report at 17:00
            now = time.strftime("%H:%M")
            if now == "17:00":
                bot.send_message(chat_id=CHAT_ID, text=generate_full_report(), parse_mode="Markdown")
                time.sleep(60)

        except Exception as e:
            print("Error in monitor thread:", e)

        time.sleep(CHECK_INTERVAL)

async def send_stock_chart(symbol: str, chat_id: str):
    data = yf.download(symbol, period="6mo", interval="1d")  # last 6 months
    if data.empty:
        await bot.send_message(chat_id, f"⚠️ No data available for {symbol}")
        return

    prices = data['Close']
    ma20 = prices.rolling(window=20).mean()
    ma50 = prices.rolling(window=50).mean()

    plt.figure(figsize=(10, 5))
    plt.plot(prices.index, prices.values, label="Close Price")
    plt.plot(ma20.index, ma20.values, label="20-Day MA")
    plt.plot(ma50.index, ma50.values, label="50-Day MA")
    plt.title(f"{symbol} Price (Last 6 Months)")
    plt.xlabel("Date")
    plt.ylabel("Price ($)")
    plt.legend()
    plt.grid(True)


    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    await bot.send_photo(chat_id=chat_id, photo=buffer)


# === MAIN ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add command
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("chart", chart))


    # Start background monitoring thread
    bot = app.bot
    threading.Thread(target=monitor_prices, args=(bot,), daemon=True).start()

    print("✅ Stock tracker bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
