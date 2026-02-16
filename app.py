import streamlit as st
import pandas as pd
import yfinance as yf
import psycopg2
from datetime import datetime

# ================= CONFIG ================= #

st.set_page_config("Trading Dashboard", layout="wide")

START_CAPITAL = 100000
RISK_PER_TRADE = 0.01

# ======== SUPABASE CONNECTION ======== #

DB_HOST = st.secrets["DB_HOST"]
DB_NAME = st.secrets["DB_NAME"]
DB_USER = st.secrets["DB_USER"]
DB_PASS = st.secrets["DB_PASS"]
DB_PORT = st.secrets["DB_PORT"]

def db():
    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )

# ================= PRICE ================= #

@st.cache_data(show_spinner=False)
def fetch_price(symbol):
    try:
        t = yf.Ticker(symbol + ".NS")
        df = t.history(period="5d", interval="1d")
        return float(df["Close"].iloc[-1])
    except:
        return None

# ================= CRUD ================= #

def load():
    with db() as con:
        return pd.read_sql("SELECT * FROM trades ORDER BY id DESC", con)

def execute(q,params=None):
    with db() as con:
        cur=con.cursor()
        cur.execute(q,params or [])
        con.commit()

def add_trade(s,b,sl,t,entered):
    status="Active" if entered else "Pending"
    execute("""
        INSERT INTO trades(symbol,buy,sl,target,status,ltp,entered,created)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
    """,(s,b,sl,t,status,None,entered,datetime.now()))

def update_price(i,p):
    execute("UPDATE trades SET ltp=%s WHERE id=%s",(p,i))

def update_status(i,s):
    execute("UPDATE trades SET status=%s WHERE id=%s",(s,i))

def close_trade(i):
    execute("UPDATE trades SET closed=%s WHERE id=%s",(datetime.now(),i))

def delete_trade(i):
    execute("DELETE FROM trades WHERE id=%s",(i,))

def edit_trade(i,b,sl,t):
    execute("UPDATE trades SET buy=%s,sl=%s,target=%s WHERE id=%s",(b,sl,t,i))

# ================= LIFECYCLE ================= #

def trade_status(r):

    if r.status in ["Target Hit","Stoploss Hit"]:
        return r.status

    if r.ltp is None:
        return r.status

    if r.ltp >= r.target:
        return "Target Hit"

    if r.ltp <= r.sl:
        return "Stoploss Hit"

    if r.status == "Active":
        return "Active"

    if r.ltp >= r.buy:
        return "Active"

    return "Pending"

# ================= ANALYTICS ================= #

def position_size(capital,buy,sl):
    risk=capital*RISK_PER_TRADE
    per=abs(buy-sl)
    return int(risk/per) if per else 0

def r_multiple(entry,exit,sl):
    return round((exit-entry)/(entry-sl),2)

# ================= STYLE ================= #

st.markdown("""
<style>
.card{padding:14px;border-radius:12px;border:1px solid #ddd;margin-bottom:10px}
.pos{color:#16a34a;font-weight:bold}
.neg{color:#dc2626;font-weight:bold}
</style>
""",unsafe_allow_html=True)

# ================= UI ================= #

st.title("📈 Trading Dashboard")

with st.expander("➕ Add Trade"):
    c1,c2,c3,c4=st.columns(4)
    s=c1.text_input("Symbol")
    b=c2.number_input("Buy",0.0)
    sl=c3.number_input("Stoploss",0.0)
    t=c4.number_input("Target",0.0)
    entered=st.checkbox("Already entered?")
    if st.button("Add Trade"):
        add_trade(s.upper(),b,sl,t,entered)
        st.rerun()

if st.button("🔄 Refresh Prices"):
    df=load()
    for _,r in df.iterrows():
        update_price(r.id,fetch_price(r.symbol))
    st.rerun()

df=load()

# ================= STATUS UPDATE ================= #

for _,r in df.iterrows():
    s=trade_status(r)
    if s!=r.status:
        update_status(r.id,s)
        if s in ["Target Hit","Stoploss Hit"]:
            close_trade(r.id)

df=load()

tabs=st.tabs(["Pending","Active","Target Hit","Stoploss Hit","Analytics"])

def render(tab,status):
    with tab:
        d=df[df.status==status]
        if d.empty:
            st.info("No trades")
        for _,r in d.iterrows():
            pnl=(r.ltp-r.buy) if r.ltp else 0
            col="pos" if pnl>=0 else "neg"

            st.markdown(f"""
            <div class="card">
            <b>{r.symbol}</b><br>
            Buy {r.buy} | SL {r.sl} | Target {r.target}<br>
            LTP {r.ltp}<br>
            <span class="{col}">P&L {round(pnl,2)}</span>
            </div>
            """,unsafe_allow_html=True)

            c1,c2=st.columns(2)
            if c1.button("Edit",key=f"e{r.id}"):
                st.session_state.edit=r.id
            if c2.button("Delete",key=f"d{r.id}"):
                delete_trade(r.id)
                st.rerun()

for t,s in zip(tabs,["Pending","Active","Target Hit","Stoploss Hit"]):
    render(t,s)

# ================= EDIT ================= #

if "edit" in st.session_state:
    tr=df[df.id==st.session_state.edit].iloc[0]
    st.subheader("Edit Trade")
    b=st.number_input("Buy",value=tr.buy)
    sl=st.number_input("SL",value=tr.sl)
    t=st.number_input("Target",value=tr.target)
    if st.button("Save"):
        edit_trade(tr.id,b,sl,t)
        del st.session_state.edit
        st.rerun()

# ================= ANALYTICS ================= #

with tabs[4]:

    closed=df[df.status.isin(["Target Hit","Stoploss Hit"])].copy()
    if closed.empty:
        st.info("No closed trades yet")
        st.stop()

    closed["created"]=pd.to_datetime(closed.created)
    closed["closed"]=pd.to_datetime(closed.closed)

    capital=START_CAPITAL
    rows=[]

    for _,r in closed.sort_values("closed").iterrows():
        qty=position_size(capital,r.buy,r.sl)
        exit_price=r.target if r.status=="Target Hit" else r.sl
        pnl=(exit_price-r.buy)*qty
        capital+=pnl

        rows.append({
            "Symbol":r.symbol,
            "PnL":round(pnl,2),
            "Equity":round(capital,2),
            "R":r_multiple(r.buy,exit_price,r.sl),
            "Days":(r.closed-r.created).days
        })

    perf=pd.DataFrame(rows)

    st.subheader("📈 Equity Curve (Numeric)")
    st.dataframe(perf[["Equity"]])

    peak=perf.Equity.cummax()
    dd=((perf.Equity-peak)/peak)*100

    years=(closed.closed.max()-closed.created.min()).days/365
    cagr=round(((capital/START_CAPITAL)**(1/years)-1)*100,2)

    c1,c2,c3,c4=st.columns(4)
    c1.metric("Final Capital",round(capital,2))
    c2.metric("Return %",round((capital/START_CAPITAL-1)*100,2))
    c3.metric("Max DD %",round(dd.min(),2))
    c4.metric("CAGR %",cagr)

st.caption("Supabase persistent DB • No data loss • Cloud production ready")
