import os
import json
import hashlib
import argparse
import time
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============ CONFIG ============
EXCLUDED_SYMBOLS = ['^NSEI', 'HDFCGOLD.NS', 'NIFTY']
GOLD_NIFTY_SYMBOLS = ['^NSEI', 'HDFCGOLD.NS']
DUPLICATE_WINDOW_HOURS = 12

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')

# ============ DATA FETCHER ============
def fetch_stock_data(symbol, period='1mo', interval='1d'):
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        data = stock.history(period=period, interval=interval)
        return data
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def fetch_nifty_stocks():
    return [
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
        'HINDUNILVR.NS', 'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'KOTAKBANK.NS',
        'LT.NS', 'WIPRO.NS', 'AXISBANK.NS', 'HCLTECH.NS', 'SUNPHARMA.NS',
        'ASIANPAINT.NS', 'TITAN.NS', 'MARUTI.NS', 'ULTRACEMCO.NS', 'BAJFINANCE.NS',
        'NTPC.NS', 'ONGC.NS', 'POWERGRID.NS', 'NESTLEIND.NS', 'M&M.NS',
        'TATASTEEL.NS', 'JSWSTEEL.NS', 'TECHM.NS', 'BAJAJFINSV.NS', 'HDFCLIFE.NS',
        'SBILIFE.NS', 'DRREDDY.NS', 'HINDALCO.NS', 'EICHERMOT.NS', 'COALINDIA.NS',
        'BRITANNIA.NS', 'GRASIM.NS', 'DIVISLAB.NS', 'APOLLOHOSP.NS', 'UPL.NS',
        'SHREECEM.NS', 'CIPLA.NS', 'TATAMOTORS.NS', 'ADANIPORTS.NS', 'ADANIENT.NS',
        'HEROMOTOCO.NS', 'BAJAJ-AUTO.NS', 'INDUSINDBK.NS', 'HDFC.NS', 'ICICIPRULI.NS'
    ]

# ============ INDICATORS ============
def calc_indicators(df):
    if df is None or df.empty:
        return None
    from ta.trend import MACD, EMAIndicator, ADXIndicator
    from ta.momentum import RSIIndicator
    df['EMA_20'] = EMAIndicator(df['Close'], window=20).ema_indicator()
    df['EMA_50'] = EMAIndicator(df['Close'], window=50).ema_indicator()
    df['EMA_200'] = EMAIndicator(df['Close'], window=200).ema_indicator()
    macd = MACD(df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_signal'] = macd.macd_signal()
    df['RSI'] = RSIIndicator(df['Close'], window=14).rsi()
    df['ADX'] = ADXIndicator(df['High'], df['Low'], df['Close'], window=14).adx()
    return df

# ============ SWING SCANNER ============
def swing_scan(symbol, daily_data, weekly_data):
    if daily_data is None or weekly_data is None:
        return None
    daily = calc_indicators(daily_data)
    weekly = calc_indicators(weekly_data)
    if daily is None or weekly is None:
        return None
    d = daily.iloc[-1]
    w = weekly.iloc[-1]
    if d['Close'] > d['EMA_20'] and d['Close'] > d['EMA_50'] and d['MACD'] > d['MACD_signal']:
        if w['Close'] > w['EMA_20'] and w['Close'] > w['EMA_50']:
            return {'symbol': symbol, 'signal': 'BUY', 'price': round(d['Close'], 2), 'rsi': round(d['RSI'], 2), 'adx': round(d['ADX'], 2)}
    if d['Close'] < d['EMA_20'] and d['Close'] < d['EMA_50'] and d['MACD'] < d['MACD_signal']:
        if w['Close'] < w['EMA_20'] and w['Close'] < w['EMA_50']:
            return {'symbol': symbol, 'signal': 'SELL', 'price': round(d['Close'], 2), 'rsi': round(d['RSI'], 2), 'adx': round(d['ADX'], 2)}
    return None

# ============ INTRADAY SCANNER ============
def intraday_scan(symbol, data_15m, data_1h):
    if data_15m is None or data_1h is None:
        return None
    from ta.trend import MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    df15 = data_15m.copy()
    df1h = data_1h.copy()
    df15['EMA_20'] = EMAIndicator(df15['Close'], window=20).ema_indicator()
    df1h['EMA_20'] = EMAIndicator(df1h['Close'], window=20).ema_indicator()
    macd15 = MACD(df15['Close'])
    macd1h = MACD(df1h['Close'])
    df15['MACD'] = macd15.macd()
    df15['MACD_signal'] = macd15.macd_signal()
    df1h['MACD'] = macd1h.macd()
    df1h['MACD_signal'] = macd1h.macd_signal()
    df15['RSI'] = RSIIndicator(df15['Close'], window=14).rsi()
    d15 = df15.iloc[-1]
    d1h = df1h.iloc[-1]
    if d15['MACD'] > d15['MACD_signal'] and d15['RSI'] < 70 and d1h['MACD'] > d1h['MACD_signal']:
        return {'symbol': symbol, 'signal': 'BUY', 'price': round(d15['Close'], 2), 'rsi': round(d15['RSI'], 2)}
    if d15['MACD'] < d15['MACD_signal'] and d15['RSI'] > 30 and d1h['MACD'] < d1h['MACD_signal']:
        return {'symbol': symbol, 'signal': 'SELL', 'price': round(d15['Close'], 2), 'rsi': round(d15['RSI'], 2)}
    return None

# ============ GOLD + NIFTY SCANNER ============
def gold_nifty_scan(symbol, data):
    if data is None or data.empty:
        return None
    from ta.trend import MACD, EMAIndicator, ADXIndicator
    from ta.momentum import RSIIndicator
    df = data.copy()
    df['EMA_20'] = EMAIndicator(df['Close'], window=20).ema_indicator()
    df['EMA_50'] = EMAIndicator(df['Close'], window=50).ema_indicator()
    df['EMA_200'] = EMAIndicator(df['Close'], window=200).ema_indicator()
    df['RSI'] = RSIIndicator(df['Close'], window=14).rsi()
    df['ADX'] = ADXIndicator(df['High'], df['Low'], df['Close'], window=14).adx()
    latest = df.iloc[-1]
    above = sum([latest['Close'] > latest['EMA_20'], latest['Close'] > latest['EMA_50'], latest['Close'] > latest['EMA_200']])
    trend = 'NEUTRAL'
    if above >= 3 and latest['ADX'] > 25:
        trend = 'STRONG_UPTREND'
    elif above >= 2:
        trend = 'UPTREND'
    return {'symbol': symbol, 'trend': trend, 'price': round(latest['Close'], 2), 'rsi': round(latest['RSI'], 2), 'adx': round(latest['ADX'], 2)}

# ============ DUPLICATE CHECK ============
def check_duplicate(symbol, signal, timestamp):
    h = hashlib.md5(f"{symbol}_{signal}_{timestamp.hour//6}".encode()).hexdigest()
    f = f"data/alerts_history/{timestamp.strftime('%Y-%m-%d')}.json"
    if os.path.exists(f):
        with open(f, 'r') as file:
            if h in json.load(file):
                return True
    return False

def save_alert(symbol, signal, timestamp, data):
    h = hashlib.md5(f"{symbol}_{signal}_{timestamp.hour//6}".encode()).hexdigest()
    f = f"data/alerts_history/{timestamp.strftime('%Y-%m-%d')}.json"
    history = {}
    if os.path.exists(f):
        with open(f, 'r') as file:
            history = json.load(file)
    history[h] = {'symbol': symbol, 'signal': signal, 'timestamp': timestamp.isoformat(), 'data': data}
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, 'w') as file:
        json.dump(history, file, indent=2)

# ============ ALERTS ============
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
        return True
    except:
        return False

def send_email(subject, body):
    if not EMAIL_TO or not EMAIL_FROM or not EMAIL_PASSWORD:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = EMAIL_FROM, EMAIL_TO, subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except:
        return False

def format_results(results, scan_type, timestamp):
    if not results:
        return f"📊 {scan_type} - {timestamp}\n\n✅ No signals"
    txt = f"📊 {scan_type} - {timestamp}\n{'='*40}\n\n"
    for r in results:
        if 'trend' in r:
            txt += f"🔹 {r['symbol']}: {r['trend']} | ₹{r['price']} | RSI:{r['rsi']} ADX:{r['adx']}\n"
        else:
            txt += f"🔸 {r['symbol']}: {r['signal']} | ₹{r['price']} | RSI:{r['rsi']}\n"
    txt += f"\n{'='*40}\n⚠️ Educational purpose only"
    return txt

# ============ SCAN FUNCTIONS ============
def run_swing():
    print("🔄 Swing Scan...")
    results = []
    for s in fetch_nifty_stocks():
        if s in EXCLUDED_SYMBOLS: continue
        d = fetch_stock_data(s, '3mo', '1d')
        w = fetch_stock_data(s, '6mo', '1wk')
        r = swing_scan(s, d, w)
        if r and not check_duplicate(s, r['signal'], datetime.now()):
            results.append(r)
            save_alert(s, r['signal'], datetime.now(), r)
        time.sleep(0.3)
    return results

def run_intraday():
    print("🔄 Intraday Scan...")
    results = []
    for s in fetch_nifty_stocks():
        if s in EXCLUDED_SYMBOLS: continue
        d15 = fetch_stock_data(s, '2d', '15m')
        d1h = fetch_stock_data(s, '5d', '1h')
        r = intraday_scan(s, d15, d1h)
        if r and not check_duplicate(s, r['signal'], datetime.now()):
            results.append(r)
            save_alert(s, r['signal'], datetime.now(), r)
        time.sleep(0.3)
    return results

def run_gold():
    print("🔄 NIFTY+Gold Scan...")
    results = []
    for s in GOLD_NIFTY_SYMBOLS:
        d = fetch_stock_data(s, '1mo', '1h')
        r = gold_nifty_scan(s, d)
        if r and not check_duplicate(s, r['trend'], datetime.now()):
            results.append(r)
            save_alert(s, r['trend'], datetime.now(), r)
        time.sleep(0.5)
    return results

# ============ MAIN ============
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', default='scheduled')
    args = parser.parse_args()
    
    ts = datetime.now().strftime('%I:%M %p, %d-%b-%Y')
    ct = datetime.now().strftime('%H:%M')
    
    if args.scan == 'scheduled':
        if ct == '06:00':
            r = run_swing()
            if r:
                msg = format_results(r, 'Swing', ts)
                send_telegram(msg); send_email(f'Swing {ts}', msg)
        elif ct == '06:05':
            r = run_gold()
            if r:
                msg = format_results(r, 'NIFTY+Gold', ts)
                send_telegram(msg); send_email(f'NIFTY+Gold {ts}', msg)
        elif ct in ['09:25','10:30','11:30','12:30','13:30','15:15']:
            r1 = run_intraday()
            r2 = run_gold()
            if r1:
                msg = format_results(r1, 'Intraday', ts)
                send_telegram(msg); send_email(f'Intraday {ts}', msg)
            if r2:
                msg = format_results(r2, 'NIFTY+Gold', ts)
                send_telegram(msg); send_email(f'NIFTY+Gold {ts}', msg)
        elif ct in ['09:30','14:30']:
            r = run_gold()
            if r:
                msg = format_results(r, 'NIFTY+Gold', ts)
                send_telegram(msg); send_email(f'NIFTY+Gold {ts}', msg)
    elif args.scan == 'swing':
        r = run_swing()
        if r:
            msg = format_results(r, 'Swing', ts)
            send_telegram(msg); send_email(f'Swing {ts}', msg)
    elif args.scan == 'intraday':
        r = run_intraday()
        if r:
            msg = format_results(r, 'Intraday', ts)
            send_telegram(msg); send_email(f'Intraday {ts}', msg)
    elif args.scan == 'gold_nifty':
        r = run_gold()
        if r:
            msg = format_results(r, 'NIFTY+Gold', ts)
            send_telegram(msg); send_email(f'NIFTY+Gold {ts}', msg)
    
    print("✅ Done!")

if __name__ == '__main__':
    main()
