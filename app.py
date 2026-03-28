"""
StockMind AI — Indian Stock Market Dashboard
Final production build — Render + Railway

All fixes:
  1. load_dotenv() before everything
  2. get_db() reads os.environ directly (never Config class cache)
  3. Accepts MYSQLDATABASE or MYSQL_DB (Railway uses both names)
  4. cryptography package required for Railway MySQL8 caching_sha2_password
  5. yfinance: per-ticker fast_info only (bulk download unreliable on Render free tier)
  6. SESSION_COOKIE_SECURE via ProxyFix + before_request (Render HTTPS proxy)
  7. SameSite=Lax (correct for same-origin form POSTs)
  8. session.permanent=True so 7-day session works
  9. autocommit=False + explicit commit for reliable lastrowid
"""

import os, re, math, random, datetime, logging
from functools import wraps

from dotenv import load_dotenv
load_dotenv()  # MUST be first — loads .env before anything reads os.environ

import feedparser
import yfinance as yf
import numpy as np
import pymysql

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash, g)
from flask_bcrypt import Bcrypt
import jwt as pyjwt
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)

SECRET_KEY = os.environ.get("SECRET_KEY") or "stockmind-india-fallback-key-2026"
app.secret_key = SECRET_KEY
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,        # overridden per-request below
    SESSION_COOKIE_NAME="stockmind_session",
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=7),
)

# Trust Render's X-Forwarded-Proto / X-Forwarded-For headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

@app.before_request
def _set_secure_cookie():
    app.config["SESSION_COOKIE_SECURE"] = request.is_secure

bcrypt = Bcrypt(app)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

JWT_ALGORITHM     = "HS256"
JWT_EXP_HOURS     = 24 * 7
JWT_REFRESH_HOURS = 24 * 30

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    """
    Always reads from os.environ at call time — never a cached class attribute.
    Accepts both MYSQL_DB and MYSQLDATABASE (Railway exposes both names).
    """
    host     = os.environ.get("MYSQL_HOST") or os.environ.get("MYSQLHOST", "")
    user     = os.environ.get("MYSQL_USER") or os.environ.get("MYSQLUSER", "root")
    password = os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQLPASSWORD", "")
    db       = (os.environ.get("MYSQL_DB")
                or os.environ.get("MYSQLDATABASE")
                or os.environ.get("MYSQL_DATABASE")
                or "railway")
    try:
        port = int(os.environ.get("MYSQL_PORT") or os.environ.get("MYSQLPORT") or 3306)
    except (TypeError, ValueError):
        port = 3306

    if not host:
        raise RuntimeError(
            "MYSQL_HOST is not set. "
            "Go to Render → Environment and add: "
            "MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, MYSQL_PORT"
        )

    log.info("DB → %s:%s  db=%s  user=%s", host, port, db, user)
    return pymysql.connect(
        host=host, user=user, password=password,
        db=db, port=port,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=15,
    )


def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if commit:
                conn.commit()
                return cur.lastrowid
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        raise e
    finally:
        conn.close()


# ── JWT ───────────────────────────────────────────────────────────────────────
def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

def create_jwt(user_id, email, token_type="access"):
    now = _utcnow()
    hours = JWT_EXP_HOURS if token_type == "access" else JWT_REFRESH_HOURS
    return pyjwt.encode({
        "sub": user_id, "email": email, "type": token_type,
        "iat": now, "exp": now + datetime.timedelta(hours=hours),
    }, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_jwt(token):
    if not token: return None
    try:
        return pyjwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM],
                            options={"require": ["exp","iat","sub"]})
    except pyjwt.InvalidTokenError:
        return None

def _extract_bearer():
    auth = request.headers.get("Authorization","")
    if auth.startswith("Bearer "):
        t = auth.split(" ",1)[1].strip()
        return t or None
    return None

def _current_user():
    if hasattr(g, "_cu"): return g._cu
    if session.get("user_id"):
        g._cu = {"user_id": session["user_id"], "user_email": session.get("user_email","")}
        return g._cu
    raw = _extract_bearer()
    if raw:
        p = decode_jwt(raw)
        if p and p.get("type","access") == "access":
            g._cu = {"user_id": p["sub"], "user_email": p.get("email","")}
            return g._cu
    g._cu = None
    return None

def login_required(f):
    @wraps(f)
    def deco(*a, **kw):
        if _current_user(): return f(*a, **kw)
        flash("Please log in to access this page.", "warning")
        return redirect(url_for("login"))
    return deco

def api_login_required(f):
    @wraps(f)
    def deco(*a, **kw):
        if _current_user(): return f(*a, **kw)
        return jsonify({"error": "Authentication required", "code": 401}), 401
    return deco

def cur_uid():
    return _current_user()["user_id"]


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    info = {
        "MYSQL_HOST":     os.environ.get("MYSQL_HOST") or os.environ.get("MYSQLHOST","❌ NOT SET"),
        "MYSQL_PORT":     os.environ.get("MYSQL_PORT") or os.environ.get("MYSQLPORT","❌ NOT SET"),
        "MYSQL_USER":     os.environ.get("MYSQL_USER") or os.environ.get("MYSQLUSER","❌ NOT SET"),
        "MYSQL_DB":       os.environ.get("MYSQL_DB") or os.environ.get("MYSQLDATABASE","❌ NOT SET"),
        "MYSQL_PASSWORD": "✅ set" if (os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQLPASSWORD")) else "❌ NOT SET",
        "SECRET_KEY":     "✅ set" if os.environ.get("SECRET_KEY") else "⚠️ using fallback default",
    }
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        info["db_status"] = "✅ Connected"
    except Exception as e:
        info["db_status"] = f"❌ FAILED: {e}"
    return jsonify(info)


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard(): return render_template("dashboard.html")

@app.route("/news")
def news(): return render_template("news.html")

@app.route("/ai-suggestions")
def ai_suggestions(): return render_template("ai_suggestions.html")

@app.route("/mutual-funds")
def mutual_funds(): return render_template("mutual_funds.html")

@app.route("/sip-calculator")
def sip_calculator(): return render_template("sip_calculation.html")

@app.route("/watchlist")
@login_required
def watchlist(): return render_template("watchlist.html", stocks=Config.INDIAN_STOCKS)


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/signup", methods=["GET","POST"])
def signup():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method == "POST":
        full_name = request.form.get("full_name","").strip()
        email     = request.form.get("email","").strip().lower()
        mobile    = request.form.get("mobile","").strip()
        password  = request.form.get("password","")
        confirm   = request.form.get("confirm_password","")

        if not all([full_name, email, mobile, password]):
            flash("All fields are required.", "error")
            return render_template("signup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html")
        if not re.match(r"^[6-9]\d{9}$", mobile):
            flash("Enter a valid 10-digit Indian mobile number.", "error")
            return render_template("signup.html")

        try:
            existing = query("SELECT id FROM users WHERE email=%s", (email,), fetchone=True)
            if existing:
                flash("Email already registered. Please log in.", "error")
                return redirect(url_for("login"))
            pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            uid = query(
                "INSERT INTO users (full_name,email,mobile,password_hash) VALUES (%s,%s,%s,%s)",
                (full_name, email, mobile, pw_hash), commit=True
            )
            if not uid:
                raise Exception("Insert returned no ID — check DB tables exist")
            session.permanent = True
            session["user_id"]     = uid
            session["user_name"]   = full_name
            session["user_email"]  = email
            session["jwt_token"]   = create_jwt(uid, email)
            session["jwt_refresh"] = create_jwt(uid, email, "refresh")
            flash(f"Welcome, {full_name}! Account created.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            log.error("Signup error: %s", e)
            flash(f"Registration failed: {e}", "error")
    return render_template("signup.html")


@app.route("/login", methods=["GET","POST"])
def login():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method == "POST":
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html")
        try:
            user = query("SELECT * FROM users WHERE email=%s", (email,), fetchone=True)
        except Exception as e:
            log.error("DB error on login: %s", e)
            flash(f"Database error: {e}", "error")
            return render_template("login.html")
        if user and bcrypt.check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["user_id"]     = user["id"]
            session["user_name"]   = user["full_name"]
            session["user_email"]  = user["email"]
            session["jwt_token"]   = create_jwt(user["id"], user["email"])
            session["jwt_refresh"] = create_jwt(user["id"], user["email"], "refresh")
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET","POST"])
def forgot_password():
    if request.method == "POST":
        email   = request.form.get("email","").strip().lower()
        new_pw  = request.form.get("new_password","")
        confirm = request.form.get("confirm_password","")
        if new_pw != confirm:
            flash("Passwords do not match.", "error")
            return render_template("forgot_password.html")
        if len(new_pw) < 6:
            flash("Minimum 6 characters.", "error")
            return render_template("forgot_password.html")
        user = query("SELECT id FROM users WHERE email=%s", (email,), fetchone=True)
        if not user:
            flash("No account with that email.", "error")
            return render_template("forgot_password.html")
        pw_hash = bcrypt.generate_password_hash(new_pw).decode("utf-8")
        query("UPDATE users SET password_hash=%s WHERE email=%s", (pw_hash,email), commit=True)
        flash("Password reset. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


# ── API: Auth ─────────────────────────────────────────────────────────────────
@app.route("/api/auth/me")
@api_login_required
def api_auth_me():
    uid  = cur_uid()
    user = query("SELECT id,full_name,email FROM users WHERE id=%s", (uid,), fetchone=True)
    if not user: return jsonify({"error":"User not found"}), 404
    tok = create_jwt(user["id"], user["email"])
    session["jwt_token"] = tok
    return jsonify({"user_id":user["id"],"name":user["full_name"],"email":user["email"],
                    "access_token":tok,"token_type":"Bearer","expires_in":JWT_EXP_HOURS*3600})

@app.route("/api/auth/token", methods=["POST"])
def api_get_token():
    d = request.get_json(force=True,silent=True) or {}
    email, pw = d.get("email","").strip().lower(), d.get("password","")
    if not email or not pw: return jsonify({"error":"email and password required"}), 400
    user = query("SELECT * FROM users WHERE email=%s", (email,), fetchone=True)
    if user and bcrypt.check_password_hash(user["password_hash"], pw):
        return jsonify({"access_token":create_jwt(user["id"],user["email"]),
                        "refresh_token":create_jwt(user["id"],user["email"],"refresh"),
                        "token_type":"Bearer","user_id":user["id"],
                        "name":user["full_name"],"email":user["email"]})
    return jsonify({"error":"Invalid credentials"}), 401


# ── API: Market ───────────────────────────────────────────────────────────────
@app.route("/api/market-status")
def api_market_status():
    now  = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30)))
    wd   = now.weekday()
    h, m = now.hour, now.minute
    open_ = wd<5 and (h>9 or (h==9 and m>=15)) and (h<15 or (h==15 and m<=30))
    if wd>=5:            msg="Market Closed — Weekend"
    elif h<9 or (h==9 and m<15): msg="Pre-Market | Opens 9:15 AM IST"
    elif h>15 or (h==15 and m>30): msg="Market Closed | Opens tomorrow 9:15 AM IST"
    else:                msg="Market Open"
    return jsonify({"is_open":open_,"message":msg,
                    "current_time":now.strftime("%I:%M %p IST, %a %d %b")})


# ── API: Indices ──────────────────────────────────────────────────────────────
@app.route("/api/indices")
def api_indices():
    result = {}
    for symbol, name in Config.INDICES.items():
        try:
            info  = yf.Ticker(symbol).fast_info
            price = float(info.last_price or 0)
            prev  = float(info.previous_close or price)
            chg   = round(price - prev, 2)
            result[symbol] = {
                "name": name, "price": round(price,2),
                "change": chg,
                "change_pct": round((chg/prev*100) if prev else 0, 2),
                "high": round(float(info.day_high or price),2),
                "low":  round(float(info.day_low  or price),2),
                "volume": int(info.three_month_average_volume or 0),
            }
        except Exception as e:
            log.warning("Index %s: %s", symbol, e)
    return jsonify(result)


# ── API: Stocks ───────────────────────────────────────────────────────────────
@app.route("/api/stocks")
def api_stocks():
    """
    Fetch each stock via fast_info individually.
    Bulk yf.download() is unreliable on Render free tier (MultiIndex parsing
    breaks across yfinance versions). fast_info is lightweight and stable.
    """
    stocks = []
    for sym, name in Config.INDIAN_STOCKS.items():
        try:
            info  = yf.Ticker(sym).fast_info
            price = float(info.last_price or 0)
            prev  = float(info.previous_close or price)
            if price == 0:
                continue
            chg   = round(price - prev, 2)
            stocks.append({
                "symbol": sym, "name": name,
                "price":      round(price, 2),
                "change":     chg,
                "change_pct": round((chg/prev*100) if prev else 0, 2),
                "high":       round(float(info.day_high or price), 2),
                "low":        round(float(info.day_low  or price), 2),
                "volume":     int(info.three_month_average_volume or 0),
            })
        except Exception as e:
            log.warning("Stock %s: %s", sym, e)
    return jsonify(stocks)


# ── API: Chart ────────────────────────────────────────────────────────────────
@app.route("/api/stock-chart/<symbol>")
def api_stock_chart(symbol):
    period = request.args.get("period","1mo")
    if period not in {"1d","5d","1mo","3mo","6mo","1y","2y","5y"}: period="1mo"
    if not symbol.endswith(".NS") and not symbol.startswith("^"): symbol+=".NS"
    imap = {"1d":"5m","5d":"15m","1mo":"1d","3mo":"1d","6mo":"1d","1y":"1wk","2y":"1wk","5y":"1mo"}
    name = Config.INDIAN_STOCKS.get(symbol, symbol.replace(".NS",""))
    try:
        df = yf.download(symbol, period=period, interval=imap.get(period,"1d"),
                         auto_adjust=True, progress=False)
        df = df.dropna()
        if df.empty: return jsonify({"error":"No data"}), 404
        closes = df["Close"].values.flatten()
        return jsonify({
            "symbol":symbol,"name":name,"period":period,
            "dates": [str(d)[:16] for d in df.index],
            "open":  [_f(v) for v in df["Open"].values.flatten()],
            "high":  [_f(v) for v in df["High"].values.flatten()],
            "low":   [_f(v) for v in df["Low"].values.flatten()],
            "close": [_f(v) for v in closes],
            "volume":[int(v) for v in df["Volume"].values.flatten()],
            "sma20": _sma(closes,20), "sma50": _sma(closes,50),
        })
    except Exception as e:
        log.error("Chart %s: %s", symbol, e)
        return jsonify({"error":str(e)}), 500

def _f(v):
    try: x=float(v); return round(x,2) if not math.isnan(x) else None
    except: return None

def _sma(arr, w):
    out=[]
    for i in range(len(arr)):
        if i+1<w: out.append(None)
        else:
            chunk=[float(x) for x in arr[i+1-w:i+1] if x is not None]
            out.append(round(float(np.mean(chunk)),2) if chunk else None)
    return out


# ── API: Exchange Rate ────────────────────────────────────────────────────────
@app.route("/api/exchange-rate")
def api_exchange_rate():
    try:
        info = yf.Ticker("USDINR=X").fast_info
        rate = float(info.last_price or 84.0)
        prev = float(info.previous_close or rate)
        chg  = round(rate-prev, 4)
        return jsonify({"rate":round(rate,4),"change":chg,
                        "change_pct":round((chg/prev*100) if prev else 0,4)})
    except: return jsonify({"rate":84.0,"change":0,"change_pct":0})


# ── API: News ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("Economic Times","https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol",  "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("LiveMint",      "https://www.livemint.com/rss/markets"),
]
@app.route("/api/news")
def api_news():
    articles=[]
    for src,url in RSS_FEEDS:
        try:
            for e in feedparser.parse(url).entries[:8]:
                pub=e.get("published",e.get("updated",""))
                try: pub=datetime.datetime(*e.published_parsed[:6]).strftime("%d %b %Y, %I:%M %p")
                except: pass
                articles.append({"source":src,"title":e.get("title",""),
                                  "link":e.get("link","#"),
                                  "summary":e.get("summary",e.get("description","")),
                                  "published":pub})
        except Exception as e: log.warning("RSS %s: %s",src,e)
    random.shuffle(articles)
    return jsonify(articles[:30])


# ── API: AI Suggestions ───────────────────────────────────────────────────────
@app.route("/api/ai-suggestions")
def api_ai_suggestions():
    suggestions=[]
    syms=list(Config.INDIAN_STOCKS.items())
    random.shuffle(syms)
    for sym,name in syms[:12]:
        try:
            df=yf.download(sym,period="3mo",interval="1d",auto_adjust=True,progress=False)
            df=df.dropna()
            if len(df)<25: continue
            closes=df["Close"].values.flatten().astype(float)
            price=round(float(closes[-1]),2)
            m_ago=float(closes[-21]) if len(closes)>=21 else float(closes[0])
            mret=round(((price-m_ago)/m_ago)*100,2)
            s5=round(float(np.mean(closes[-5:])),2)
            s20=round(float(np.mean(closes[-20:])),2)
            vol=round(float(np.std(closes[-20:])/np.mean(closes[-20:])*100),2)
            score=50
            if price>s20: score+=15
            if s5>s20:    score+=10
            if mret>0:    score+=min(15,int(mret))
            if vol<3:     score+=10
            elif vol>6:   score-=10
            score=max(0,min(100,score))
            if score>=65:   sig,reason="BUY",f"Price ₹{price:,} above SMA20 ₹{s20:,}. +{mret}% monthly."
            elif score<=40: sig,reason="SELL",f"Price ₹{price:,} below SMA20 ₹{s20:,}. {mret}% monthly."
            else:           sig,reason="HOLD",f"Mixed signals near SMA20 ₹{s20:,}. Vol {vol}%."
            suggestions.append({"symbol":sym,"name":name,"price":price,"signal":sig,
                                 "score":score,"monthly_return":mret,"volatility":vol,
                                 "sma_5":s5,"sma_20":s20,"reason":reason})
        except Exception as e: log.warning("AI %s: %s",sym,e)
    suggestions.sort(key=lambda x:x["score"],reverse=True)
    return jsonify(suggestions)


# ── API: Mutual Funds ─────────────────────────────────────────────────────────
MUTUAL_FUNDS=[
    {"name":"Mirae Asset Large Cap Fund","amc":"Mirae Asset","category":"Large Cap","rating":5,"risk":"Moderate","returns_1y":18.4,"returns_3y":22.1,"returns_5y":17.8,"min_sip":1000,"min_lumpsum":5000,"expense_ratio":0.54},
    {"name":"Axis Bluechip Fund","amc":"Axis MF","category":"Large Cap","rating":5,"risk":"Moderate","returns_1y":17.2,"returns_3y":20.6,"returns_5y":16.9,"min_sip":500,"min_lumpsum":5000,"expense_ratio":0.52},
    {"name":"Kotak Emerging Equity Fund","amc":"Kotak MF","category":"Mid Cap","rating":5,"risk":"High","returns_1y":28.6,"returns_3y":31.2,"returns_5y":24.7,"min_sip":1000,"min_lumpsum":5000,"expense_ratio":0.46},
    {"name":"HDFC Mid-Cap Opportunities Fund","amc":"HDFC MF","category":"Mid Cap","rating":4,"risk":"High","returns_1y":26.3,"returns_3y":29.8,"returns_5y":23.1,"min_sip":500,"min_lumpsum":5000,"expense_ratio":0.76},
    {"name":"Nippon India Small Cap Fund","amc":"Nippon India MF","category":"Small Cap","rating":5,"risk":"High","returns_1y":38.4,"returns_3y":42.7,"returns_5y":32.6,"min_sip":100,"min_lumpsum":5000,"expense_ratio":0.68},
    {"name":"SBI Small Cap Fund","amc":"SBI MF","category":"Small Cap","rating":5,"risk":"High","returns_1y":34.2,"returns_3y":38.9,"returns_5y":29.4,"min_sip":500,"min_lumpsum":5000,"expense_ratio":0.70},
    {"name":"Parag Parikh Flexi Cap Fund","amc":"PPFAS MF","category":"Multi Cap","rating":5,"risk":"Moderate","returns_1y":22.7,"returns_3y":26.4,"returns_5y":21.3,"min_sip":1000,"min_lumpsum":1000,"expense_ratio":0.58},
    {"name":"Axis Long Term Equity Fund (ELSS)","amc":"Axis MF","category":"ELSS (Tax Saving)","rating":5,"risk":"High","returns_1y":19.8,"returns_3y":23.5,"returns_5y":18.6,"min_sip":500,"min_lumpsum":500,"expense_ratio":0.56},
    {"name":"Mirae Asset Tax Saver Fund (ELSS)","amc":"Mirae Asset","category":"ELSS (Tax Saving)","rating":5,"risk":"High","returns_1y":21.4,"returns_3y":25.1,"returns_5y":20.2,"min_sip":500,"min_lumpsum":500,"expense_ratio":0.49},
    {"name":"UTI Nifty 50 Index Fund","amc":"UTI MF","category":"Index Fund","rating":4,"risk":"Moderate","returns_1y":14.6,"returns_3y":18.3,"returns_5y":14.1,"min_sip":500,"min_lumpsum":5000,"expense_ratio":0.20},
    {"name":"HDFC Index Fund — NIFTY 50","amc":"HDFC MF","category":"Index Fund","rating":4,"risk":"Moderate","returns_1y":14.4,"returns_3y":18.1,"returns_5y":13.9,"min_sip":100,"min_lumpsum":100,"expense_ratio":0.20},
    {"name":"ICICI Pru Balanced Advantage Fund","amc":"ICICI Prudential","category":"Hybrid Fund","rating":4,"risk":"Moderate","returns_1y":16.1,"returns_3y":19.4,"returns_5y":15.2,"min_sip":100,"min_lumpsum":5000,"expense_ratio":0.82},
    {"name":"Canara Robeco Flexi Cap Fund","amc":"Canara Robeco","category":"Multi Cap","rating":4,"risk":"Moderate","returns_1y":20.3,"returns_3y":24.1,"returns_5y":19.0,"min_sip":1000,"min_lumpsum":5000,"expense_ratio":0.62},
    {"name":"DSP Midcap Fund","amc":"DSP MF","category":"Mid Cap","rating":4,"risk":"High","returns_1y":24.7,"returns_3y":28.2,"returns_5y":22.4,"min_sip":500,"min_lumpsum":1000,"expense_ratio":0.67},
]
@app.route("/api/mutual-funds")
def api_mutual_funds(): return jsonify(MUTUAL_FUNDS)


# ── API: SIP ──────────────────────────────────────────────────────────────────
@app.route("/api/sip-calculate", methods=["POST"])
def api_sip_calculate():
    d=request.get_json(force=True,silent=True) or {}
    try:
        mo=float(d.get("monthly_investment",0))
        ar=float(d.get("expected_return",12))
        yr=int(d.get("time_period",10))
        if mo<=0 or ar<=0 or yr<=0: return jsonify({"error":"Invalid"}),400
        r=ar/12/100; n=yr*12
        fv=mo*(((1+r)**n-1)/r)*(1+r); inv=mo*n
        bd=[{"year":y,"invested":round(mo*y*12,2),
             "value":round(mo*(((1+r)**(y*12)-1)/r)*(1+r),2),
             "gains":round(mo*(((1+r)**(y*12)-1)/r)*(1+r)-mo*y*12,2)} for y in range(1,yr+1)]
        return jsonify({"total_investment":round(inv,2),"estimated_returns":round(fv-inv,2),
                        "total_value":round(fv,2),"breakdown":bd})
    except Exception as e: return jsonify({"error":str(e)}),400


# ── API: Watchlist ────────────────────────────────────────────────────────────
@app.route("/api/watchlist")
@api_login_required
def api_get_watchlist():
    uid=cur_uid()
    items=query("SELECT stock_symbol,stock_name,added_at FROM watchlist WHERE user_id=%s ORDER BY added_at DESC",
                (uid,),fetchall=True) or []
    enriched=[]
    for item in items:
        sym=item["stock_symbol"]
        e={"symbol":sym,"name":item["stock_name"],"added_at":str(item["added_at"]),
           "price":None,"change":None,"change_pct":None}
        try:
            info=yf.Ticker(sym).fast_info
            price=float(info.last_price or 0)
            prev=float(info.previous_close or price)
            chg=round(price-prev,2)
            e.update({"price":round(price,2),"change":chg,
                      "change_pct":round((chg/prev*100) if prev else 0,2)})
        except: pass
        enriched.append(e)
    return jsonify(enriched)

@app.route("/api/watchlist/add", methods=["POST"])
@api_login_required
def api_watchlist_add():
    uid=cur_uid()
    d=request.get_json(force=True,silent=True) or {}
    sym=d.get("symbol","").strip(); name=d.get("name",sym)
    if not sym: return jsonify({"success":False,"error":"Symbol required"}),400
    cnt=query("SELECT COUNT(*) as c FROM watchlist WHERE user_id=%s",(uid,),fetchone=True)
    if cnt and cnt["c"]>=20: return jsonify({"success":False,"error":"Limit 20 reached"}),400
    try:
        query("INSERT IGNORE INTO watchlist (user_id,stock_symbol,stock_name) VALUES (%s,%s,%s)",
              (uid,sym,name),commit=True)
        return jsonify({"success":True,"message":f"{name} added"})
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

@app.route("/api/watchlist/remove", methods=["POST"])
@api_login_required
def api_watchlist_remove():
    uid=cur_uid()
    d=request.get_json(force=True,silent=True) or {}
    sym=d.get("symbol","").strip()
    if not sym: return jsonify({"success":False,"error":"Symbol required"}),400
    query("DELETE FROM watchlist WHERE user_id=%s AND stock_symbol=%s",(uid,sym),commit=True)
    return jsonify({"success":True})

@app.route("/api/watchlist/symbols")
@api_login_required
def api_watchlist_symbols():
    uid=cur_uid()
    items=query("SELECT stock_symbol FROM watchlist WHERE user_id=%s",(uid,),fetchall=True) or []
    return jsonify([i["stock_symbol"] for i in items])


# ── Errors ────────────────────────────────────────────────────────────────────
@app.errorhandler(404)
def e404(e):
    if request.path.startswith("/api/"): return jsonify({"error":"Not found"}),404
    return render_template("dashboard.html"),404

@app.errorhandler(500)
def e500(e):
    if request.path.startswith("/api/"): return jsonify({"error":"Server error"}),500
    return render_template("dashboard.html"),500


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
