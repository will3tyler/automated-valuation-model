import pandas as pd
from helpers import slope

#______________________________________________________________________________
#
# DISCOUNT RATES
#______________________________________________________________________________

#------------------------------------------------------------------------------
# COST OF EQUITY
#------------------------------------------------------------------------------

def CAPM(ticker,market,rf,erp):
    
    historystock = ticker.history(period="5y",interval="1mo")["Close"]
    historymarket = market.history(period="5y",interval="1mo")["Close"]
    rm = rf + erp
    
    df = pd.concat([historystock,historymarket],axis=1,join="inner",keys=["ticker","market"])
    
    s = df["ticker"].tolist()
    m = df["market"].tolist()
    
    s_chg = []
    
    for i in range(len(s)-1):
        chg = ((s[i+1])/s[i])-1
        s_chg.append(chg)
        
    if len(s_chg) < 24:
        return None
    
    m_chg = []
    
    for i in range(len(m)-1):
        chg = ((m[i+1]/m[i])-1)
        m_chg.append(chg)
        
    raw_beta = slope(m_chg, s_chg)
    
    b = (raw_beta * 0.67) + (1 * 0.33)
    b = (b * 0.5) + 0.5
    
    return rf + b * (rm - rf)

#------------------------------------------------------------------------------
# COST OF DEBT
#------------------------------------------------------------------------------

def cost_of_debt(ticker, rf, spreads):
    
    if "Interest Expense"  not in ticker.income_stmt.index or "EBIT" not in ticker.income_stmt.index:
        return None
    
    interest_expense = ticker.income_stmt.loc["Interest Expense"]
    ebit = ticker.income_stmt.loc["EBIT"]
    
    df = pd.concat([interest_expense, ebit], axis = 1, join = "inner", keys = ["interest_expense", "ebit"]).dropna()
    
    if df.empty or not df["interest_expense"].any():
        return None
    
    interest_coverage = df["ebit"].sum() / abs(df["interest_expense"]).sum()
    
    for min_coverage, spread in zip(spreads["min_coverage"], spreads["spread"]):
        if interest_coverage >= min_coverage:
            return rf + spread

#------------------------------------------------------------------------------
# COST OF PREFERRED
#------------------------------------------------------------------------------

def cost_of_preferred(ticker):
    
    if "Preferred Stock" not in ticker.balance_sheet.index or "Net Income" not in ticker.income_stmt.index or "Net Income Common Stockholders" not in ticker.income_stmt.index:
        return None
    
    preferred_stock = ticker.balance_sheet.loc["Preferred Stock"]
    preferred_dividends = ticker.income_stmt.loc["Net Income"] - ticker.income_stmt.loc["Net Income Common Stockholders"]
    
    df = pd.concat([preferred_stock, preferred_dividends], axis = 1, join = "inner", keys = ["preferred_stock", "preferred_dividends"]).dropna()
    
    if df.empty or df["preferred_stock"].sum() <= 0:
        return None
    
    return df["preferred_dividends"].sum() / df["preferred_stock"].sum()

#------------------------------------------------------------------------------
# TAX RATE
#------------------------------------------------------------------------------

def tax_rate(ticker):
    
    if "Tax Provision" not in ticker.income_stmt.index or "Pretax Income" not in ticker.income_stmt.index:
        return 0
        
    else:
        tax_provision = ticker.income_stmt.loc["Tax Provision"]
        ebt = ticker.income_stmt.loc["Pretax Income"]
        df = pd.concat([tax_provision, ebt], axis = 1, join = "inner", keys = ["tax_provision", "ebt"]).dropna()
        
        if df.empty or df["ebt"].sum() <= 0:
            return 0

    return max(0, min(1, df["tax_provision"].sum() / df["ebt"].sum()))

#------------------------------------------------------------------------------
# WACC
#------------------------------------------------------------------------------

def wacc(ticker, r, rf, spreads):
    
    debt_cost = cost_of_debt(ticker, rf, spreads)
    preferred_cost = cost_of_preferred(ticker)
    
    E = ticker.info.get("marketCap")
    
    if not E:
        return None
    
    if "Total Debt" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Total Debt"].dropna().empty or not debt_cost:
        D = 0
        debt_cost = 0
        
    else: 
        D = ticker.balance_sheet.loc["Total Debt"].dropna().iloc[0]
    
    if "Preferred Stock" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Preferred Stock"].dropna().empty or not preferred_cost:
        P = 0
        preferred_cost = 0
        
    else:
        P = ticker.balance_sheet.loc["Preferred Stock"].dropna().iloc[0]
    
    t = tax_rate(ticker)
    V = E + D + P
            
    return (E / V * r) + (D / V * debt_cost * (1 - t)) + (P / V * preferred_cost)