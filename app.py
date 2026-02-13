import streamlit as st
import sqlite3
import pandas as pd
from tvDatafeed import TvDatafeed, Interval
from pathlib import Path

# ---------------- CLOUD SAFE PATH ---------------- #

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "trades.db"

# ---------------- PAGE CONFIG ---------------- #

st.set_page_config("Trading Dashboard", layout="wide")

tv = TvDatafeed()

# ---------------- DATABASE ---------------- #

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def create_table():
    with get_db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            buy REAL,
            sl REAL,
            target REAL,
            status TEXT,
            ltp REAL
        )
        """)

create_table()

# ---------------- PRICE FETCH ---------------- #

@st.cache_data(show_spinner=False)
def fetch_price(symbol):
    try:
        df = tv.get_hist(symbol, "NSE", Interval.in_daily, n_bars=2)
        return float(df.close.iloc[-1])
    except:
        return None

# ---------------- CRUD ---------------- #

def add_trade(sym,buy,sl,target):
    with get_db() as con:
        con.execute(
            "INSERT INTO trades(symbol,buy,sl,target,status,ltp) VALUES(?,?,?,?,?,?)",
            (sym,buy,sl,target,"Pending",None)
        )

def update_price(tid,price):
    with get_db() as con:
        con.execute("UPDATE trades SET ltp=? WHERE id=?", (price,tid))

def update_status(tid,status):
    with get_db() as con:
        con.execute("UPDATE trades SET status=? WHERE id=?", (status,tid))

def delete_trade(tid):
    with get_db() as con:
        con.execute("DELETE FROM trades WHERE id=?", (tid,))

def edit_trade(tid,b,sl,t):
    with get_db() as con:
        con.execute("UPDATE trades SET buy=?,sl=?,target=? WHERE id=?", (b,sl,t,tid))

def load():
    return pd.read_sql("SELECT * FROM trades", get_db())

# ---------------- STATUS LOGIC ---------------- #

def calc_status(r):
    if r.ltp is None:
        return "Pending"
    if r.ltp < r.buy:
        return "Pending"
    if r.ltp >= r.target:
        return "Target Hit"
    if r.ltp <= r.sl:
        return "Stoploss Hit"
    return "Active"

# ---------------- STYLE ---------------- #

st.markdown("""
<style>
.card {
padding:14px;
border-radius:12px;
border:1px solid #e0e0e0;
margin-bottom:10px;
}
.pnl-pos {color:#16a34a;font-weight:bold}
.pnl-neg {color:#dc2626;font-weight:bold}
</style>
""",unsafe_allow_html=True)

# ---------------- UI ---------------- #

st.title("📈 Trading Dashboard")

with st.expander("➕ Add Trade"):
    c1,c2,c3,c4 = st.columns(4)
    sym = c1.text_input("Symbol")
    buy = c2.number_input("Buy",0.0)
    sl = c3.number_input("SL",0.0)
    tgt = c4.number_input("Target",0.0)

    if st.button("Add"):
        add_trade(sym.upper(),buy,sl,tgt)
        st.rerun()

if st.button("🔄 Refresh Prices"):
    df = load()
    for _,r in df.iterrows():
        price = fetch_price(r.symbol)
        update_price(r.id,price)
    st.rerun()

df = load()

for _,r in df.iterrows():
    s = calc_status(r)
    if s != r.status:
        update_status(r.id,s)

df = load()

tabs = st.tabs(["Pending","Active","Target Hit","Stoploss Hit","Analytics"])

def draw(tab,status):
    with tab:
        d = df[df.status==status]
        if d.empty:
            st.info("No trades")
        for _,r in d.iterrows():
            pnl = (r.ltp-r.buy) if r.ltp else 0
            col = "pnl-pos" if pnl>=0 else "pnl-neg"

            st.markdown(f"""
            <div class="card">
            <b>{r.symbol}</b><br>
            Buy {r.buy} | SL {r.sl} | Target {r.target}<br>
            LTP {r.ltp}<br>
            <span class="{col}">P&L {round(pnl,2)}</span>
            </div>
            """,unsafe_allow_html=True)

            c1,c2 = st.columns(2)
            if c1.button("Edit",key=f"e{r.id}"):
                st.session_state.edit=r.id
            if c2.button("Delete",key=f"d{r.id}"):
                delete_trade(r.id)
                st.rerun()

for t,s in zip(tabs,["Pending","Active","Target Hit","Stoploss Hit"]):
    draw(t,s)

# ---------------- EDIT ---------------- #

if "edit" in st.session_state:
    tr = df[df.id==st.session_state.edit].iloc[0]
    st.subheader("Edit Trade")

    b = st.number_input("Buy",value=tr.buy)
    sl = st.number_input("SL",value=tr.sl)
    t = st.number_input("Target",value=tr.target)

    if st.button("Save"):
        edit_trade(tr.id,b,sl,t)
        del st.session_state.edit
        st.rerun()

# ---------------- ANALYTICS ---------------- #

with tabs[4]:
    total = len(df)
    wins = len(df[df.status=="Target Hit"])
    loss = len(df[df.status=="Stoploss Hit"])
    wr = round((wins/total)*100,2) if total else 0

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total",total)
    c2.metric("Targets",wins)
    c3.metric("Stoploss",loss)
    c4.metric("Win %",wr)

st.caption("Streamlit Cloud ready • Manual refresh only • SQLite local DB")
