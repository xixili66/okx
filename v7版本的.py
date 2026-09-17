from __future__ import annotations

import os
import sys
import time
import re
import traceback
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from math import sqrt, log
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import okx.Account as Account
    import okx.Funding as Funding
    import okx.MarketData as MarketData
    import okx.PublicData as PublicData
    import okx.Trade as Trade
    from okx.consts import GET, POST, TICKERS_INFO, TICKER_INFO, MARKET_CANDLES, INSTRUMENT_INFO, ACCOUNT_INFO, ORDER_INFO, PLACR_ORDER, GET_BALANCES
except ImportError:
    print("请先执行: pip install python-okx --upgrade")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("请先执行: pip install requests")
    sys.exit(1)


# ==============================================
# 全局配置
# ==============================================
DEBUG_TRADE = True

MAX_POSITION_RATIO = Decimal("0.25")
BUY_BALANCE_RATIO = Decimal("0.985")
MIN_TRADE_USDT = Decimal("0.01")
MIN_PROFIT_RATIO = 0.003

ADX_PERIOD = 12
ADX_WEAK, ADX_MODERATE, ADX_STRONG = 15.0, 22.0, 30.0
CORR_BLOCK, CORR_REDUCE = 0.85, 0.70
BB_PERIOD, BB_MULT = 20, 2.0
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
KDJ_N, KDJ_M1, KDJ_M2 = 9, 3, 3
OBV_LOOKBACK = 5

AGGRESSIVE_PICK_N = 10
AGGRESSIVE_MIN_VOL_USDT = 500000.0
AGGRESSIVE_REFRESH_ROUNDS = 3
AGGRESSIVE_COOLDOWN_ROUNDS = 3
AGGRESSIVE_BATCH_SIZE = 100
AGGRESSIVE_TARGET_POOL = 20
AGGRESSIVE_MIN_CAND_SCORE = 55.0
AGGRESSIVE_WEIGHTS = {
    "momentum": 0.25, "rsi": 0.20, "adx": 0.20,
    "volume": 0.15, "bollinger": 0.10, "volatility": 0.10,
}

STOP_LOSS_ATR_MULT = 1.2
BREAK_EVEN_ATR_MULT = 0.8
TRAILING_STEPS = [(0.03, 0.015), (0.08, 0.025), (float("inf"), 0.04)]
AGGR_STOP_LOSS_ATR = 1.5
AGGR_BREAK_EVEN_ATR = 1.0
AGGR_TRAILING_STEPS = [(0.05, 0.02), (0.15, 0.03), (float("inf"), 0.05)]
AGGR_TAKE_PROFIT_RSI = 78
AGGR_TAKE_PROFIT_BB = 0.97
AGGR_TAKE_PROFIT_KDJ = 105
AGGR_PARTIAL_TAKE_ATR = 2.0

MAX_HOLD_HOURS = 72
MIN_ATR_RATIO = 0.0005
COLLECT_MIN_VALUE_USDT = Decimal("5")
COLLECT_INTERVAL_ROUNDS = 5
RETRY_TIMES = 2
RETRY_DELAY = 1
IP_REFRESH_ROUNDS = 30

TD_MODE = "cash"


# ==============================================
# 控制台
# ==============================================
def init_console():
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        s = k.GetStdHandle(-10)
        m = ctypes.c_ulong()
        k.GetConsoleMode(s, ctypes.byref(m))
        m.value &= ~0x0040
        k.SetConsoleMode(s, m)
        k.SetConsoleOutputCP(65001)
    except Exception:
        pass


def set_utf8_io():
    for s in (sys.stdout, sys.stderr):
        try:
            if getattr(s, "encoding", "").lower() not in {"utf-8", "utf8"}:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ==============================================
# 基础工具
# ==============================================
def fmt(v):
    try:
        t = format(v, "f")
        return t.rstrip("0").rstrip(".") if "." in t else t
    except Exception:
        return "0"


def rd(v, step):
    try:
        if step <= 0:
            return v
        return (v / step).to_integral_value(rounding=ROUND_DOWN) * step
    except Exception:
        return Decimal("0")


def clamp(v, lo, hi):
    return max(lo, min(v, hi))


def sf(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (ValueError, TypeError, InvalidOperation):
        return default


def sd(v, default=Decimal("0")):
    try:
        if v is None or v == "":
            return default
        return Decimal(str(v))
    except (ValueError, TypeError, InvalidOperation):
        return default


def sinput(prompt, default=""):
    try:
        v = input(prompt).strip()
        return v if v else default
    except (EOFError, KeyboardInterrupt):
        return default


def norm(s):
    return s.strip().upper().replace("_", "-")


def dbg(*args):
    if DEBUG_TRADE:
        print("    [DEBUG]", *args)


def make_oid(prefix="x"):
    ms = int(time.time() * 1000)
    return f"{prefix}{ms}"[:32]


# ==============================================
# 网络工具
# ==============================================
def detect_proxy():
    import socket
    for p in [7890, 7891, 7897, 10808, 10809, 1080, 8888, 8118]:
        for h in ["127.0.0.1", "localhost"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                r = s.connect_ex((h, p))
                s.close()
                if r == 0:
                    return f"http://{h}:{p}"
            except Exception:
                pass
    return None


def get_public_ip(proxy=None, timeout=5):
    urls = ["https://api.ipify.org?format=json", "https://ipinfo.io/json"]
    px = {"http": proxy, "https": proxy} if proxy else None
    for u in urls:
        try:
            r = requests.get(u, proxies=px, timeout=timeout)
            if r.status_code != 200:
                continue
            try:
                d = r.json()
                for k in ("ip", "query", "IPv4", "origin"):
                    if k in d:
                        v = str(d[k]).split(",")[0].strip()
                        if v:
                            return v
            except Exception:
                pass
            m = re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", r.text)
            if m:
                return m.group(0)
        except Exception:
            continue
    return "未知"


def set_title(ip, extra=""):
    if os.name != "nt":
        return
    try:
        import ctypes
        t = f"OKX Bot | IP: {ip}"
        if extra:
            t += f" | {extra}"
        ctypes.windll.kernel32.SetConsoleTitleW(t)
    except Exception:
        pass


def cip(ip):
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass
    return f"\033[93m{ip}\033[0m"


# ==============================================
# SDK 响应
# ==============================================
def ok_ok(r):
    return isinstance(r, dict) and str(r.get("code", "")) == "0"


def ok_data(r):
    if not isinstance(r, dict):
        return []
    d = r.get("data", [])
    return d if isinstance(d, list) else []


def ok_err(r):
    if not isinstance(r, dict):
        return str(r)
    return f"[{r.get('code', '')}] {r.get('msg', '')}"


def bal_amt(item):
    for k in ("availBal", "cashBal", "eq", "bal"):
        v = sd(item.get(k, "0"))
        if v > 0:
            return v
    return Decimal("0")


def retry_call(func, *args, **kwargs):
    """带重试，DNS失败特殊处理"""
    last = None
    for i in range(RETRY_TIMES + 2):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last = e
            err_str = str(e).lower()
            if "getaddrinfo" in err_str or "11004" in err_str:
                time.sleep(2.0 * (i + 1))
            elif "timeout" in err_str or "timed out" in err_str:
                time.sleep(1.0 * (i + 1))
            else:
                if i < RETRY_TIMES:
                    time.sleep(RETRY_DELAY * (2 ** i))
    raise last


# ==============================================
# 指标
# ==============================================
class Ind:
    @staticmethod
    def ema(vals, p):
        if len(vals) < p:
            return None
        m = 2 / (p + 1)
        c = sum(vals[:p]) / p
        for v in vals[p:]:
            c = (v - c) * m + c
        return c

    @staticmethod
    def ema_series(vals, p):
        if len(vals) < p:
            return []
        m = 2 / (p + 1)
        out = [sum(vals[:p]) / p]
        for v in vals[p:]:
            out.append((v - out[-1]) * m + out[-1])
        return out

    @staticmethod
    def rsi(closes, p=14):
        if len(closes) <= p:
            return None
        g = l = 0.0
        for pr, cu in zip(closes[-p-1:-1], closes[-p:]):
            ch = cu - pr
            g += max(ch, 0)
            l += max(-ch, 0)
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l)

    @staticmethod
    def atr(candles, p=14):
        if len(candles) < p + 1:
            return None
        trs = []
        for pr, cu in zip(candles[-p-1:-1], candles[-p:]):
            h, l, pc = sf(cu[2]), sf(cu[3]), sf(pr[4])
            if h <= 0 or l <= 0 or pc <= 0:
                continue
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else None

    @staticmethod
    def boll(closes, p=BB_PERIOD, m=BB_MULT):
        if len(closes) < p:
            return None, None, None
        w = closes[-p:]
        mid = sum(w) / p
        std = sqrt(sum((x - mid) ** 2 for x in w) / p)
        return mid + m * std, mid, mid - m * std

    @staticmethod
    def macd(closes, f=MACD_FAST, s=MACD_SLOW, sig=MACD_SIGNAL):
        if len(closes) < s + sig:
            return None, None, None
        ef = Ind.ema_series(closes, f)
        es = Ind.ema_series(closes, s)
        off = len(ef) - len(es)
        if off < 0:
            return None, None, None
        ms = [a - b for a, b in zip(ef[off:], es)]
        if len(ms) < sig:
            return None, None, None
        ss = Ind.ema_series(ms, sig)
        if not ss:
            return None, None, None
        return ms[-1], ss[-1], ms[-1] - ss[-1]

    @staticmethod
    def macd_hist(closes):
        if len(closes) < MACD_SLOW + MACD_SIGNAL + 2:
            return []
        ef = Ind.ema_series(closes, MACD_FAST)
        es = Ind.ema_series(closes, MACD_SLOW)
        off = len(ef) - len(es)
        if off < 0:
            return []
        ms = [a - b for a, b in zip(ef[off:], es)]
        if len(ms) < MACD_SIGNAL:
            return []
        ss = Ind.ema_series(ms, MACD_SIGNAL)
        off2 = len(ms) - len(ss)
        return [a - b for a, b in zip(ms[off2:], ss)]

    @staticmethod
    def kdj(candles, n=KDJ_N, m1=KDJ_M1, m2=KDJ_M2):
        if len(candles) < n:
            return None, None, None
        kp = dp = 50.0
        for i in range(n - 1, len(candles)):
            w = candles[i-n+1:i+1]
            h = max(sf(c[2]) for c in w)
            l = min(sf(c[3]) for c in w)
            c = sf(candles[i][4])
            rsv = 50.0 if h == l else (c - l) / (h - l) * 100
            kp = (m1 - 1) / m1 * kp + 1 / m1 * rsv
            dp = (m2 - 1) / m2 * dp + 1 / m2 * kp
        return kp, dp, 3 * kp - 2 * dp

    @staticmethod
    def obv(candles):
        if len(candles) < 2:
            return []
        s = [0.0]
        for i in range(1, len(candles)):
            cp = sf(candles[i-1][4])
            cc = sf(candles[i][4])
            vc = sf(candles[i][5])
            if cc > cp:
                s.append(s[-1] + vc)
            elif cc < cp:
                s.append(s[-1] - vc)
            else:
                s.append(s[-1])
        return s


def vol_score(cs):
    if len(cs) < 20:
        return 0.0
    vs = [sf(c[5]) for c in cs if len(c) > 5]
    if len(vs) < 20:
        return 0.0
    avg = sum(vs[-20:]) / 20
    r = vs[-1] / avg if avg > 0 else 0
    if r < 0.5: return 0.0
    elif r < 1.0: return 30 * r
    elif r < 2.0: return 50 + (r - 1) * 25
    elif r < 5.0: return 75 + (r - 2) / 3 * 15
    else: return 90 + min(10, (r - 5) / 5 * 10)


def vola_score(atr, price):
    if price <= 0:
        return 0.0
    r = atr / price
    if r < 0.002: return 20
    elif r < 0.005: return 50 + (r - 0.002) / 0.003 * 20
    elif r < 0.015: return 70 + (r - 0.005) / 0.01 * 20
    elif r < 0.03: return 90 - (r - 0.015) / 0.015 * 20
    else: return 50


def bb_score(closes):
    u, m, l = Ind.boll(closes)
    if not u or not m or not l or m <= 0:
        return 50.0
    b = u - l
    if b <= 0:
        return 50.0
    pos = (closes[-1] - l) / b
    if pos < 0: return 100
    elif pos < 0.2: return 90
    elif pos < 0.4: return 70
    elif pos < 0.6: return 50
    elif pos < 0.8: return 30
    elif pos < 1.0: return 15
    else: return 0


def macd_score(closes):
    ml, sl, h = Ind.macd(closes)
    if ml is None or sl is None or h is None:
        return 50.0
    hs = Ind.macd_hist(closes)
    rising = len(hs) >= 2 and hs[-1] > hs[-2]
    if h > 0 and rising: sc = 90
    elif h > 0: sc = 70
    elif h < 0 and rising: sc = 55
    else: sc = 20
    if ml > sl and rising:
        sc = min(100, sc + 5)
    elif ml < sl and not rising:
        sc = max(0, sc - 5)
    return sc


def kdj_score(cs):
    k, d, j = Ind.kdj(cs)
    if k is None or j is None:
        return 50.0
    if j < 0: sc = 100
    elif j < 20: sc = 85
    elif j < 40: sc = 70
    elif j < 60: sc = 50
    elif j < 80: sc = 30
    elif j < 100: sc = 15
    else: sc = 0
    return min(100, sc + 5) if k > d else sc


def obv_score(cs):
    s = Ind.obv(cs)
    if len(s) < OBV_LOOKBACK + 1:
        return 50.0
    r = s[-OBV_LOOKBACK-1:]
    diff = r[-1] - r[0]
    av = sum(abs(r[i] - r[i-1]) for i in range(1, len(r))) / max(1, len(r) - 1)
    if av <= 0:
        return 50.0
    n = diff / av
    if n > 2: return 90
    elif n > 0.5: return 75
    elif n > -0.5: return 50
    elif n > -2: return 30
    else: return 10


def mom_score(ch):
    if ch < 0: return 0
    elif ch < 3: return 30 + ch / 3 * 20
    elif ch < 8: return 50 + (ch - 3) / 5 * 25
    elif ch < 20: return 75 + (ch - 8) / 12 * 20
    elif ch < 50: return 95 - (ch - 20) / 30 * 20
    else: return 60


def aggr_rsi_score(rsi):
    if rsi < 30: return 30
    elif rsi < 40: return 60
    elif rsi < 50: return 85
    elif rsi < 60: return 95
    elif rsi < 65: return 80
    elif rsi < 70: return 50
    elif rsi < 80: return 25
    else: return 10


def aggr_bb_score(closes):
    u, m, l = Ind.boll(closes)
    if not u or not m or not l or m <= 0:
        return 50.0
    b = u - l
    if b <= 0:
        return 50.0
    pos = (closes[-1] - l) / b
    if pos < 0.2: return 40
    elif pos < 0.4: return 70
    elif pos < 0.6: return 90
    elif pos < 0.8: return 75
    elif pos < 0.95: return 50
    else: return 25


class ADX:
    def __init__(self, p=ADX_PERIOD):
        self.p = p

    def calc(self, cs):
        p = self.p
        if len(cs) < p * 2 + 1:
            return None
        pdm, mdm, trl = [], [], []
        for pr, cu in zip(cs[:-1], cs[1:]):
            hc, hp = sf(cu[2]), sf(pr[2])
            lc, lp = sf(cu[3]), sf(pr[3])
            cp = sf(pr[4])
            if min(hc, hp, lc, lp, cp) <= 0:
                continue
            hd = hc - hp
            ld = lp - lc
            pdm.append(hd if hd > ld and hd > 0 else 0)
            mdm.append(ld if ld > hd and ld > 0 else 0)
            trl.append(max(hc - lc, abs(hc - cp), abs(lc - cp)))
        if len(trl) < p * 2:
            return None

        def sw(vs, n):
            if len(vs) < n:
                return 0.0
            s = sum(vs[:n])
            for i in range(n, len(vs)):
                s = s - s / n + vs[i]
            return s

        a = sw(trl, p)
        if a <= 0:
            return None
        pdi = 100 * sw(pdm, p) / a
        mdi = 100 * sw(mdm, p) / a
        d = pdi + mdi
        return 100 * abs(pdi - mdi) / d if d > 0 else 0.0


class Corr:
    @staticmethod
    def pearson(x, y):
        n = min(len(x), len(y))
        if n < 5:
            return 0.0
        xs, ys = x[:n], y[:n]
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
        sx = sqrt(sum((v - mx) ** 2 for v in xs) / n)
        sy = sqrt(sum((v - my) ** 2 for v in ys) / n)
        return cov / (sx * sy) if sx > 0 and sy > 0 else 0.0


# ==============================================
# Client
# ==============================================
class Client:
    def __init__(self, key, secret, passphrase, simulated=False, proxy=None, brokerId='', brokerApiKey=''):
        flag = "1" if simulated else "0"
        self.proxy = proxy
        self.flag = flag
        self.brokerId = brokerId
        self.brokerApiKey = brokerApiKey
        self._inst = {}
        self._inst_loaded = False

        self.account = Account.AccountAPI(
            api_key=key,
            api_secret_key=secret,
            passphrase=passphrase,
            use_server_time=False,
            flag=flag,
            debug=False,
            proxy=proxy
        )
        self.market = MarketData.MarketAPI(
            flag=flag,
            debug=False,
            proxy=proxy
        )
        self.public = PublicData.PublicAPI(
            flag=flag,
            debug=False,
            proxy=proxy
        )
        self.trade = Trade.TradeAPI(
            api_key=key,
            api_secret_key=secret,
            passphrase=passphrase,
            use_server_time=False,
            flag=flag,
            debug=False,
            proxy=proxy
        )
        self.funding = Funding.FundingAPI(
            api_key=key,
            api_secret_key=secret,
            passphrase=passphrase,
            use_server_time=False,
            flag=flag,
            debug=False,
            proxy=proxy
        )

    def _tag(self):
        return self.brokerId if self.brokerId else ''

    # ---------- 行情 ----------
    def ticker(self, sym):
        try:
            params = {'instId': sym}
            r = retry_call(self.market._request_with_params, GET, TICKER_INFO, params)
            if ok_ok(r):
                d = ok_data(r)
                return d[0] if d else {}
        except Exception as e:
            dbg(f"ticker({sym}): {e}")
        return {}

    def all_tickers(self):
        try:
            params = {'instType': "SPOT"}
            r = retry_call(self.market._request_with_params, GET, TICKERS_INFO, params)
            if ok_ok(r):
                return ok_data(r)
        except Exception as e:
            print(f"  全市场行情失败: {str(e)[:150]}")
        return []

    def candles(self, sym, bar="1H", limit=300):
        params = {'instId': sym, 'bar': bar, 'limit': str(limit)}
        r = retry_call(self.market._request_with_params, GET, MARKET_CANDLES, params)
        if not ok_ok(r):
            raise ValueError(f"K线失败: {ok_err(r)}")
        d = ok_data(r)
        if not d:
            raise ValueError(f"K线为空: {sym}")
        d.reverse()
        out = []
        for row in d:
            if len(row) < 6:
                continue
            if len(row) >= 9 and str(row[8]) == "0":
                continue
            out.append([str(row[0]), str(row[1]), str(row[2]),
                        str(row[3]), str(row[4]), str(row[5])])
        if len(out) < 20:
            raise ValueError(f"K线不足: {len(out)}根")
        return out

    # ---------- 交易对（★ 批量加载，减少DNS压力） ----------
    def all_instruments(self, force=False):
        """一次性获取全部SPOT交易对（1次请求替代100次）"""
        if not force and self._inst_loaded:
            return self._inst
        try:
            params = {'instType': "SPOT"}
            r = retry_call(self.public._request_with_params, GET, INSTRUMENT_INFO, params)
            if not ok_ok(r):
                print(f"  加载交易对失败: {ok_err(r)}")
                return self._inst
            d = ok_data(r)
            for i in d:
                sym = i.get("instId", "")
                self._inst[sym] = {
                    "symbol": sym,
                    "state": i.get("state", "off"),
                    "status": "live" if i.get("state") == "live" else "off",
                    "base_min": sd(i.get("minSz", "0.00000001")),
                    "lot_size": sd(i.get("lotSz", "0.00000001")),
                    "tick_size": sd(i.get("tickSz", "0.01")),
                }
            self._inst_loaded = True
            print(f"  已缓存 {len(self._inst)} 个交易对")
        except Exception as e:
            print(f"  批量加载交易对异常: {str(e)[:120]}")
        return self._inst

    def instrument(self, sym, force=False):
        # 优先从缓存
        if not force and sym in self._inst:
            return self._inst[sym]
        # 尝试批量加载
        if not self._inst_loaded:
            self.all_instruments()
        if sym in self._inst:
            return self._inst[sym]
        # 单币请求兜底
        params = {'instType': "SPOT", 'instId': sym}
        r = retry_call(self.public._request_with_params, GET, INSTRUMENT_INFO, params)
        if not ok_ok(r):
            raise ValueError(f"交易对不存在: {sym} ({ok_err(r)})")
        d = ok_data(r)
        if not d:
            raise ValueError(f"交易对不存在: {sym}")
        i = d[0]
        info = {
            "symbol": sym,
            "state": i.get("state", "off"),
            "status": "live" if i.get("state") == "live" else "off",
            "base_min": sd(i.get("minSz", "0.00000001")),
            "lot_size": sd(i.get("lotSz", "0.00000001")),
            "tick_size": sd(i.get("tickSz", "0.01")),
        }
        self._inst[sym] = info
        return info

    # ---------- 账户 ----------
    def balance(self, ccys):
        """交易账户余额（现货下单用）。"""
        cur = list(set(c.upper() for c in ccys if c))
        bal = {c: Decimal("0") for c in cur}
        last_err = None
        got_data = False
        for i in range(0, len(cur), 20):
            batch = cur[i:i+20]
            try:
                params = {'ccy': ",".join(batch)}
                r = retry_call(self.account._request_with_params, GET, ACCOUNT_INFO, params)
                if not ok_ok(r):
                    last_err = ok_err(r)
                    dbg(f"balance: {last_err}")
                    continue
                d = ok_data(r)
                if not d or not isinstance(d[0], dict):
                    continue
                got_data = True
                for it in d[0].get("details", []):
                    ccy = it.get("ccy", "").upper()
                    if ccy in bal:
                        bal[ccy] = max(bal[ccy], bal_amt(it))
            except Exception as e:
                last_err = str(e)
                dbg(f"balance: {e}")
        if not got_data and last_err:
            raise RuntimeError(last_err)
        return bal

    def funding_balance(self, ccys):
        """资金账户余额（需划转到交易账户后才能现货下单）。"""
        cur = list(set(c.upper() for c in ccys if c))
        bal = {c: Decimal("0") for c in cur}
        last_err = None
        got_data = False
        for i in range(0, len(cur), 20):
            batch = cur[i:i+20]
            try:
                params = {'ccy': ",".join(batch)}
                r = retry_call(self.funding._request_with_params, GET, GET_BALANCES, params)
                if not ok_ok(r):
                    last_err = ok_err(r)
                    dbg(f"funding_balance: {last_err}")
                    continue
                got_data = True
                for it in ok_data(r):
                    ccy = it.get("ccy", "").upper()
                    if ccy in bal:
                        bal[ccy] = max(bal[ccy], bal_amt(it))
            except Exception as e:
                last_err = str(e)
                dbg(f"funding_balance: {e}")
        if not got_data and last_err:
            raise RuntimeError(last_err)
        return bal

    def all_balances(self):
        try:
            r = retry_call(self.account._request_with_params, GET, ACCOUNT_INFO, {})
            if not ok_ok(r):
                dbg(f"all_balances: {ok_err(r)}")
                return []
            d = ok_data(r)
            if not d or not isinstance(d[0], dict):
                return []
            out = []
            for it in d[0].get("details", []):
                ccy = it.get("ccy", "").upper()
                b = bal_amt(it)
                if ccy and b > 0:
                    out.append({"ccy": ccy, "availBal": b})
            return out
        except Exception as e:
            dbg(f"all_balances: {e}")
            return []

    # ---------- 交易 ----------
    def place_buy(self, sym, quote_usdt: Decimal, td_mode="cash"):
        oid = make_oid("b")
        sz_str = str(quote_usdt)
        dbg(f"下单: {sym} tdMode={td_mode} side=buy sz={sz_str} "
            f"tgtCcy=quote_ccy clOrdId={oid} tag={self._tag() or '(无)'}")
        try:
            order_kw = dict(
                instId=sym,
                tdMode=td_mode,
                side="buy",
                ordType="market",
                sz=sz_str,
                tgtCcy="quote_ccy",
                clOrdId=oid,
            )
            if self.brokerId:
                order_kw["tag"] = self.brokerId
            r = retry_call(self.trade.place_order, **order_kw)
        except Exception as e:
            return {"order_id": "", "status": "-1", "s_msg": str(e)[:150]}
        return self._parse_order(r, "买入")

    def place_sell(self, sym, base_amount: Decimal, td_mode="cash"):
        oid = make_oid("s")
        sz_str = str(base_amount)
        dbg(f"下单: {sym} tdMode={td_mode} side=sell sz={sz_str} "
            f"clOrdId={oid} tag={self._tag() or '(无)'}")
        try:
            order_kw = dict(
                instId=sym,
                tdMode=td_mode,
                side="sell",
                ordType="market",
                sz=sz_str,
                clOrdId=oid,
            )
            if self.brokerId:
                order_kw["tag"] = self.brokerId
            r = retry_call(self.trade.place_order, **order_kw)
        except Exception as e:
            return {"order_id": "", "status": "-1", "s_msg": str(e)[:150]}
        return self._parse_order(r, "卖出")

    @staticmethod
    def _parse_order(r, action=""):
        dbg(f"{action}响应: {r}")
        if not isinstance(r, dict):
            return {"order_id": "", "status": "-1", "s_msg": "响应格式异常"}
        if str(r.get("code", "0")) != "0":
            return {"order_id": "", "status": str(r.get("code", "")),
                    "s_msg": r.get("msg", "")}
        d = r.get("data", [])
        if not d or not isinstance(d, list):
            return {"order_id": "", "status": "-1", "s_msg": "无data"}
        o = d[0]
        s_code = str(o.get("sCode", ""))
        s_msg = o.get("sMsg", "")
        ord_id = str(o.get("ordId", ""))
        if s_code != "0":
            dbg(f"{action}被拒: sCode={s_code} sMsg={s_msg}")
            return {"order_id": "", "status": s_code, "s_msg": s_msg}
        return {"order_id": ord_id, "status": "0", "s_msg": ""}

    def get_order(self, sym, oid):
        params = {'instId': sym, 'ordId': oid}
        r = retry_call(self.trade._request_with_params, POST, ORDER_INFO, params)
        if not ok_ok(r):
            raise RuntimeError(f"查询失败: {ok_err(r)}")
        d = ok_data(r)
        o = d[0] if d else {}
        smap = {"live": "open", "filled": "filled",
                "partially_filled": "partial", "canceled": "canceled"}
        return {
            "state": smap.get(o.get("state", ""), o.get("state", "")),
            "filled_amount": sd(o.get("accFillSz", "0")),
            "avg_price": sd(o.get("avgPx", "0")),
        }

    def wait_fill(self, sym, oid, timeout=10.0):
        deadline = time.monotonic() + timeout
        poll = 0
        info = {"state": "unknown", "filled_amount": Decimal("0"),
                "avg_price": Decimal("0")}
        while poll < 30:
            try:
                info = self.get_order(sym, oid)
            except Exception:
                time.sleep(0.5)
                poll += 1
                continue
            if info["state"] in {"filled", "canceled"}:
                return info
            if time.monotonic() >= deadline:
                return info
            time.sleep(0.5)
            poll += 1
        return info


# ==============================================
# Executor
# ==============================================
class Executor:
    def __init__(self, client: Client, instruments: Dict, td_mode="cash"):
        self.client = client
        self.instruments = instruments
        self.td_mode = td_mode

    def ensure(self, sym):
        try:
            if sym not in self.instruments:
                self.instruments[sym] = self.client.instrument(sym)
            inst = self.instruments[sym]
            if inst["status"] != "live":
                return False, f"state={inst.get('state', 'off')}"
            return True, "OK"
        except Exception as e:
            return False, f"加载交易对失败: {str(e)[:80]}"

    def calc_min_usdt(self, sym, inst=None):
        """minSz 是数量（币），最小USDT = minSz × 价格"""
        if inst is None:
            inst = self.instruments.get(sym)
            if inst is None:
                inst = self.client.instrument(sym)
        t = self.client.ticker(sym)
        price = sd(t.get("last", "0"))
        if price <= 0:
            return None, None
        return inst["base_min"] * price, price

    def validate_buy(self, sym, target_usdt: Decimal):
        ok, msg = self.ensure(sym)
        if not ok:
            return False, msg, {}
        inst = self.instruments[sym]
        min_usdt, price = self.calc_min_usdt(sym, inst)
        if min_usdt is None:
            return False, "无法获取价格", inst
        if target_usdt < min_usdt:
            base = sym.split("-")[0]
            return False, (
                f"目标{target_usdt:.4f}U < 最小{min_usdt:.4f}U "
                f"(需{inst['base_min']}{base}@{price:.6f})"
            ), inst
        return True, "OK", inst

    def buy(self, sym, target_usdt: Decimal, equity: Decimal):
        res = {"order_id": "", "filled_amount": Decimal("0"),
               "avg_price": Decimal("0"), "state": ""}
        try:
            if target_usdt <= 0:
                return False, res, "目标金额≤0"

            ok, msg, inst = self.validate_buy(sym, target_usdt)
            if not ok:
                return False, res, msg

            bal = self.client.balance(["USDT"])
            avail = bal.get("USDT", Decimal("0"))
            usable = avail * BUY_BALANCE_RATIO
            if usable < MIN_TRADE_USDT:
                return False, res, f"USDT不足: 可用{avail:.4f}U"

            amt = min(target_usdt, usable, equity * MAX_POSITION_RATIO)
            amt = rd(amt, Decimal("0.01"))

            min_usdt, price = self.calc_min_usdt(sym, inst)
            if amt < min_usdt:
                return False, res, f"对齐后{amt:.4f}U < 最小{min_usdt:.4f}U"
            if amt < MIN_TRADE_USDT:
                return False, res, f"低于自设最小{MIN_TRADE_USDT}U"

            o = self.client.place_buy(sym, amt, self.td_mode)

            if o.get("status") != "0":
                err_map = {
                    "51000": "参数错误", "51001": "交易对不存在",
                    "51005": "余额不足", "51006": "订单不存在",
                    "51007": "数量<最小值", "51008": "数量>最大值",
                    "51009": "下单数量小于最小值", "51012": "资金不足",
                    "51020": "数量精度错误", "51024": "下单参数错误",
                    "51026": "下单金额小于最小值", "51119": "金额太小",
                    "51121": "无交易权限", "51127": "不支持市价单",
                    "51131": "余额不足", "59000": "账户限制",
                    "59001": "账户已冻结", "50011": "请求过于频繁",
                }
                sc = o.get("status", "")
                hint = err_map.get(sc, "")
                return False, res, f"下单拒绝[{sc}] {hint} {o.get('s_msg', '')}"

            oid = o.get("order_id", "")
            if not oid:
                return False, res, "未返回订单号"

            info = self.client.wait_fill(sym, oid)
            res.update(info)
            res["order_id"] = oid

            if info["state"] == "filled" and info["filled_amount"] > 0:
                return True, res, f"成交{fmt(info['filled_amount'])} 花费{amt}U"
            elif info["state"] == "canceled":
                return False, res, "订单已取消"
            elif info["state"] == "partial" and info["filled_amount"] > 0:
                return True, res, f"部分成交{fmt(info['filled_amount'])}"
            return False, res, f"状态:{info['state']}"
        except Exception as e:
            return False, res, f"买入异常: {str(e)[:150]}"

    def sell(self, sym, base_amount: Decimal):
        res = {"order_id": "", "filled_amount": Decimal("0"),
               "avg_price": Decimal("0"), "state": ""}
        try:
            if base_amount <= 0:
                return False, res, "数量≤0"

            ok, msg = self.ensure(sym)
            if not ok:
                return False, res, msg
            inst = self.instruments[sym]
            lot = inst.get("lot_size", inst["base_min"])
            bmin = inst["base_min"]

            sa = rd(base_amount, lot)
            if sa < bmin:
                return False, res, f"数量{fmt(sa)} < 最小{bmin}"

            base_ccy = sym.split("-")[0]
            bal = self.client.balance([base_ccy])
            real = bal.get(base_ccy.upper(), Decimal("0"))
            if real < bmin:
                return False, res, f"实际余额{fmt(real)} < 最小{bmin}"
            if real < sa:
                sa = rd(real, lot)
                if sa < bmin:
                    return False, res, "调整后数量过小"

            o = self.client.place_sell(sym, sa, self.td_mode)

            if o.get("status") != "0":
                err_map = {
                    "51000": "参数错误", "51001": "交易对不存在",
                    "51005": "余额不足", "51007": "数量<最小值",
                    "51020": "数量精度错误", "51024": "下单参数错误",
                    "51121": "无交易权限", "59000": "账户限制",
                    "59001": "账户已冻结", "50011": "请求频繁",
                }
                sc = o.get("status", "")
                hint = err_map.get(sc, "")
                return False, res, f"卖出拒绝[{sc}] {hint} {o.get('s_msg', '')}"

            oid = o.get("order_id", "")
            if not oid:
                return False, res, "未返回订单号"

            info = self.client.wait_fill(sym, oid)
            res.update(info)
            res["order_id"] = oid

            if info["state"] == "filled" and info["filled_amount"] > 0:
                return True, res, f"成交{fmt(info['filled_amount'])} 均价{info['avg_price']}"
            elif info["state"] == "canceled":
                return False, res, "订单已取消"
            elif info["state"] == "partial" and info["filled_amount"] > 0:
                return True, res, f"部分成交{fmt(info['filled_amount'])}"
            return False, res, f"状态:{info['state']}"
        except Exception as e:
            return False, res, f"卖出异常: {str(e)[:150]}"


# ==============================================
# 诊断
# ==============================================
def diagnose(client: Client, symbols: List[str], per_max: Decimal, td_mode: str):
    print("\n" + "=" * 90)
    print("                         交 易 诊 断")
    print("=" * 90)
    bals = client.balance(["USDT"])
    usdt_bal = bals.get("USDT", Decimal("0"))
    print(f"tdMode   : {td_mode}")
    print(f"USDT余额 : {usdt_bal}")
    print(f"单笔上限 : {per_max} USDT")
    print()
    print(f"{'币种':<14}{'state':<10}{'价格':>14}{'minSz(币)':>16}"
          f"{'最小USDT':>14}{'能买':>6}")
    print("-" * 90)
    for sym in symbols:
        try:
            inst = client.instrument(sym)
            state = inst.get("state", "?")[:9]
            ticker = client.ticker(sym)
            price = sd(ticker.get("last", "0"))
            base_min = inst["base_min"]
            if price > 0:
                min_usdt = base_min * price
                can_buy = "✓" if per_max >= min_usdt and usdt_bal >= min_usdt else "✗"
            else:
                min_usdt = Decimal("0")
                can_buy = "?"
            print(f"{sym:<14}{state:<10}{str(price):>14}{str(base_min):>16}"
                  f"{str(min_usdt):>14}{can_buy:>6}")
        except Exception as e:
            print(f"{sym:<14}错误: {str(e)[:60]}")
    print("-" * 90)


# ==============================================
# 归集器
# ==============================================
class Collector:
    def __init__(self, client: Client, instruments: Dict, td_mode="cash"):
        self.client = client
        self.instruments = instruments
        self.td_mode = td_mode

    def collect(self, exclude=None, min_value=COLLECT_MIN_VALUE_USDT,
                executor=None, verbose=True):
        exclude = exclude or set()
        ex_ccy = {"USDT"} | {s.split("-")[0].upper() for s in exclude}
        all_b = self.client.all_balances()
        if not all_b:
            return 0, 0, Decimal("0")
        targets = [(it["ccy"], it["availBal"]) for it in all_b
                   if it["ccy"] not in ex_ccy and it["availBal"] > 0]
        if not targets:
            if verbose:
                print("  无需归集")
            return 0, 0, Decimal("0")
        if verbose:
            print(f"  待归集: {[c for c, _ in targets]}")
        ok = fail = 0
        total = Decimal("0")
        ex = executor or Executor(self.client, self.instruments, self.td_mode)
        for ccy, amt in targets:
            sym = f"{ccy}-USDT"
            try:
                inst = self.client.instrument(sym)
                if inst["status"] != "live":
                    continue
                self.instruments[sym] = inst
            except Exception:
                continue
            t = self.client.ticker(sym)
            price = sd(t.get("last", "0"))
            if price <= 0:
                continue
            if amt * price < min_value:
                continue
            success, oi, msg = ex.sell(sym, amt * Decimal("0.999"))
            if success:
                px = oi.get("avg_price", Decimal("0"))
                fq = oi.get("filled_amount", Decimal("0"))
                got = fq * px if px > 0 else Decimal("0")
                total += got
                ok += 1
                if verbose:
                    print(f"    ✓ {ccy}: 得≈{got:.4f}U")
            else:
                fail += 1
                if verbose:
                    print(f"    ✗ {ccy}: {msg}")
            time.sleep(0.4)
        return ok, fail, total


# ==============================================
# PM / Tracker
# ==============================================
class PM:
    def __init__(self):
        self.positions = {}
        self.aggr_flags = {}

    def add(self, sym, entry, size, atr, ema20, aggr=False):
        e = float(entry)
        a = max(atr, e * MIN_ATR_RATIO)
        self.positions[sym] = {
            "entry_price": entry, "size": size, "original_size": size,
            "open_time": time.time(), "highest_price": entry,
            "entry_atr": a, "entry_ema20": ema20,
            "break_even_done": False, "partial_taken": False,
            "_last_hist": 0.0,
        }
        self.aggr_flags[sym] = aggr

    def remove(self, sym):
        self.positions.pop(sym, None)
        self.aggr_flags.pop(sym, None)

    def has(self, sym):
        return sym in self.positions

    def held(self):
        return set(self.positions.keys())

    def check_exit(self, sym, price, ema20, candles=None):
        pos = self.positions.get(sym)
        if not pos:
            return None
        aggr = self.aggr_flags.get(sym, False)
        if aggr:
            sl_m, be_m, ts = AGGR_STOP_LOSS_ATR, AGGR_BREAK_EVEN_ATR, AGGR_TRAILING_STEPS
        else:
            sl_m, be_m, ts = STOP_LOSS_ATR_MULT, BREAK_EVEN_ATR_MULT, TRAILING_STEPS

        entry = pos["entry_price"]
        atr = pos["entry_atr"]
        p = float(price)
        if p > pos["highest_price"]:
            pos["highest_price"] = p
        profit = (p - entry) / entry if entry > 0 else 0

        if p <= entry - atr * sl_m:
            return "stop_loss", f"价格{p:.6f} ≤ {entry - atr*sl_m:.6f}"

        be_trigger = atr / entry * be_m
        if not pos["break_even_done"] and profit >= be_trigger:
            pos["break_even_done"] = True
        be_buf = max(atr * 0.1 / entry, 0.0005)
        if pos["break_even_done"] and p <= entry * (1 + be_buf):
            return "break_even", "回落保本价"

        if aggr and candles and len(candles) >= 50:
            try:
                closes = [sf(c[4]) for c in candles if len(c) > 4 and sf(c[4]) > 0]
                if profit > MIN_PROFIT_RATIO:
                    rsi = Ind.rsi(closes, 14)
                    u, m, l = Ind.boll(closes)
                    bp = (p - l) / (u - l) if u and l and u > l else None
                    k, d, j = Ind.kdj(candles)
                    ml, sl, hist = Ind.macd(closes)
                    sigs = []
                    if rsi is not None and rsi >= AGGR_TAKE_PROFIT_RSI:
                        sigs.append(f"RSI={rsi:.1f}")
                    if bp is not None and bp >= AGGR_TAKE_PROFIT_BB:
                        sigs.append(f"BB%={bp:.2f}")
                    if j is not None and j >= AGGR_TAKE_PROFIT_KDJ:
                        sigs.append(f"KDJ_J={j:.0f}")
                    if len(sigs) >= 2:
                        return "predictive_profit", f"顶部共振 盈利{profit*100:.2f}%"
                    if hist is not None and hist < 0 and pos.get("_last_hist", 0) > 0:
                        return "macd_reverse", f"MACD转负 盈利{profit*100:.2f}%"
                    if hist is not None:
                        pos["_last_hist"] = hist
                    if not pos["partial_taken"] and \
                            profit >= (atr * AGGR_PARTIAL_TAKE_ATR) / entry:
                        return "partial_take", f"浮盈{profit*100:.2f}%≥2ATR"
            except Exception:
                pass

        high = pos["highest_price"]
        dd = (high - p) / high if high > 0 else 0
        thr = ts[-1][1]
        for mp, t in ts:
            if profit < mp:
                thr = t
                break
        if p > ema20:
            thr *= 1.2
        if dd >= thr and profit > 0:
            return "trailing_stop", f"回撤{dd*100:.2f}%"
        if p < ema20 and profit > MIN_PROFIT_RATIO:
            return "ema20_break", "跌破EMA20"
        if time.time() - pos["open_time"] > MAX_HOLD_HOURS * 3600:
            return "timeout", f">{MAX_HOLD_HOURS}h"
        return None


class Tracker:
    def __init__(self, initial):
        self.initial = initial
        self.peak = initial
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.realized = Decimal("0")

    def record(self, ret, size):
        self.trades += 1
        self.realized += size * Decimal(str(ret))
        if ret > 0:
            self.wins += 1
        elif ret < 0:
            self.losses += 1

    def update(self, eq):
        self.peak = max(self.peak, eq)

    def summary(self, eq):
        r = (eq - self.initial) / self.initial * 100 if self.initial > 0 else Decimal("0")
        wr = self.wins / self.trades * 100 if self.trades > 0 else 0
        dd = (self.peak - eq) / self.peak * 100 if self.peak > 0 else Decimal("0")
        return (f"初始:{self.initial:.4f} 当前:{eq:.4f} 收益:{r:.2f}% "
                f"已实现:{self.realized:.4f} 交易:{self.trades}(胜{wr:.1f}%) "
                f"峰值:{self.peak:.4f} 回撤:{dd:.2f}%")


# ==============================================
# 激进型（顺延扫描，减少DNS压力）
# ==============================================
class Aggressive:
    def __init__(self, client, per_max, td_mode):
        self.client = client
        self.per_max = per_max
        self.td_mode = td_mode
        self._pool = []
        self._pool_round = -999
        self._cooldown = {}

    def refresh_pool(self, round_n, force=False):
        if not force and round_n - self._pool_round < AGGRESSIVE_REFRESH_ROUNDS:
            return
        self._pool_round = round_n
        print("  刷新全市场行情...")
        tickers = self.client.all_tickers()
        if not tickers:
            return

        # ★ 批量加载交易对信息（1次请求替代100次）
        self.client.all_instruments()

        all_movers = []
        for t in tickers:
            sym = t.get("instId", "")
            if not sym.endswith("-USDT"):
                continue
            last = sf(t.get("last", 0))
            op = sf(t.get("open24h", 0))
            vol = sf(t.get("volCcy24h", 0))
            if last <= 0 or op <= 0 or vol < AGGRESSIVE_MIN_VOL_USDT:
                continue
            ch = (last - op) / op * 100
            if ch <= 0:
                continue
            all_movers.append({"instId": sym, "last": last,
                               "change24h": ch, "vol_usdt": vol})
        all_movers.sort(key=lambda x: -x["change24h"])
        total = len(all_movers)
        print(f"  全市场符合条件: {total}个")
        if total == 0:
            self._pool = []
            return
        adx = ADX()
        candidates = []
        skipped_q = skipped_l = skipped_low = 0
        scanned = 0
        bs = 0
        bn = 0
        while bs < total and len(candidates) < AGGRESSIVE_TARGET_POOL:
            batch = all_movers[bs:bs + AGGRESSIVE_BATCH_SIZE]
            bs += AGGRESSIVE_BATCH_SIZE
            bn += 1
            print(f"  ── 第{bn}批: 排名 {bs-len(batch)+1}-{bs} "
                  f"（候选{len(candidates)}/{AGGRESSIVE_TARGET_POOL}）")
            for item in batch:
                scanned += 1
                sym = item["instId"]
                try:
                    # ★ 从缓存读取交易对信息（不发请求）
                    try:
                        inst = self.client.instrument(sym)
                    except Exception:
                        skipped_l += 1
                        continue

                    if inst["status"] != "live":
                        skipped_l += 1
                        continue
                    min_usdt = inst["base_min"] * Decimal(str(item["last"]))
                    if min_usdt > self.per_max:
                        skipped_q += 1
                        continue

                    # ★ K线请求间隔加大，减少DNS压力
                    time.sleep(0.15)
                    cs = self.client.candles(sym, bar="1H", limit=300)
                    closes = [sf(c[4]) for c in cs if len(c) > 4 and sf(c[4]) > 0]
                    if len(closes) < 210:
                        continue
                    rsi = Ind.rsi(closes, 14)
                    if rsi is None:
                        continue
                    atr = Ind.atr(cs, 14) or closes[-1] * MIN_ATR_RATIO
                    price = closes[-1]
                    ms = mom_score(item["change24h"])
                    rs = aggr_rsi_score(rsi)
                    a = adx.calc(cs)
                    if a is None: as_ = 0
                    elif a < ADX_WEAK: as_ = 0
                    elif a < ADX_MODERATE: as_ = 40 + (a - ADX_WEAK) / (ADX_MODERATE - ADX_WEAK) * 30
                    elif a < ADX_STRONG: as_ = 70 + (a - ADX_MODERATE) / (ADX_STRONG - ADX_MODERATE) * 20
                    else: as_ = 90 + min(10, (a - ADX_STRONG) / 10 * 10)
                    vs = vol_score(cs)
                    bsc = aggr_bb_score(closes)
                    vls = vola_score(atr, price)
                    comp = (ms * AGGRESSIVE_WEIGHTS["momentum"] +
                            rs * AGGRESSIVE_WEIGHTS["rsi"] +
                            as_ * AGGRESSIVE_WEIGHTS["adx"] +
                            vs * AGGRESSIVE_WEIGHTS["volume"] +
                            bsc * AGGRESSIVE_WEIGHTS["bollinger"] +
                            vls * AGGRESSIVE_WEIGHTS["volatility"])
                    if comp < AGGRESSIVE_MIN_CAND_SCORE:
                        skipped_low += 1
                        continue
                    candidates.append({
                        "symbol": sym, "score": comp,
                        "change24h": item["change24h"],
                        "vol_usdt": item["vol_usdt"],
                        "rsi": rsi, "adx": a, "atr": atr, "price": price,
                        "base_min": inst["base_min"],
                        "min_usdt": min_usdt,
                    })
                    if len(candidates) >= AGGRESSIVE_TARGET_POOL:
                        break
                except Exception as e:
                    err_str = str(e).lower()
                    if "getaddrinfo" in err_str or "11004" in err_str:
                        print(f"    {sym}: DNS失败，等待3秒...")
                        time.sleep(3.0)
                    continue
                time.sleep(0.1)   # 每币之间间隔
            if len(candidates) >= AGGRESSIVE_TARGET_POOL:
                print(f"  ✓ 候选充足")
                break
            if bs >= total:
                print(f"  已扫完全部{total}个")
                break
            print(f"    候选不足，继续顺延...")
            time.sleep(0.5)   # 批次间隔

        candidates.sort(key=lambda x: -x["score"])
        now = []
        skipped_cool = 0
        for s in candidates:
            if s["symbol"] in self._cooldown and self._cooldown[s["symbol"]] > 0:
                skipped_cool += 1
                continue
            now.append(s)
        self._pool = now
        top_s = now[0]["score"] if now else 0
        print(f"  ────────────────────────────")
        print(f"  扫描:{scanned} 剔除:状态{skipped_l} 金额{skipped_q} "
              f"低分{skipped_low} 冷却{skipped_cool}")
        print(f"  候选池: {len(now)}个 最高分{top_s:.1f}")
        if now:
            print(f"  前5: " + ", ".join(
                f"{c['symbol'].replace('-USDT','')}({c['score']:.0f})"
                for c in now[:5]))
        print(f"  ────────────────────────────")

    def maintain(self, pm, ex, tracker, equity, round_n):
        held = pm.held()
        need = AGGRESSIVE_PICK_N - len(held)
        if need <= 0:
            return
        print(f"\n持仓 {len(held)}/{AGGRESSIVE_PICK_N}，需补位 {need}")
        self.refresh_pool(round_n)
        if not self._pool:
            print("  候选池空")
            return
        for sym in list(self._cooldown.keys()):
            self._cooldown[sym] -= 1
            if self._cooldown[sym] <= 0:
                del self._cooldown[sym]
        available = [c for c in self._pool if c["symbol"] not in held]
        print(f"  可用候补: {len(available)}")
        bought = 0
        for c in available:
            if bought >= need:
                break
            sym = c["symbol"]
            sm = clamp((c["score"] - 50) / 50, 0.5, 1.5)
            target = self.per_max * Decimal(str(sm))
            target = min(target, equity * MAX_POSITION_RATIO)

            min_usdt = c.get("min_usdt", Decimal("0"))
            if target < min_usdt:
                boosted = min_usdt * Decimal("1.05")
                if boosted <= self.per_max:
                    print(f"  {sym}: 目标{target:.2f}U < 最小{min_usdt:.4f}U "
                          f"→ 提升到{boosted:.2f}U")
                    target = boosted
                else:
                    print(f"  {sym}: 最小{min_usdt:.4f}U > 上限{self.per_max}U，换")
                    self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
                    continue

            if target < MIN_TRADE_USDT:
                print(f"  {sym}: 目标{target:.2f}U < {MIN_TRADE_USDT}U，换")
                self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
                continue

            ok, msg, _ = ex.validate_buy(sym, target)
            if not ok:
                print(f"  {sym}: ✗ {msg}，换")
                self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
                continue

            if held:
                nr = self._get_returns(sym)
                if nr:
                    too = False
                    for h in held:
                        orr = self._get_returns(h)
                        if orr and abs(Corr.pearson(nr, orr)) > CORR_BLOCK:
                            too = True
                            break
                    if too:
                        print(f"  {sym}: ✗ 相关性过高，换")
                        self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
                        continue

            print(f"  {sym}: 评分{c['score']:.1f} 涨{c['change24h']:.1f}% 目标{target:.2f}U")
            ok, oi, msg = ex.buy(sym, target, equity)
            if ok:
                fq = oi.get("filled_amount", Decimal("0"))
                fp = oi.get("avg_price", Decimal("0"))
                if fq > 0 and fp > 0:
                    pm.add(sym, fp, fq, c["atr"], c["price"], aggr=True)
                    bought += 1
                    print(f"    ✓ {msg}")
                else:
                    print(f"    ✗ 无成交数据")
                    self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
            else:
                print(f"    ✗ {msg}")
                self._cooldown[sym] = AGGRESSIVE_COOLDOWN_ROUNDS
            time.sleep(0.5)
        print(f"  本轮补位: {bought}/{need}")

    def _get_returns(self, sym):
        try:
            cs = self.client.candles(sym, bar="1H", limit=100)
            closes = [sf(c[4]) for c in cs if len(c) > 4 and sf(c[4]) > 0]
            return [log(closes[i] / closes[i-1]) for i in range(1, len(closes))
                    if closes[i-1] > 0 and closes[i] > 0]
        except Exception:
            return []


# ==============================================
# 主逻辑
# ==============================================
def calc_equity(client):
    total = Decimal("0")
    try:
        for it in client.all_balances():
            if it["ccy"] == "USDT":
                total += it["availBal"]
            else:
                t = client.ticker(f"{it['ccy']}-USDT")
                px = sd(t.get("last", "0"))
                if px > 0:
                    total += it["availBal"] * px
    except Exception:
        return Decimal("1000")
    return total


def liquidate_all(client, ex, pm, tracker, td_mode):
    print("\n执行全仓清仓 → USDT")
    total = Decimal("0")
    for sym in list(pm.held()):
        try:
            pos = pm.positions[sym]
            ok, oi, msg = ex.sell(sym, pos["size"] * Decimal("0.998"))
            if ok:
                px = oi.get("avg_price", Decimal("0"))
                fq = oi.get("filled_amount", Decimal("0"))
                if px > 0 and fq > 0:
                    got = fq * px
                    total += got
                    ret = float((px - pos["entry_price"]) / pos["entry_price"])
                    tracker.record(ret, pos["entry_price"] * fq)
                print(f"  ✓ {sym}: {msg}")
                pm.remove(sym)
            else:
                print(f"  ✗ {sym}: {msg}")
        except Exception as e:
            print(f"  ✗ {sym}: {e}")
        time.sleep(0.8)
    print("\n扫尾归集...")
    col = Collector(client, ex.instruments, td_mode)
    _, _, extra = col.collect(exclude=set(), executor=ex, verbose=True)
    total += extra
    print(f"\n清仓共得 ≈{total:.4f} USDT")
    return total


def run_aggressive(client, per_max, interval, proxy, public_ip, td_mode):
    instruments = {}
    pm = PM()
    ex = Executor(client, instruments, td_mode)
    col = Collector(client, instruments, td_mode)

    print("\n--- 启动归集 ---")
    print("[1] 立即归集  [2] 跳过")
    if sinput("选择 [1]: ", "1").strip() != "2":
        ok, fail, got = col.collect(exclude=set(), executor=ex, verbose=True)
        print(f"归集: 成功{ok} 失败{fail} 得{got:.4f}U")

    initial = calc_equity(client)
    tracker = Tracker(initial)
    aggr = Aggressive(client, per_max, td_mode)

    print(f"\n{'='*66}")
    print(f"  [激进型] 单笔上限:{per_max}U | 初始:{initial:.4f}U | IP:{public_ip}")
    print(f"{'='*66}\n")

    round_n = 0
    while True:
        try:
            round_n += 1
            ts = datetime.now().strftime("%H:%M:%S")
            if round_n % IP_REFRESH_ROUNDS == 1:
                public_ip = get_public_ip(proxy, timeout=5)
                set_title(public_ip, f"激进|{calc_equity(client):.2f}U")
            print(f"\n[{ts}] 激进型 第{round_n}轮 | IP: {cip(public_ip)}")
            eq = calc_equity(client)
            tracker.update(eq)
            print(f"权益:{eq:.4f}U | 已实现:{tracker.realized:.4f} | "
                  f"持仓:{len(pm.held())}/{AGGRESSIVE_PICK_N}")

            if pm.held():
                print("\n[实时监控]")
                for sym in list(pm.held()):
                    try:
                        t = client.ticker(sym)
                        price = sd(t.get("last", "0"))
                        if price <= 0:
                            continue
                        candles = None
                        ema20 = float(price)
                        try:
                            candles = client.candles(sym, bar="1H", limit=100)
                            cl = [sf(c[4]) for c in candles if len(c) > 4]
                            if cl:
                                ema20 = float(Ind.ema(cl, 20) or float(price))
                        except Exception:
                            pass
                        pos = pm.positions[sym]
                        entry = float(pos["entry_price"])
                        profit = (float(price) - entry) / entry * 100
                        hold_h = (time.time() - pos["open_time"]) / 3600
                        print(f"  {sym}: 入{entry:.6f} 现{float(price):.6f} | "
                              f"盈亏{profit:+.2f}% | 持{hold_h:.1f}h")

                        r = pm.check_exit(sym, price, ema20, candles)
                        if r:
                            reason, detail = r
                            print(f"    → 触发[{reason}]: {detail}")
                            ratio = Decimal("0.5") if reason == "partial_take" else Decimal("0.998")
                            sell_size = pm.positions[sym]["size"] * ratio
                            ok, oi, msg = ex.sell(sym, sell_size)
                            if ok:
                                px = oi.get("avg_price", price)
                                fq = oi.get("filled_amount", sell_size)
                                if px > 0 and fq > 0:
                                    ret = float((px - pos["entry_price"]) / pos["entry_price"])
                                    tracker.record(ret, pos["entry_price"] * fq)
                                if reason == "partial_take":
                                    pos["size"] = pos["size"] - fq
                                    pos["partial_taken"] = True
                                    print(f"    ✓ 部分止盈 {msg}")
                                else:
                                    pm.remove(sym)
                                    print(f"    ✓ 全卖 {msg}")
                            else:
                                print(f"    ✗ {msg}")
                    except Exception as e:
                        print(f"  {sym}: 异常 - {str(e)[:80]}")

            aggr.maintain(pm, ex, tracker, eq, round_n)

            if round_n % COLLECT_INTERVAL_ROUNDS == 0:
                held = pm.held()
                print(f"\n[周期归集] 排除持仓: {held or '无'}")
                ok, fail, got = col.collect(exclude=held, executor=ex, verbose=True)
                if got > 0:
                    tracker.realized += got

            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n停止中...")
            total = liquidate_all(client, ex, pm, tracker, td_mode)
            time.sleep(2)
            final = calc_equity(client)
            print("\n" + "="*66)
            print("              激进型 最终报告")
            print("="*66)
            print(f"运行IP: {public_ip}")
            print(tracker.summary(final))
            print(f"清仓所得: {total:.4f} USDT")
            print(f"最终余额: {final:.4f} USDT")
            print(f"净利润: {final - tracker.initial:+.4f} USDT")
            print("="*66)
            return
        except Exception as e:
            print(f"主循环异常: {e}")
            traceback.print_exc()
            time.sleep(interval)


def run_standard(client, per_max, interval, proxy, public_ip, instruments, td_mode):
    pm = PM()
    ex = Executor(client, instruments, td_mode)
    col = Collector(client, instruments, td_mode)

    diagnose(client, list(instruments.keys()), per_max, td_mode)

    print("\n--- 启动归集 ---")
    print("[1] 立即归集  [2] 跳过")
    if sinput("选择 [1]: ", "1").strip() != "2":
        ok, fail, got = col.collect(exclude=set(), executor=ex, verbose=True)
        print(f"归集: 得{got:.4f}U")

    initial = calc_equity(client)
    tracker = Tracker(initial)

    print(f"\n{'='*66}")
    print(f"  [标准型] 交易对: {list(instruments.keys())}")
    print(f"  初始: {initial:.4f}U | IP: {public_ip}")
    print(f"{'='*66}\n")

    round_n = 0
    while True:
        try:
            round_n += 1
            ts = datetime.now().strftime("%H:%M:%S")
            if round_n % IP_REFRESH_ROUNDS == 1:
                public_ip = get_public_ip(proxy, timeout=5)
                set_title(public_ip, f"标准|{calc_equity(client):.2f}U")
            print(f"\n[{ts}] 标准型 第{round_n}轮 | IP: {cip(public_ip)}")
            eq = calc_equity(client)
            tracker.update(eq)
            print(f"权益:{eq:.4f}U | 持仓:{len(pm.held())}")

            for sym in list(pm.held()):
                try:
                    t = client.ticker(sym)
                    price = sd(t.get("last", "0"))
                    if price <= 0:
                        continue
                    candles = client.candles(sym, limit=100)
                    cl = [sf(c[4]) for c in candles if len(c) > 4]
                    ema20 = float(Ind.ema(cl, 20) or float(price))
                    r = pm.check_exit(sym, price, ema20, candles)
                    if r:
                        reason, detail = r
                        print(f"  {sym}: 卖[{reason}] {detail}")
                        pos = pm.positions[sym]
                        ok, oi, msg = ex.sell(sym, pos["size"] * Decimal("0.998"))
                        if ok:
                            px = oi.get("avg_price", price)
                            fq = oi.get("filled_amount", pos["size"])
                            if px > 0 and fq > 0:
                                ret = float((px - pos["entry_price"]) / pos["entry_price"])
                                tracker.record(ret, pos["entry_price"] * fq)
                            pm.remove(sym)
                            print(f"  ✓ {msg}")
                        else:
                            print(f"  ✗ {msg}")
                except Exception as e:
                    print(f"  {sym}: 异常 - {str(e)[:80]}")

            for sym in list(instruments.keys()):
                if pm.has(sym):
                    continue
                try:
                    cs = client.candles(sym, bar="1H", limit=300)
                    cl = [sf(c[4]) for c in cs if len(c) > 4 and sf(c[4]) > 0]
                    if len(cl) < 210:
                        continue
                    rsi = Ind.rsi(cl, 14)
                    if rsi is None or rsi >= 45:
                        continue
                    ema200 = Ind.ema(cl, 200) or cl[-1]
                    if cl[-1] <= ema200 * 0.98:
                        continue
                    atr = Ind.atr(cs, 14) or cl[-1] * MIN_ATR_RATIO
                    t = client.ticker(sym)
                    price = sd(t.get("last", "0"))
                    if price <= 0:
                        continue

                    inst = instruments[sym]
                    min_usdt = inst["base_min"] * price
                    target = min(per_max, eq * MAX_POSITION_RATIO)
                    if target < min_usdt:
                        boosted = min_usdt * Decimal("1.05")
                        if boosted <= per_max:
                            print(f"  {sym}: 目标{target:.2f}U < 最小{min_usdt:.4f}U → 提升")
                            target = boosted
                        else:
                            print(f"  {sym}: 最小{min_usdt:.4f}U > 上限，跳过")
                            continue
                    if target < MIN_TRADE_USDT:
                        continue

                    print(f"  {sym}: RSI={rsi:.1f} 买入 目标{target:.2f}U")
                    ok, oi, msg = ex.buy(sym, target, eq)
                    if ok:
                        fq = oi.get("filled_amount", Decimal("0"))
                        fp = oi.get("avg_price", price)
                        if fq > 0 and fp > 0:
                            ema20 = float(Ind.ema(cl, 20) or price)
                            pm.add(sym, fp, fq, atr, ema20, aggr=False)
                        print(f"  ✓ {msg}")
                    else:
                        print(f"  ✗ {msg}")
                except Exception as e:
                    print(f"  {sym}: 买入异常 - {str(e)[:80]}")

            if round_n % COLLECT_INTERVAL_ROUNDS == 0:
                held = pm.held()
                print(f"\n[周期归集] 排除: {held or '无'}")
                ok, fail, got = col.collect(exclude=held, executor=ex, verbose=True)
                if got > 0:
                    tracker.realized += got

            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n停止中...")
            total = liquidate_all(client, ex, pm, tracker, td_mode)
            time.sleep(2)
            final = calc_equity(client)
            print("\n" + "="*66)
            print("              标准型 最终报告")
            print("="*66)
            print(tracker.summary(final))
            print(f"清仓所得: {total:.4f} USDT")
            print(f"最终余额: {final:.4f} USDT")
            print(f"净利润: {final - tracker.initial:+.4f} USDT")
            print("="*66)
            return
        except Exception as e:
            print(f"主循环异常: {e}")
            traceback.print_exc()
            time.sleep(interval)


# ==============================================
# 主程序
# ==============================================
def main():
    global TD_MODE
    init_console()
    set_utf8_io()

    print("="*66)
    print("   OKX 量化交易机器人")
    print("="*66)

    try:
        print("\n--- API 凭证 ---")
        key = os.environ.get("OKX_API_KEY") or sinput("API Key: ")
        secret = os.environ.get("OKX_API_SECRET") or sinput("API Secret: ")
        passphrase = os.environ.get("OKX_PASSPHRASE") or sinput("Passphrase: ")
        if not key or not secret or not passphrase:
            print("凭证不能为空")
            sinput("按回车退出...")
            return

        print("\n--- 券商计划 (Broker Program) ---")
        print("[1] 普通用户（无brokerId）")
        print("[2] 券商账号（需填写brokerId和brokerApiKey）")
        bc = sinput("选择 [1]: ", "1").strip()
        brokerId = ""
        brokerApiKey = ""
        if bc == "2":
            brokerId = sinput("Broker ID (brokerCode): ").strip()
            brokerApiKey = sinput("Broker API Key: ").strip()
            if not brokerId or not brokerApiKey:
                print("  → brokerId和brokerApiKey不能为空，回退为普通用户")
                brokerId = ""
                brokerApiKey = ""
            else:
                print(f"  → 券商模式: brokerId={brokerId}")
        else:
            print("  → 普通用户模式")

        print("\n--- 交易模式 ---")
        print("[1] 实盘  [2] 模拟盘")
        sim = sinput("选择 [1]: ", "1").strip() == "2"
        print(f"→ {'模拟盘' if sim else '实盘'}")

        print("\n--- 账户模式（tdMode）---")
        print("  现货账户：选 1")
        print("  统一账户：选 2")
        print("[1] cash    [2] cross")
        tc = sinput("选择 [1]: ", "1").strip()
        TD_MODE = "cross" if tc == "2" else "cash"
        print(f"→ tdMode = {TD_MODE}")

        print("\n--- 网络 ---")
        print("[1] 使用系统默认（推荐）")
        print("[2] 手动输入代理")
        print("[3] 强制直连")
        pc = sinput("选择 [1]: ", "1").strip()

        proxy = None
        if pc == "2":
            proxy = sinput("代理地址(如 http://127.0.0.1:7890): ").strip() or None
            if proxy:
                print(f"  → 使用代理: {proxy}")
        elif pc == "3":
            print("  → 强制直连")
        else:
            print("  → 使用系统默认")

        print(f"\n最终网络: {('代理 ' + proxy) if proxy else '系统默认/直连'}")

        print("尝试获取公网IP...")
        public_ip = get_public_ip(proxy, timeout=5)
        if public_ip == "未知":
            print(f"  → 暂时无法获取公网IP（不影响运行）")
        else:
            print(f"  → {cip(public_ip)}")
        set_title(public_ip, "初始化中")

        print("\n--- 策略类型 ---")
        print("[1] 标准型（固定币种池 + 多因子评分）")
        print("[2] 激进型（涨幅榜顺延扫描 → 筛前10）")
        st = sinput("请选择 [1]: ", "1").strip()
        is_aggr = (st == "2")

        print("\n初始化 OKX SDK...")
        try:
            client = Client(key, secret, passphrase, simulated=sim, proxy=proxy,
                           brokerId=brokerId, brokerApiKey=brokerApiKey)
            print("  ✓ SDK 初始化成功")
        except Exception as e:
            print(f"  ✗ 初始化失败: {e}")
            traceback.print_exc()
            sinput("按回车退出...")
            return

        print("验证 API...")
        try:
            trading = client.balance(["USDT"])
            funding = client.funding_balance(["USDT"])
            t_usdt = trading.get("USDT", Decimal("0"))
            f_usdt = funding.get("USDT", Decimal("0"))
            print(f"  ✓ API验证通过")
            print(f"    交易账户 USDT: {t_usdt}")
            if f_usdt > 0:
                print(f"    资金账户 USDT: {f_usdt}")
            if f_usdt > 0 and t_usdt == 0:
                print("    → USDT 在资金账户，需先在 OKX 划转到交易账户才能现货下单")
            elif t_usdt == 0 and f_usdt == 0:
                print("    → 两个账户 USDT 均为 0，请对照 OKX App 确认余额位置")
        except Exception as e:
            err_str = str(e)
            print(f"  ✗ API验证失败: {err_str[:200]}")
            if "50111" in err_str:
                print("  → Passphrase 错误")
            elif "50113" in err_str:
                print("  → 签名错误")
            elif "50110" in err_str:
                print("  → IP不在白名单")
            elif "401" in err_str or "403" in err_str:
                print("  → 实盘/模拟盘不匹配")
            ans = sinput("\n是否仍要继续？(y/N): ", "n").strip().lower()
            if ans != "y":
                sinput("按回车退出...")
                return

        print("\n--- 最小买入（程序自设，测试连通可设很小） ---")
        print("  交易所另有 minSz；过小仍可能被拒。测试建议 0.01")
        global MIN_TRADE_USDT
        try:
            MIN_TRADE_USDT = Decimal(sinput("最小买入USDT [0.01]: ", "0.01"))
        except (InvalidOperation, ValueError):
            MIN_TRADE_USDT = Decimal("0.01")
        if MIN_TRADE_USDT <= 0:
            MIN_TRADE_USDT = Decimal("0.01")
        print(f"→ MIN_TRADE_USDT = {MIN_TRADE_USDT}")

        if is_aggr:
            print("\n--- 激进型参数 ---")
            per_max = Decimal(sinput("单笔最大USDT [50]: ", "50"))
            interval = int(sinput("检查间隔秒 [60]: ", "60"))
            run_aggressive(client, per_max, interval, proxy, public_ip, TD_MODE)
        else:
            print("\n--- 标准型参数 ---")
            default = "BTC-USDT,ETH-USDT,SOL-USDT,DOGE-USDT,XRP-USDT,ADA-USDT,AVAX-USDT,LINK-USDT"
            si = sinput(f"交易币种 [{default}]: ", default)
            syms = [norm(s) for s in si.replace("，", ",").split(",") if s.strip()]
            per_max = Decimal(sinput("单笔最大USDT [100]: ", "100"))
            interval = int(sinput("检查间隔秒 [60]: ", "60"))

            print("\n加载交易对...")
            instruments = {}
            # ★ 先批量加载
            client.all_instruments()
            for s in syms:
                try:
                    inst = client.instrument(s)
                    if inst["status"] != "live":
                        print(f"  ✗ {s}: state={inst.get('state')}")
                        continue
                    instruments[s] = inst
                    print(f"  ✓ {s}")
                except Exception as e:
                    print(f"  ✗ {s}: {str(e)[:120]}")
            if not instruments:
                print("\n无法加载任何交易对")
                sinput("按回车退出...")
                return

            run_standard(client, per_max, interval, proxy, public_ip,
                         instruments, TD_MODE)

    except Exception:
        print("\n程序异常：")
        traceback.print_exc()
        sinput("按回车退出...")


if __name__ == "__main__":
    main()
