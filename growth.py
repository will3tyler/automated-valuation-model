import pandas as pd
import math
from helpers import normalize_series, slope, CAGR, financialco_filter
from data import edgar_roe, edgar_seriesdata, common_dividends
from rates import tax_rate

#______________________________________________________________________________
#
# GROWTH
#______________________________________________________________________________

#------------------------------------------------------------------------------
# ROE PERSISTENCE (PHI)
#------------------------------------------------------------------------------

def company_phi(data):
    
    roe = edgar_roe(data)
    
    if roe is None:       
        return None, 0
    
    roe = normalize_series(roe)
    
    roe_last = []
    roe_now = []
    
    for i in range(1, len(roe)):
        days = (roe.index[i] - roe.index[i-1]).days 
        
        if days > 340 and days < 380:
            roe_last.append(roe.iloc[i-1])
            roe_now.append(roe.iloc[i])
            
    pairs = len(roe_last)
    
    if pairs < 2:
        return None, 0
            
    phi = slope(roe_last, roe_now)
    phi = max(0, min(1, phi))
    
    return phi, pairs

def blended_phi(data):
    
    phi, pairs = company_phi(data)
    
    if phi is None:
        phi = 0.62
        
    w = pairs / (pairs + 10)  
    
    return w * phi + (1 - w) * 0.62

def target_roe(data, r, roe_now):
    
    roe = edgar_roe(data)
    
    if roe is None or len(roe) < 5:
        return r
    
    roe = normalize_series(roe)
    
    median_roe = roe.median()
    
    w = len(roe) / (len(roe) + 10)
    
    target = w * median_roe + (1 - w) * r
    
    high = max(r, roe_now)
    low = min(r, roe_now)
    
    return max(low, min(target, high))

#------------------------------------------------------------------------------
# REVENUE GROWTH
#------------------------------------------------------------------------------

def revenue_growth(ticker, data):
    
    if data is not None:
    
        for tag in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]:
            revenue = edgar_seriesdata(data, tag)
            
            if revenue is not None and len(revenue) >= 6 and (pd.Timestamp.now() - revenue.index[-1]).days < 731:
                return historical_growth(revenue)
            
    if "Total Revenue" in ticker.income_stmt.index:
        revenue = ticker.income_stmt.loc["Total Revenue"].dropna().sort_index()
        
        if len(revenue) >= 3 and revenue.iloc[0] > 0 and revenue.iloc[-1] > 0:
            return CAGR(revenue.iloc[-1], revenue.iloc[0], len(revenue) - 1)
            
    return None

#------------------------------------------------------------------------------
# TERMINAL GROWTH
#------------------------------------------------------------------------------

def terminal_growth(ticker, data, r, rf, gdp_g, years_projected):
    
    phi = blended_phi(data)
    
    if "Net Income Common Stockholders" not in ticker.income_stmt.index or "Common Stock Equity" not in ticker.balance_sheet.index:
        return min(gdp_g, rf)
    
    net_income = ticker.income_stmt.loc["Net Income Common Stockholders"]
    equity = ticker.balance_sheet.loc["Common Stock Equity"]
    dividends = common_dividends(ticker, net_income)
    
    if dividends is None:
        return min(gdp_g, rf)
    
    df = pd.concat([net_income, equity, dividends],axis=1,join="inner", keys = ["net_income", "equity", "dividends"]).dropna()
    
    if len(df) < 3 or (df["equity"] <= 0).any() or df["net_income"].sum() <= 0:
        return min(gdp_g, rf)
    
    roe_fadestart = df["net_income"].sum() / df["equity"].sum()
    
    retention = 1 - df["dividends"].sum() / df["net_income"].sum()
    retention = max(0, min(1, retention))
    
    target = target_roe(data, r, roe_fadestart)
    roe_final = target + (roe_fadestart - target) * (phi ** years_projected)
    
    return min(roe_final * retention, min(gdp_g, rf))

#------------------------------------------------------------------------------
# HISTORICAL GROWTH
#------------------------------------------------------------------------------

def historical_growth(series):
    
    if series is None:
        return None
    
    series = normalize_series(series).tail(10)
    
    s = pd.Series(series)
    if (s <= 0).any():
        return None
    
    if len(series) < 4:
        return None
    
    years = series.index.year.tolist()
    logs = []
    
    for i in series:
        logs.append(math.log(i))
        
    regression = slope(years, logs)
    
    return math.exp(regression) - 1

#------------------------------------------------------------------------------
# FCFE HIGH GROWTH
#------------------------------------------------------------------------------

def fcfe_highgrowth(ticker, data, g_L, gdp_g):
    
    if financialco_filter(ticker):
        return None, False, None
    
    if "Operating Cash Flow" in ticker.cashflow.index and "Capital Expenditure" in ticker.cashflow.index and "Net Income Common Stockholders" in ticker.income_stmt.index and "Common Stock Equity" in ticker.balance_sheet.index:
        cfo = ticker.cashflow.loc["Operating Cash Flow"]
        capex = ticker.cashflow.loc["Capital Expenditure"]
        net_income = ticker.income_stmt.loc["Net Income Common Stockholders"]
        equity = ticker.balance_sheet.loc["Common Stock Equity"]
        
    else:
        return None, False, None
    
    
    if "Net Issuance Payments Of Debt" in ticker.cashflow.index:
        debt_pmts = ticker.cashflow.loc["Net Issuance Payments Of Debt"]
        
    else:
        debt_pmts = pd.Series(0, index = cfo.index)
        
    if "Total Debt" in ticker.balance_sheet.index:
        total_debt = ticker.balance_sheet.loc["Total Debt"]
        
    else:
        total_debt = pd.Series(0, index = cfo.index)
        
    df = pd.concat([cfo, capex, net_income, equity, debt_pmts, total_debt], axis = 1, join = "inner", keys = ["cfo", "capex", "net_income", "equity", "debt_pmts", "total_debt"]).dropna(subset = ["cfo", "capex", "net_income", "equity", "debt_pmts"]).sort_index()
    
    df["fcfe"] = df["cfo"] + df["capex"] + df["debt_pmts"]
    df["debt_ratio"] = df["total_debt"] / (df["total_debt"] + df["equity"])
    
    if df.empty or df["net_income"].sum() <= 0:
        return None, False, None
    
    rev_g = revenue_growth(ticker, data)
    
    if rev_g is None:
        g = gdp_g
        
    else:
        g = (max(0, rev_g) * 0.5) + gdp_g
        
    return g, True, df

#------------------------------------------------------------------------------
# FCFF HIGH GROWTH
#------------------------------------------------------------------------------

def fcff_highgrowth(ticker, data, g_L, gdp_g):
    
    if financialco_filter(ticker):
        return None, False, None
    
    if "Operating Cash Flow" in ticker.cashflow.index and "Capital Expenditure" in ticker.cashflow.index and "EBIT" in ticker.income_stmt.index and "Invested Capital" in ticker.balance_sheet.index:
        cfo = ticker.cashflow.loc["Operating Cash Flow"]
        capex = ticker.cashflow.loc["Capital Expenditure"]
        ebit = ticker.income_stmt.loc["EBIT"]
        invested_capital = ticker.balance_sheet.loc["Invested Capital"]
        
    else:
        return None, False, None
    
    
    if "Interest Expense" in ticker.income_stmt.index:
        interest_expense = ticker.income_stmt.loc["Interest Expense"].fillna(0)
        
    else:
        interest_expense = pd.Series(0, index = cfo.index)
        
    if "Interest Income" in ticker.income_stmt.index:
        interest_income = ticker.income_stmt.loc["Interest Income"].fillna(0)
        
    else:
        interest_income = pd.Series(0, index = cfo.index)
        
    df = pd.concat([cfo, capex, ebit, invested_capital, interest_expense, interest_income], axis = 1, join = "inner", keys = ["cfo", "capex", "ebit", "invested_capital", "interest_expense", "interest_income"]).dropna().sort_index()
    
    t = tax_rate(ticker)
    
    df["nopat"] = (df["ebit"] - df["interest_income"]) * (1 - t)
    df["fcff"] = df["cfo"] + df["capex"] + (abs(df["interest_expense"]) - df["interest_income"]) * (1 - t)
    
    if df.empty or df["nopat"].sum() <= 0:
        return None, False, None
    
    if (df["invested_capital"] <= 0).any():
        return g_L, False, df
    
    rev_g = revenue_growth(ticker, data)
    
    if rev_g is None:
        g = gdp_g
        
    else:
        g = (max(0, rev_g) * 0.5) + gdp_g
        
    return g, True, df