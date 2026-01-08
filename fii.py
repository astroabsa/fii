import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import io
import re

# --- Configuration ---
CASH_URL = "https://www.5paisa.com/share-market-today/fii-dii"
# NSE Archive URL Pattern
NSE_ARCHIVE_URL = "https://nsearchives.nseindia.com/content/fo/fii_stats_{date}.xls"

# Browser Headers to bypass NSE blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.google.com/"
}

def clean_value(x):
    if isinstance(x, (str, bytes)):
        clean = str(x).replace(',', '').replace(' ', '').replace('Cr', '').replace('₹', '')
        try:
            return float(clean)
        except:
            return 0.0
    return float(x) if x else 0.0

@st.cache_data(ttl=300)
def fetch_cash_data_5paisa():
    """Fetches Cash data from 5paisa."""
    try:
        response = requests.get(CASH_URL, headers=HEADERS, timeout=10)
        tables = pd.read_html(io.StringIO(response.text))
        
        for df in tables:
            # Flatten multi-level headers
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [' '.join(map(str, col)).strip() for col in df.columns.values]
            
            # Identify table by columns
            cols_str = " ".join([str(c) for c in df.columns]).lower()
            if "dii" in cols_str and "net" in cols_str:
                date_pattern = re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}")
                for index, row in df.iterrows():
                    row_text = str(row[0])
                    if date_pattern.search(row_text):
                        date_val = row_text
                        fii_net = clean_value(row[3])
                        dii_net = clean_value(row[6])
                        return date_val, fii_net, dii_net
        return None, 0, 0
    except:
        return None, 0, 0

def fetch_fno_nse_recursive(start_date_str):
    """
    Recursively checks NSE Archives for the last 7 days.
    Returns the first valid data found.
    """
    try:
        if start_date_str:
            # Parse the start date (e.g. 07-Jan-2026)
            current_date = datetime.strptime(start_date_str, "%d-%b-%Y")
        else:
            current_date = datetime.now()
    except:
        current_date = datetime.now()

    # LOOP: Check today, then yesterday, etc. (up to 7 days back)
    for i in range(7): 
        check_date = current_date - timedelta(days=i)
        date_fmt = check_date.strftime("%d-%b-%Y") # e.g. 07-Jan-2025
        
        url = NSE_ARCHIVE_URL.format(date=date_fmt)
        
        try:
            # Short timeout because we expect 404s for future/missing dates
            r = requests.get(url, headers=HEADERS, timeout=3)
            
            if r.status_code == 200:
                # File found! Try parsing
                try:
                    df = pd.read_csv(io.BytesIO(r.content))
                except:
                    try:
                        df = pd.read_excel(io.BytesIO(r.content))
                    except:
                        # Sometimes NSE sends HTML masquerading as XLS
                        df = pd.read_html(io.BytesIO(r.content))[0]

                fii_fut = 0.0
                fii_opt = 0.0
                
                # Parse Rows
                for idx, row in df.iterrows():
                    cat = str(row[0]).upper()
                    if "INDEX FUTURES" in cat:
                        # Col 2=Buy(Val), Col 4=Sell(Val) usually
                        buy = clean_value(row.iloc[2])
                        sell = clean_value(row.iloc[4])
                        fii_fut = buy - sell
                    if "INDEX OPTIONS" in cat:
                        buy = clean_value(row.iloc[2])
                        sell = clean_value(row.iloc[4])
                        fii_opt = buy - sell
                        
                return date_fmt, fii_fut, fii_opt # Return the ACTUAL date found
        except:
            continue # Try next date
            
    return None, 0, 0

def analyze(fii_cash, fii_fut, dii_cash):
    score = 0
    reasons = []

    if fii_cash > 0:
        score += 1
        reasons.append(f"🟢 FII Cash: +₹{fii_cash:,.0f} Cr")
    else:
        score -= 1
        reasons.append(f"🔴 FII Cash: -₹{abs(fii_cash):,.0f} Cr")

    if fii_fut > 0:
        score += 2
        reasons.append(f"🟢 FII Futures: +₹{fii_fut:,.0f} Cr (Long Build-up)")
    elif fii_fut < 0:
        score -= 2
        reasons.append(f"🔴 FII Futures: -₹{abs(fii_fut):,.0f} Cr (Short Build-up)")

    if dii_cash > 0:
        score += 0.5
        reasons.append(f"🟢 DII Cash: +₹{dii_cash:,.0f} Cr")
    else:
        score -= 0.5
        reasons.append(f"🔴 DII Cash: -₹{abs(dii_cash):,.0f} Cr")

    if score >= 2: return "Bullish", "green", reasons
    elif score <= -2: return "Bearish", "red", reasons
    return "Sideways / Volatile", "orange", reasons

# --- UI Layout ---
st.set_page_config(page_title="Market Logic v5", layout="wide")

# Header
col_head, col_btn = st.columns([6, 1])
with col_head:
    st.title("📊 Auto-Correlated Market Report")
with col_btn:
    st.write("")
    st.write("") 
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# --- Sidebar for Manual Override ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.info("If F&O data is missing, the app looks back 7 days automatically.")
    
    # Allow manual date override (Fixes '2026' vs '2025' mismatch)
    use_manual = st.checkbox("Override F&O Date")
    manual_date = st.date_input("Select Date for F&O Fetch", datetime.now())

# --- Fetch Data ---
cash_date, fii_cash, dii_cash = fetch_cash_data_5paisa()

# Determine which date to use for F&O fetch
if use_manual:
    target_fno_date = manual_date.strftime("%d-%b-%Y")
else:
    target_fno_date = cash_date

# Fetch F&O (Recursive)
fno_date, fii_fut, fii_opt = fetch_fno_nse_recursive(target_fno_date)

# --- Display ---
if cash_date:
    st.subheader(f"Readings as of {cash_date}")
else:
    st.subheader("Latest Readings")

c1, c2, c3 = st.columns([1, 1, 1.3])

with c1:
    st.markdown("### Equity Market")
    if cash_date:
        st.caption(f"Source Date: {cash_date}")
        st.metric("FII Cash Net", f"₹ {fii_cash:,.2f} Cr")
        st.metric("DII Cash Net", f"₹ {dii_cash:,.2f} Cr")
    else:
        st.warning("Cash Data Not Found")

with c2:
    st.markdown("### Futures Market")
    if fno_date:
        # Visual cue if data is stale
        if cash_date and fno_date != cash_date:
             st.warning(f"⚠️ Showing data for {fno_date}")
             st.caption("(Latest available in NSE Archives)")
        else:
             st.caption(f"Source Date: {fno_date}")
             
        st.metric("FII Index Futures", f"₹ {fii_fut:,.2f} Cr")
        st.metric("FII Index Options", f"₹ {fii_opt:,.2f} Cr")
    else:
        st.error("F&O Data Not Found")
        st.caption("Try selecting a valid 2025 date in the Sidebar.")

with c3:
    st.markdown("### AI Analysis")
    # We analyze using whatever data we found (even if dates mismatch slightly)
    verdict, color, reasons = analyze(fii_cash, fii_fut, dii_cash)
    
    st.markdown(f"#### Outlook: :{color}[{verdict}]")
    with st.container(border=True):
        for r in reasons:
            st.write(r)
