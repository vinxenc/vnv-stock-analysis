"""Print the latest daily price of one VN stock as a JSON line.

Usage: python3 -I scripts/vn_stock_latest_price.py <SYMBOL>   (or set env SYMBOL)
Sources tried in order: DNSE -> VPS -> VNDirect. Prices are in thousand VND.
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
VN = timezone(timedelta(hours=7))
KEYS = ("date", "open", "high", "low", "close", "volume")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.load(r)


def tv_last(d):  # DNSE and VPS share the TradingView-style layout
    i = -1
    return (datetime.fromtimestamp(d["t"][i], VN).strftime("%Y-%m-%d"),
            d["o"][i], d["h"][i], d["l"][i], d["c"][i], d["v"][i])


def dnse(sym):
    now = int(time.time())
    return tv_last(get(f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from={now - 86400 * 10}&to={now}&symbol={sym}&resolution=1D"))


def vps(sym):
    now = int(time.time())
    return tv_last(get(f"https://histdatafeed.vps.com.vn/tradingview/history?symbol={sym}&resolution=1D&from={now - 86400 * 10}&to={now}"))


def vndirect(sym):
    r = get(f"https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date:desc&q=code:{sym}&size=1")["data"][0]
    # ad* = adjusted for dividends/splits, matching DNSE and VPS
    return (r["date"], r["adOpen"], r["adHigh"], r["adLow"], r["adClose"], r["nmVolume"])


if __name__ == "__main__":
    sym = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SYMBOL", "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{1,10}", sym):  # the symbol goes into URLs: reject "FPT#x", "FPT&y=1"
        sys.exit("usage: vn_stock_latest_price.py <SYMBOL>  (letters/digits, max 10)")
    errors = []
    for name, fn in (("DNSE", dnse), ("VPS", vps), ("VNDirect", vndirect)):
        try:
            row = fn(sym)
            print(json.dumps({"symbol": sym, "source": name, "unit": "thousand VND",
                              **dict(zip(KEYS, (row[0], *row[1:5], int(row[5]))))}))
            sys.exit()
        except Exception as e:  # IndexError/KeyError from empty data (unknown ticker) land here too
            errors.append(f"{name}: {type(e).__name__}: {e}")
    sys.exit("All sources failed:\n" + "\n".join(errors))
