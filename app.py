import streamlit as st
import sqlite3
import pandas as pd
from tvdatafeed import TvDatafeed, Interval
from pathlib import Path
from datetime import datetime

# ---------------- CONFIG ---------------- #

BASE = Path(__file__).parent
DB = BASE / "trades.db"

st.set_page_config("Trading Dashboard", layout="wide")
tv = TvDatafeed()

START_CAPITAL = 100000
RISK_PER_TRADE = 0.01

# ---------------- DATABASE ---------------- #

def db():
    return sqlite3.connect(DB, check_same_thread=False)

with db() as con:
    con.execute("""
    CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY,
        symbol TEXT,
        buy REAL,
        sl REAL,
        target REAL,
        status TEXT,
        ltp REAL,
        created TEXT,
        closed TEXT
    )
    """)

# ---------------- HELPERS ---------------- #

@st.cache_data(show_spinner=False)
def price(symbol):
    try:
        df = tv.get_hist(symbol,"NSE",Interval.in_daily,n_bars=2)
        return float(df.close.iloc[-1])
    except:
        return None

def load():
    return pd.read_sql("SELECT * FROM trades", db())

def add_trade(s,b,sl,t):
    with db() as con:
        con.execute("""
        INSERT INTO trades VALUES(NULL,?,?,?,?,?,?,?,?)
        """,(s,b,sl,t,"Pending",None,str(datetime.now()),None))

def update_price(i,p):
    with db() as con:
        con.execute("UPDATE trades SET ltp=? WHERE id=?", (p,i))

def update_status(i,s):
    with db() as con:
        con.execute("UPDATE trades SET status=? WHERE id=?", (s,i))

def close_trade(i):
    with db() as con:
        con.execute("UPDATE trades SET closed=? WHERE id=?", (str(datetime.now()),i))

def delete_trade(i):
    with db() as con:
        con.execute("DELETE FROM trades WHERE id=?", (i,))

# ---------------- LOGIC ---------------- #

def status(r):
    if r.ltp is None or r.ltp < r.buy:
        return "Pending"
    if r.ltp >= r.target:
        return "Target Hit"
    if r.ltp <= r.sl:
        return "Stoploss Hit"
    return "Active"

def position_size(capital, buy, sl):
    risk_amt = capital * RISK_PER_TRADE
    per_share = abs(buy-sl)
    return int(risk_amt/per_share) if per_share else 0

def r_multiple(entry, exit, sl):
    return round((exit-entry)/(entry-sl),2)

# ---------------- STYLE ---------------- #

st.markdown("""
<style>
.card{padding:14px;border-radius:12px;border:1px solid #ddd;margin-bottom:10px}
.pos{color:#16a34a;font-weight:bold}
.neg{color:#dc2626;font-weight:bold}
</style>
""",unsafe_allow_html=True)

# ---------------- UI ---------------- #

st.title("📈 Trading Dashboard")

with st.expander("➕ Add Trade"):
    c1,c2,c3,c4 = st.columns(4)
    s=c1.text_input("Symbol")
    b=c2.number_input("Buy",0.0)
    sl=c3.number_input("SL",0.0)
    t=c4.number_input("Target",0.0)
    if st.button("Add"):
        add_trade(s.upper(),b,sl,t)
        st.rerun()

if st.button("🔄 Refresh Prices"):
    df=load()
    for _,r in df.iterrows():
        update_price(r.id, price(r.symbol))
    st.rerun()

df=load()

# ---------------- STATUS UPDATE ---------------- #

for _,r in df.iterrows():
    s=status(r)
    if s!=r.status:
        update_status(r.id,s)
        if s in ["Target Hit","Stoploss Hit"]:
            close_trade(r.id)

df=load()

tabs=st.tabs(["Pending","Active","Target Hit","Stoploss Hit","Analytics"])

def render(tab,stt):
    with tab:
        d=df[df.status==stt]
        if d.empty:
            st.info("No trades")
        for _,r in d.iterrows():
            pnl=(r.ltp-r.buy) if r.ltp else 0
            cls="pos" if pnl>=0 else "neg"

            st.markdown(f"""
            <div class="card">
            <b>{r.symbol}</b><br>
            Buy {r.buy} | SL {r.sl} | Target {r.target}<br>
            LTP {r.ltp}<br>
            <span class="{cls}">P&L {round(pnl,2)}</span>
            </div>
            """,unsafe_allow_html=True)

            c1,c2=st.columns(2)
            if c1.button("Delete",key=f"d{r.id}"):
                delete_trade(r.id)
                st.rerun()

for t,s in zip(tabs,["Pending","Active","Target Hit","Stoploss Hit"]):
    render(t,s)

# ================= ANALYTICS ENGINE ================= #

with tabs[4]:

    closed=df[df.status.isin(["Target Hit","Stoploss Hit"])].copy()
    if closed.empty:
        st.info("No closed trades yet")
        st.stop()

    closed["created"]=pd.to_datetime(closed.created)
    closed["closed"]=pd.to_datetime(closed.closed)

    capital=START_CAPITAL
    equity=[]
    trade_data=[]

    for _,r in closed.sort_values("closed").iterrows():

        qty=position_size(capital,r.buy,r.sl)

        exit_price = r.target if r.status=="Target Hit" else r.sl

        pnl=(exit_price-r.buy)*qty

        capital+=pnl

        equity.append(capital)

        trade_data.append({
            "Symbol":r.symbol,
            "Exit":exit_price,
            "Qty":qty,
            "PnL":round(pnl,2),
            "Equity":round(capital,2),
            "R":r_multiple(r.buy,exit_price,r.sl),
            "Days":(r.closed-r.created).days
        })

    perf=pd.DataFrame(trade_data)

    # ----- Equity Curve (Numeric) ----- #

    st.subheader("📈 Equity Curve (Numeric)")
    st.dataframe(perf[["Equity"]])

    # ----- Drawdown ----- #

    peak=perf.Equity.cummax()
    dd=((perf.Equity-peak)/peak)*100
    max_dd=round(dd.min(),2)

    # ----- Monthly ----- #

    closed["month"]=closed.closed.dt.to_period("M")
    monthly=closed.groupby("month").size().reset_index(name="Trades")

    # ----- CAGR ----- #

    years=(closed.closed.max()-closed.created.min()).days/365
    cagr=round(((capital/START_CAPITAL)**(1/years)-1)*100,2) if years>0 else 0

    # ----- Metrics ----- #

    c1,c2,c3,c4=st.columns(4)
    c1.metric("Final Capital",round(capital,2))
    c2.metric("Total Return %",round((capital/START_CAPITAL-1)*100,2))
    c3.metric("Max Drawdown %",max_dd)
    c4.metric("CAGR %",cagr)

    st.divider()

    c5,c6,c7,c8=st.columns(4)
    c5.metric("Avg R",round(perf.R.mean(),2))
    c6.metric("Best R",round(perf.R.max(),2))
    c7.metric("Worst R",round(perf.R.min(),2))
    c8.metric("Avg Hold Days",round(perf.Days.mean(),1))

    st.divider()

    st.subheader("📆 Monthly Trade Count")
    st.dataframe(monthly)

    st.divider()

    st.subheader("📋 Trade Performance Log")
    st.dataframe(perf)

st.caption("Equity | R-multiples | Drawdown | CAGR | Capital based P&L | Cloud ready")
