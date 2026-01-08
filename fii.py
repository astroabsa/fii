import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import io
import re

# --- Configuration ---
# 1. 5paisa for Cash Data (Proven to work for you)
CASH_URL = "https://www.5paisa.com/share-market-today/fii-dii"
# 2. NSE Archives for F&O (The "Gold Standard" for missing data)
# We try multiple date formats if needed
NSE_ARCHIVE_URL = "https://nsearchives.nseindia.com/content/fo/fii_stats_{date}.xls"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*"
}

def clean_value(x):
    """Robust cleaner for currency strings."""
    if isinstance(x, (str, bytes)):
        # Remove 'Cr', commas, spaces, '₹'
        clean = str(x).replace(',', '').replace(' ', '').replace('Cr', '').replace('₹', '')
        try:
            return float(clean)
        except:
            return 0.0
    return float(x) if x else 0.0

@st.cache_data(ttl=300)
def fetch_cash_data_5paisa():
    """Fetches Cash data from 5paisa with robust parsing."""
    try:
        response = requests.get(CASH_URL, headers=HEADERS, timeout=10)
        # Parse all tables
        tables = pd.read_html(io.StringIO(response.text))
        
        for df in tables:
            # Flatten multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [' '.join(map(str, col)).strip() for col in df.columns.values]
            
            # Search for the table containing "DII" and "Net"
            cols_str = " ".join([str(c) for c in df.columns]).lower()
            if "dii" in cols_str and "net" in cols_str:
                
                # --- ROW FINDER LOGIC ---
                # Scan every row for a date pattern (DD-Mmm-YYYY)
                date_pattern = re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}")
                
                for index, row in df.iterrows():
                    row_text = str(row[0]) # First column is usually Date
                    
                    if date_pattern.search(row_text):
                        # Found a valid daily row!
                        date_val = row_text
                        
                        # Column Mapping (Standard 5paisa):
                        # Col 0: Date
                        # Col 1,2,3: FII (Buy, Sell, Net)
                        # Col 4,5,6: DII (Buy, Sell, Net)
                        fii_net = clean_value(row[3])
                        dii_net = clean_value(row[6])
                        
                        return date_val, fii_net, dii_net
                        
        return None, 0, 0
    except Exception as e:
        return None, 0, 0

def fetch_fno_nse(target_date_str):
    """Downloads F&O report from NSE Archives."""
    try:
        if target_date_str:
            base_date = datetime.strptime(target_date_str, "%d-%b-%Y")
            dates_to_try = [base_date]
        else:
            dates_to_try = [datetime.now()]
    except:
        dates_to_try = [datetime.now()]

    for d in dates_to_try:
        date_fmt = d.strftime("%d-%b-%Y") # e.g., 07-Jan-2026
        url = NSE_ARCHIVE_URL.format(date=date_fmt)
        
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                # NSE files are often CSVs masked as XLS
                try:
                    df = pd.read_csv(io.BytesIO(r.content))
                except:
                    try:
                        df = pd.read_excel(io.BytesIO(r.content))
                    except:
                        df = pd.read_html(io.BytesIO(r.content))[0]

                fii_fut = 0.0
                fii_opt = 0.0
                
                for idx, row in df.iterrows():
                    cat = str(row[0]).upper()
                    
                    if "INDEX FUTURES" in cat:
                        # Col 2 = Buy Value, Col 4 = Sell Value (Crores)
                        buy_val = clean_value(row.iloc[2])
                        sell_val = clean_value(row.iloc[4])
                        fii_fut = buy_val - sell_val
                        
                    if "INDEX OPTIONS" in cat:
                        buy_val = clean_value(row.iloc[2])
                        sell_val = clean_value(row.iloc[4])
                        fii_opt = buy_val - sell_val
                        
                return date_fmt, fii_fut, fii_opt
        except:
            continue
            
    return None, 0, 0

def analyze(fii_cash, fii_fut, dii_cash):
    score = 0
    reasons = []

    # 1. FII Cash
    if fii_cash > 0:
        score += 1
        reasons.append(f"🟢 FII Cash: +₹{fii_cash:,.0f} Cr")
    else:
        score -= 1
        reasons.append(f"🔴 FII Cash: -₹{abs(fii_cash):,.0f} Cr")

    # 2. FII Futures (Weighted)
    if fii_fut > 0:
        score += 2
        reasons.append(f"🟢 FII Futures: +₹{fii_fut:,.0f} Cr (Long Build-up)")
    elif fii_fut < 0:
        score -= 2
        reasons.append(f"🔴 FII Futures: -₹{abs(fii_fut):,.0f} Cr (Short Build-up)")

    # 3. DII Cash
    if dii_cash > 0:
        score += 0.5
        reasons.append(f"🟢 DII Cash: +₹{dii_cash:,.0f} Cr")
    else:
        score -= 0.5
        reasons.append(f"🔴 DII Cash: -₹{abs(dii_cash):,.0f} Cr")

    if score >= 2: return "Bullish", "green", reasons
    elif score <= -2: return "Bearish", "red", reasons
    return "Sideways / Volatile", "orange", reasons

# --- Streamlit UI ---
st.set_page_config(page_title="iTW Market Logic", layout="wide")

# --- HEADER SECTION (Title + Right Aligned Button) ---
col_head, col_btn = st.columns([6, 1])

with col_head:
    st.title("📊 iTW's Auto-Correlated Market Report")

with col_btn:
    st.write("") # Spacer
    st.write("") 
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

st.caption("Powered by : i-Tech World")
st.divider()

# --- FETCH DATA ---
cash_date, fii_cash, dii_cash = fetch_cash_data_5paisa()
fno_date, fii_fut, fii_opt = fetch_fno_nse(cash_date)

# --- MAIN DISPLAY ---
if cash_date:
    st.subheader(f"Readings as of {cash_date}")
    
    # Create 3 Columns for Layout
    c1, c2, c3 = st.columns([1, 1, 1.3]) # 3rd column slightly wider for text
    
    # Column 1: Cash Market
    with c1:
        st.markdown("### Equity Market")
        st.metric("FII Cash Net", f"₹ {fii_cash:,.2f} Cr", delta_color="normal")
        st.metric("DII Cash Net", f"₹ {dii_cash:,.2f} Cr", delta_color="normal")
    
    # Column 2: F&O Market
    with c2:
        st.markdown("### Futures Market")
        if fno_date:
            st.metric("FII Index Futures", f"₹ {fii_fut:,.2f} Cr", help="Net Buy - Sell Value")
            st.metric("FII Index Options", f"₹ {fii_opt:,.2f} Cr")
        else:
            st.warning("F&O Data Pending")
            st.caption("NSE Archives usually updates by 6:00 PM")

    # Column 3: AI Analysis
    with c3:
        st.markdown("### AI Analysis")
        verdict, color, reasons = analyze(fii_cash, fii_fut, dii_cash)
        
        st.markdown(f"#### Outlook: :{color}[{verdict}]")
        
        with st.container(border=True):
            for r in reasons:
                st.write(r)
                
else:
    st.error("Could not scrape Cash Data. Please refresh.")