import yfinance as yf
import pandas as pd
import os
import warnings as pywarnings
from helpers import CAGR
from data import load_ciks, load_spreads, load_erp, edgar_rawdata, edgar_roe
from rates import CAPM
from growth import terminal_growth, fcfe_highgrowth
from models import implied_roe, ri_dataframe
from output import master_value, recommendation, implied_growth, sensitivity

#______________________________________________________________________________
#
# MAIN CODE
#______________________________________________________________________________

#------------------------------------------------------------------------------
# INPUTS
#------------------------------------------------------------------------------

pywarnings.filterwarnings("ignore", category = UserWarning, module = "openpyxl")
print("The SEC requires a contact for EDGAR requests (name and email). It is sent only to sec.gov as the User-Agent header.")
first_last = input("First & Last Name: ").strip()

while first_last == "":
    print("First & Last Name required.")
    first_last = input("First & Last Name: ").strip()

email = input("Email: ").strip()

while email == "":
    print("Email required.")
    email = input("Email: ").strip()

HEADERS = {"User-Agent": f"{first_last} {email}"}
market = yf.Ticker("^GSPC")
tnx = yf.Ticker("^TNX")
rf = tnx.history(period="5d")["Close"].dropna().iloc[-1]/100
years_historical = 5
years_projected = 10
gdp_years = 30
gdp = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP")
gdp_now = gdp["GDP"].iloc[-1]
gdp_past = gdp["GDP"].iloc[-1-gdp_years*4]
gdp_g = CAGR(gdp_now,gdp_past,gdp_years)
ciks = load_ciks(HEADERS)
spreads = load_spreads()
erp = load_erp()
base_rates = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_rates.csv"))["growth"]

#------------------------------------------------------------------------------
# TICKER INPUT
#------------------------------------------------------------------------------

while True:

    while True: 
        print()
        symbol = input("Stock Ticker: ").strip().upper()
        
        if symbol == "":
            
            break
        
        print()
        ticker = yf.Ticker(symbol)
        
        try:
            not_found = ticker.history(period = "5d").empty
            
        except Exception:
            not_found = True

        if not_found:
            print("Ticker not found. Try again.")
            
            continue
        
        if ticker.info.get("quoteType") != "EQUITY":
            print("Model only accepts equity stocks. Try again.")
            
            continue
        
        if ticker.info.get("industry", "").startswith("REIT"):
            print("This model does not value REITs. Try again.")
            
            continue
        
        if ticker.info.get("financialCurrency") != ticker.info.get("currency"):
            print("Financial statements are not in the trading currency; cannot value. Try again.")
            
            continue
        
        r = CAPM(ticker, market, rf, erp)
        
        if r is None:
            print("Price history insufficient, or yahoo finance is broken for this stock. Try again.")
            
            continue
        
        data = edgar_rawdata(ticker, ciks, HEADERS)
        g_L = terminal_growth(ticker, data, r, rf, gdp_g, years_projected)
        price = ticker.history(period = "5d")["Close"].dropna().iloc[-1]
        name = ticker.info.get("longName", symbol)
    
        break
    
    if symbol == "":
        
        break
    
#------------------------------------------------------------------------------
# RESULTS
#------------------------------------------------------------------------------
    
    master, models, warnings = master_value(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected)
    
    print("_________________________________________________________")
    print("VALUATIONS: ", name)
    print()
    
    if master is None:
        print("No valuation model can accurately estimate intrinsic value.")
    
    else:
        table = round(models, 2)
        table["weight"] = table["weight"].astype(str) + "%"
        table["value"] = table["value"].fillna("-")
        
        for i in table.to_string().split("\n"):
            print("                        ", i)
        print()
        print("                                      5 = Highly reliable")
        print("                               0 = Not reliable, Unusable")
        print("_________________________________________________________")
        print("INITIAL MODEL RESULT")
        print("                             Current Market Value: ", round(price, 2))
        print("                           Master Intrinsic Value: ", round(master, 2))
        print("_________________________________________________________")
        print("CURRENT MARKET PRICE ASSUMPTIONS")
        print()
        
        g_needed = implied_growth(ticker, data, r, g_L, gdp_g, years_projected, price)
        roe_needed = implied_roe(ticker, data, r, years_projected, price)
        
        if g_needed is not None:
            g_used, _, _ = fcfe_highgrowth(ticker, data, g_L, gdp_g)
            share = (base_rates >= g_needed).sum() / len(base_rates)
            print(f"Market price implies FCFE growth of {g_needed:.1%}. Model uses {g_used:.1%}.")
            print(f"Of {len(base_rates)} ten-year periods at 227 large companies (2010 - 2016), {share:.0%} grew that fast.")
            
        if roe_needed is not None:
            df_ri = ri_dataframe(ticker)
            
            roe_shorthistory = df_ri["net_income"].sum() / df_ri["equity"].sum()
            roe_longhistory = edgar_roe(data)
            
            print(f"Market price implies a permanent ROE of {roe_needed:.1%}.")
            
            if roe_longhistory is not None:
                print(f"ROE last {len(df_ri)} years is {roe_shorthistory:.1%}; median ROE over {len(roe_longhistory)} years is {roe_longhistory.median():.1%}.")
                
            else:
                print(f"ROE last {len(df_ri)} years is {roe_shorthistory:.1%}.")
    
        if g_needed is None and roe_needed is None:
            print("No reverse calculation available.")
    
        
        print("_________________________________________________________")
        print("SENSITIVITY ANALYSIS")
        print()
        
        s_table = round(sensitivity(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected), 2)
        for i in s_table.to_string().split("\n"):
            print(i)
        print("_________________________________________________________")
        print("FINAL VERDICT")
        print()
        valued, verdict = recommendation(s_table, price)
        print(valued)
        print(verdict)
        if warnings:
            print()
            print("                       VERDICT IS UNRELIABLE. REASON(S):")
            for i in warnings:
                print(i)