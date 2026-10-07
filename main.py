import yfinance as yf
import pandas as pd
import requests
import math
import contextlib
import io
import os
import warnings as pywarnings

#______________________________________________________________________________
#
# HELPERS
#______________________________________________________________________________

#------------------------------------------------------------------------------
# CAGR
#------------------------------------------------------------------------------

def CAGR(current,past,years):
    return ((current/past)**(1/years))-1

#------------------------------------------------------------------------------
# REGRESSION
#------------------------------------------------------------------------------

def slope(x, y):
    
    avg_x = sum(x)/len(x)
    avg_y = sum(y)/len(y)
    
    var_x = 0
    
    for i in range(len(x)):
        var = (x[i]-avg_x)**2
        var_x = var_x + var
    
    var_x = var_x/(len(x)-1)
    
    covar_total = 0
    
    for i in range(len(x)):
        covar = (x[i] - avg_x) * (y[i] - avg_y)
        covar_total = covar_total + covar
        
    covar_total = covar_total/(len(x)-1)
    
    return covar_total / var_x

#------------------------------------------------------------------------------
# NORMALIZE
#------------------------------------------------------------------------------

def normalize_series(series):
    
    clean = series.copy()
    threshold = 0.25
    
    for i in range(1, len(series) - 1):
        
        median = series.iloc[i-1:i+2].median()
        
        if abs(series.iloc[i] - median) > threshold * abs(median):
            clean.iloc[i] = median
            
    return clean

#------------------------------------------------------------------------------
# ARITHMETIC MEAN
#------------------------------------------------------------------------------

def mean(a, b):
    
    if a is None or b is None:
        return None
    
    return (a + b) / 2

#------------------------------------------------------------------------------
# FINANCIAL INDUSTRY FILTER
#------------------------------------------------------------------------------

def financialco_filter(ticker):
        
    return ticker.info.get("industry","").startswith(("Banks", "Insurance -", "Capital Markets", "Mortgage Finance"))

#------------------------------------------------------------------------------
# BASE ROLLER
#------------------------------------------------------------------------------

def rolled_base(flow, earnings, g):
    base = min(flow.mean(), earnings.mean())
    return base * (1 + g) ** ((len(flow) - 1) / 2)





#______________________________________________________________________________
#
# DATA
#______________________________________________________________________________

#------------------------------------------------------------------------------
# YFINANCE DIVIDEND DATA
#------------------------------------------------------------------------------

def common_dividends(ticker, net_income):
    
    if ticker.dividends.empty:
        return pd.Series(0, index = net_income.index)
    
    else:
        if "Common Stock Dividend Paid" in ticker.cashflow.index:
            common = abs(ticker.cashflow.loc["Common Stock Dividend Paid"])
        
        else:
            common = None
            
        if "Cash Dividends Paid" in ticker.cashflow.index and "Net Income" in ticker.income_stmt.index:
            preferred = ticker.income_stmt.loc["Net Income"] - net_income
            total = abs(ticker.cashflow.loc["Cash Dividends Paid"]) - preferred
            
        else:
            total = None
            
    if common is None and total is None:
        return None
    
    elif common is None:
        return total.fillna(0)
    
    elif total is None:
        return common.fillna(0)
    
    else:
        return common.combine_first(total).fillna(0)

#------------------------------------------------------------------------------
# DAMODARAN SPREADS TABLE
#------------------------------------------------------------------------------

def load_spreads():
    
    table = pd.read_html("https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html")[0]
    
    min_coverage = pd.to_numeric(table[0], errors = "coerce")
    spread = pd.to_numeric(table[3].str.rstrip("%"), errors = "coerce") / 100
    
    return pd.DataFrame({"min_coverage":min_coverage, "spread":spread}).dropna().sort_values("min_coverage", ascending = False)

def load_erp():
    
    table = pd.read_excel("https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx", sheet_name = "Historical ERP")
    
    return pd.to_numeric(table["ERP (T12m)"], errors = "coerce").dropna().iloc[-1]

#------------------------------------------------------------------------------
# SEC EDGAR
#------------------------------------------------------------------------------

def load_ciks():
    
    response = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    
    ciks = {}
    
    for company in data.values():
        ciks[company["ticker"]] = str(company["cik_str"]).zfill(10)
        
    return ciks

def edgar_rawdata(ticker, ciks):
    
    if ticker.ticker not in ciks:
        return None
    
    response = requests.get("https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json".format(ciks[ticker.ticker]), headers = HEADERS)
    
    if response.status_code != 200:
        return None
    
    data = response.json()
    
    return data

def edgar_seriesdata(data, tag):
    
    if "us-gaap" not in data["facts"] or tag not in data["facts"]["us-gaap"] or "USD" not in data["facts"]["us-gaap"][tag]["units"]:
        
        return None
    
    filings = pd.DataFrame(data["facts"]["us-gaap"][tag]["units"]["USD"])
    filings = filings[filings["form"] == "10-K"]

    if "start" in filings.columns:
        end_dates = pd.to_datetime(filings["end"])
        start_dates = pd.to_datetime(filings["start"])
        days = (end_dates - start_dates).dt.days
        filings = filings[(days > 350) & (days < 380)]
        
    filings = filings.sort_values("filed").drop_duplicates("end", keep="last")
    
    if filings.empty:
 
        return None
    
    return pd.Series(filings["val"].values, index = pd.to_datetime(filings["end"])).sort_index()

def edgar_netincome(data):
    
    common_ni = edgar_seriesdata(data,"NetIncomeLossAvailableToCommonStockholdersBasic")
    total_ni = edgar_seriesdata(data, "NetIncomeLoss")
    ni_fallback = edgar_seriesdata(data, "ProfitLoss")
    
    if common_ni is None and total_ni is None:
        return ni_fallback
    
    elif common_ni is None:
        return total_ni
        
    elif total_ni is None:
        return common_ni
        
    else:
        return common_ni.combine_first(total_ni)

def edgar_roe(data):
    
    if data is None:
        return None
    
    net_income = edgar_netincome(data)
    
    equity = edgar_seriesdata(data, "StockholdersEquity")
    
    if equity is None:
        equity = edgar_seriesdata(data, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
    
    preferred = edgar_seriesdata(data, "PreferredStockValue")

    if net_income is None or equity is None:
        return None
        
    if preferred is not None:
        equity = equity - preferred.reindex(equity.index).fillna(0)

    return (net_income / equity).dropna()





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





#______________________________________________________________________________
#
# VALUATION FORMULAS
#______________________________________________________________________________

#------------------------------------------------------------------------------
# TWO STAGE MODEL
#------------------------------------------------------------------------------

def two_stage(r,cash_flow,g,g_L,years_projected):
    
    total_pv = 0
    for i in range(1,years_projected + 1):
        cf_t = cash_flow * (1 + g) ** i
        total_pv = total_pv + cf_t/(1+r)**i
        
    CF_n = ((cash_flow * (1 + g) ** (years_projected)) * (1 + g_L))
    
    V_n = CF_n / (r - g_L)
    V_n = V_n / (1 + r) ** years_projected
    
    return total_pv + V_n

#------------------------------------------------------------------------------
# H MODEL
#------------------------------------------------------------------------------

def h_model(r,cash_flow,g,g_L,years_projected):
    
    H = years_projected / 2
    
    return (cash_flow * (1 + g_L) / (r - g_L)) + (cash_flow * H * (g - g_L) / (r - g_L))

#------------------------------------------------------------------------------
# RESIDUAL INCOME MODEL
#------------------------------------------------------------------------------

def residual_income(r, book_value, roe, retention, phi, years_projected, target):

    total_pv = 0
    bv = book_value
    
    for i in range(1,years_projected + 1):
        roe_t = target + (roe - target) * phi ** i
        ri = (roe_t - r) * bv
        fade = (roe_t - target) * bv
        total_pv = total_pv + (ri / (1+r)**i)
        bv = bv * max(0, (1 + roe_t * retention))
        
    if target > r:
        permanent_excess = (target - r) * (bv / r)
    
    else:
        permanent_excess = 0
    
    V_n = ((phi * fade) / (1 + r - phi) + permanent_excess) / (1 + r)**years_projected
    
    return total_pv + book_value + V_n





#______________________________________________________________________________
#
# MODEL RUNNERS
#______________________________________________________________________________

#------------------------------------------------------------------------------
# DDM
#------------------------------------------------------------------------------

def run_ddm(ticker, data, r, g_L, gdp_g, years_historical, years_projected):
    
    if ticker.dividends.empty:
        print("Company does not pay dividends; DDM model inappropriate.")
            
        return None, None, 0
        
    if "Net Income Common Stockholders" not in ticker.income_stmt.index:
        print("Common shareholder data missing; DDM model inappropriate.")
        
        return None, None, 0
    
    divs = ticker.dividends
    gaps = []
    
    if len(divs) < 2:
        print("Not enough dividend payments; DDM model inappropriate.")
        
        return None, None, 0
    
    for i in range(max(1, len(divs) - 8), len(divs)):
        gaps.append((divs.index[i] - divs.index[i-1]).days)
    
    freq = round(365/pd.Series(gaps).median())
    
    if freq < 1:
        print("Dividends too infrequent; DDM model inappropriate.")
        
        return None, None, 0
    
    if len(ticker.dividends) < freq + years_historical * freq:
        print("Company does not have enough dividend history; DDM model inappropriate.")
            
        return None, None, 0
        
        
    dividend = ticker.dividends.iloc[-freq:].median() * freq
    dividend_past = ticker.dividends.iloc[-freq-years_historical*freq:-years_historical*freq].median() * freq
    net_income = ticker.income_stmt.loc["Net Income Common Stockholders"]
    total_dividends_paid = common_dividends(ticker, net_income)
    
    if total_dividends_paid is None:
        print("Dividend data missing; DDM model inappropriate.")
        
        return None, None, 0
        
    payouts = pd.concat([net_income, total_dividends_paid], axis = 1, join = "inner", keys = ["net_income", "total_dividends_paid"]).dropna().sort_index()
    payout_ratio_sum = payouts["total_dividends_paid"].sum() / payouts["net_income"].sum()
    
    payouts["payout_ratio"] = payouts["total_dividends_paid"] / payouts["net_income"]
    
    if payouts.empty or payouts["net_income"].iloc[-1] <=0 or payout_ratio_sum < 0.2:
        print("Payout ratio too low; DDM model inappropriate.")
        
        return None, None, 0

    g = (CAGR(dividend,dividend_past,years_historical) * 0.5) + (gdp_g * 0.5)
    
    if g_L >= r:
        print("Terminal growth exceeds cost of equity; DDM model inappropriate.")
                
        return None, None, 0
    
         
    run_two_stage = two_stage(r, dividend, g, g_L, years_projected)
    run_h_model = h_model(r, dividend, g, g_L, years_projected)
    
    if run_two_stage <= 0 or run_h_model <= 0:
        print("Intrinsic Value negative; DDM model inappropriate.")
        
        return None, None, 0
    
    score = 0
    
    if 0.5 <= payout_ratio_sum < 1:
        score = score + 1

    if payouts["payout_ratio"].max() - payouts["payout_ratio"].min() < 0.20:
        score = score + 1
        
    n = len(ticker.dividends)
    regular = []
    special = False

    for i in range(years_historical + 1):
        year = ticker.dividends.iloc[n - freq*(i+1) : n - freq*i]
        typical = year.median()
        regular.append(typical)

        if year.max() > typical * 1.5:
            special = True

    cut = False
    for i in range(len(regular) - 1):
        if regular[i] < regular[i+1] * 0.95:
            cut = True

    if not cut and not special:
        score = score + 1
        
    if "Common Stock Equity" in ticker.balance_sheet.index:
        equity = ticker.balance_sheet.loc["Common Stock Equity"]
        growth = pd.concat([net_income, equity], axis = 1, join = "inner", keys = ["net_income", "equity"]).dropna().sort_index()
        
        if not growth.empty and (growth["equity"] > 0).all():
            roe = growth["net_income"].sum() / growth["equity"].sum()
            
            if g <= roe * (1 - payout_ratio_sum):
                score = score + 1
    
    fcfe_g, _, df = fcfe_highgrowth(ticker, data, g_L, gdp_g)
    shares = ticker.info.get("sharesOutstanding")
    
    if df is not None and shares and df["fcfe"].mean() > 0:
        FCFEo_pershare = rolled_base(df["fcfe"], df["net_income"], fcfe_g) / shares
        
        if 0.7 <= (divs[divs.index > pd.Timestamp.now(tz = divs.index.tz) - pd.Timedelta(days = 365)]).sum() / FCFEo_pershare <= 1.3:
            score = score + 1
    
    if payout_ratio_sum < 0.5:
        score = 0
        
    return run_two_stage, run_h_model, score

#------------------------------------------------------------------------------
# FCFE
#------------------------------------------------------------------------------

def run_fcfe(ticker, data, r, g_L, gdp_g, years_projected):
    
    g, reliable, df = fcfe_highgrowth(ticker, data, g_L, gdp_g)
    
    if g is None:
        print("Data behind high-growth assumption insufficient; FCFE model inappropriate.")
        
        return None, None, 0
    
    if len(df) < 3:
        print("Not enough years of financial data; FCFE model inappropriate.")
        
        return None, None, 0
    
    if df["fcfe"].mean() <= 0:
        print("Average FCFE is not positive; FCFE model inappropriate.")
        
        return None, None, 0
    
    shares = ticker.info.get("sharesOutstanding")
    
    if not shares:
        print("Insufficient shares outstanding data; FCFE model inappropriate.")
        
        return None, None, 0
    
    if g_L >= r:
        print("Terminal growth exceeds the cost of equity; FCFE model inappropriate.")
        
        return None, None, 0
    
    FCFEo_pershare = rolled_base(df["fcfe"], df["net_income"], g) / shares
    
    run_two_stage = two_stage(r, FCFEo_pershare, g, g_L, years_projected)
    run_h_model = h_model(r, FCFEo_pershare, g, g_L, years_projected)
    
    if run_two_stage <= 0 or run_h_model <= 0:
        print("Intrinsic Value negative; FCFE model inappropriate.")
        
        return None, None, 0
    
    score = 0
    
    if (df["fcfe"] > 0).all():
        score = score + 1
        
    if 0.5 <= df["fcfe"].sum() / df["net_income"].sum() <= 1.5:
        score = score + 1
        
    if (df["equity"] > 0).all() and df["debt_ratio"].dropna().max() - df["debt_ratio"].dropna().min() <= 0.10:
        score = score + 1
        
    divs = ticker.dividends
    
    if divs.empty or (divs[divs.index > pd.Timestamp.now(tz = divs.index.tz) - pd.Timedelta(days = 365)]).sum() / FCFEo_pershare < 0.7:
        score = score + 1
        
    if "Total Revenue" in ticker.income_stmt.index:
        m = pd.concat([df["fcfe"], ticker.income_stmt.loc["Total Revenue"]], axis = 1, join = "inner", keys = ["fcfe", "revenue"]).dropna()
        margin = m["fcfe"] / m["revenue"]

        if not m.empty and margin.median() > 0 and (margin.max() - margin.min()) / margin.median() < 0.4:
            score = score + 1
        
    if reliable is False:
        score = 0
        
    return run_two_stage, run_h_model, score

#------------------------------------------------------------------------------
# RESIDUAL INCOME
#------------------------------------------------------------------------------

def ri_dataframe(ticker):
    if "Net Income Common Stockholders" not in ticker.income_stmt.index or "Common Stock Equity" not in ticker.balance_sheet.index:    
        return None
    
    net_income = ticker.income_stmt.loc["Net Income Common Stockholders"]
    equity = ticker.balance_sheet.loc["Common Stock Equity"]
    dividends = common_dividends(ticker, net_income)
    
    if dividends is None:
        return None
        
    if "Net Common Stock Issuance" in ticker.cashflow.index:
        buybacks = -ticker.cashflow.loc["Net Common Stock Issuance"].fillna(0)
        
    else:
        
        if "Repurchase Of Capital Stock" in ticker.cashflow.index:
            repurchase = abs(ticker.cashflow.loc["Repurchase Of Capital Stock"]).fillna(0)
            
        else:
            repurchase = pd.Series(0, index = net_income.index)
                
        if "Issuance Of Capital Stock" in ticker.cashflow.index:
            issuance = ticker.cashflow.loc["Issuance Of Capital Stock"].fillna(0)
            
        else:
            issuance = pd.Series(0, index = net_income.index)
            
        buybacks = repurchase - issuance
        
    if "Stock Based Compensation" in ticker.cashflow.index:
        sbc = ticker.cashflow.loc["Stock Based Compensation"].fillna(0)
        
    else:
        sbc = pd.Series(0, index = net_income.index)
        
    if "Goodwill And Other Intangible Assets" in ticker.balance_sheet.index:
        intangibles = ticker.balance_sheet.loc["Goodwill And Other Intangible Assets"].fillna(0)
        
    else:
        intangibles = pd.Series(0, index = net_income.index)
    
    return pd.concat([net_income, equity, dividends, buybacks, sbc, intangibles], axis = 1, join = "inner", keys = ["net_income", "equity", "dividends", "buybacks", "sbc", "intangibles"]).dropna().sort_index()

def implied_roe(ticker, data, r, years_projected, price):
    
    if not financialco_filter(ticker):
        return None
    
    df = ri_dataframe(ticker)
    
    if df is None or len(df) < 3 or (df["equity"] <= 0).any() or df["net_income"].sum() <= 0:
        return None
    
    shares = ticker.info.get("sharesOutstanding")
    
    if not shares:
        return None
    
    book_value = df["equity"].iloc[-1] / shares
    retention = min(1, 1 - (df["dividends"].sum() + df["buybacks"].sum()) / df["net_income"].sum())
    phi = blended_phi(data)
    
    low = 0.0
    high = 0.6
    
    for i in range(100):
        mid = (low + high) / 2
        value = residual_income(r, book_value, mid, retention, phi, years_projected, mid)
        
        if value < price:
            low = mid
            
        else:
            high = mid
            
    return mid

def run_ri(ticker, data, r, years_projected, target_shift = 0):
    
    df = ri_dataframe(ticker)
    
    if df is None:
        print ("Common shareholder or dividend data missing; RI model inappropriate.")
        
        return None, 0

    if len(df) < 3 or (df["equity"] <= 0).any():
        print("Common Shareholder data insufficient; RI model inappropriate.")
        
        return None, 0
    
    if df["net_income"].sum() <= 0:
        print("Total net income negative; RI model inappropriate.")
        
        return None, 0
    
    shares = ticker.info.get("sharesOutstanding")
    
    if not shares:
        print("Insufficient shares outstanding data; RI model inappropriate.")
        
        return None, 0
    
    book_value = df["equity"].iloc[-1] / shares
    roe = df["net_income"].sum() / df["equity"].sum()
    retention = min(1, 1 - (df["dividends"].sum() + df["buybacks"].sum()) / df["net_income"].sum())
    phi = blended_phi(data)
    roe_target = target_roe(data, r, roe) + target_shift
    
    run_residual_income = residual_income(r, book_value, roe, retention, phi, years_projected, roe_target)
    
    if run_residual_income <= 0:
        print("Intrinsic Value negative; RI model inappropriate.")
        
        return None, 0
    
    score = 0
    
    actual = df["equity"].iloc[-1] - df["equity"].iloc[0]
    expected = df["net_income"].iloc[1:].sum() - df["dividends"].iloc[1:].sum() - df["buybacks"].iloc[1:].sum() + df["sbc"].iloc[1:].sum()
    yearly_roe = df["net_income"] / df["equity"]
    bv_is_fair = df["intangibles"].sum() / df["equity"].sum() < 0.5 and roe < 0.25
    phi, pairs = company_phi(data)

    if abs(actual - expected) <= 0.20 * abs(expected):
        score = score + 1
        
    if bv_is_fair:
        score = score + 1
    
    if financialco_filter(ticker):
        score = score + 1
        
    if yearly_roe.max() - yearly_roe.min() < 0.05:
        score = score + 1
    
    if pairs >= 10 and 0 < phi < 1:
        score = score + 1
        
    if not bv_is_fair:
        score = 0
    
    return run_residual_income, score

#------------------------------------------------------------------------------
# FCFF
#------------------------------------------------------------------------------

def run_fcff(ticker, data, r, rf, spreads, g_L, gdp_g, years_projected):
    
    g, reliable, df = fcff_highgrowth(ticker, data, g_L, gdp_g)
    
    if g is None:
        print("Data behind high-growth assumption insufficient; FCFF model inappropriate.")
        
        return None, None, 0
    
    if len(df) < 3:
        print("Not enough years of financial data; FCFF model inappropriate.")
        
        return None, None, 0
    
    if df["fcff"].mean() <= 0:
        print("Average FCFF is not positive; FCFF model inappropriate.")
        
        return None, None, 0
    
    shares = ticker.info.get("sharesOutstanding")
    
    if not shares:
        print("Insufficient shares outstanding data; FCFF model inappropriate.")
        
        return None, None, 0
    
    w = wacc(ticker, r, rf, spreads)
    
    if w is None:
        print("Cost of capital unavailable; FCFF model inappropriate.")
        
        return None, None, 0
    
    if g_L >= w:
        print("Terminal growth exceeds the cost of capital; FCFF model inappropriate.")
        
        return None, None, 0
    
    FCFFo = rolled_base(df["fcff"], df["nopat"], g)
    
    run_two_stage = two_stage(w, FCFFo, g, g_L, years_projected)
    run_h_model = h_model(w, FCFFo, g, g_L, years_projected)
    
    if "Total Debt" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Total Debt"].dropna().empty:
        debt_latest = 0
        
    else: 
        debt_latest = ticker.balance_sheet.loc["Total Debt"].dropna().iloc[0]
        
    if "Preferred Stock" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Preferred Stock"].dropna().empty:
        preferred_latest = 0
        
    else: 
        preferred_latest = ticker.balance_sheet.loc["Preferred Stock"].dropna().iloc[0]
        
    if "Cash Cash Equivalents And Short Term Investments" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Cash Cash Equivalents And Short Term Investments"].dropna().empty:
        cash_latest = 0
        
    else: 
        cash_latest = ticker.balance_sheet.loc["Cash Cash Equivalents And Short Term Investments"].dropna().iloc[0]
        
    run_two_stage = (run_two_stage + cash_latest - debt_latest - preferred_latest) / shares
    run_h_model = (run_h_model + cash_latest - debt_latest - preferred_latest) / shares
    
    if run_two_stage <= 0 or run_h_model <= 0:
        print("Intrinsic Value negative; FCFF model inappropriate.")
        
        return None, None, 0
    
    score = 0
    
    if "Common Stock Equity" not in ticker.balance_sheet.index or ticker.balance_sheet.loc["Common Stock Equity"].dropna().empty:
        negative_equity = False
        
    else: 
        negative_equity = ticker.balance_sheet.loc["Common Stock Equity"].dropna().iloc[0] <= 0
        
    E = ticker.info.get("marketCap")
    
    if debt_latest / (debt_latest + E) >= 0.3 or negative_equity:
        score = score + 1
        
    _, _, df_fcfe = fcfe_highgrowth(ticker, data, g_L, gdp_g)
    
    if df_fcfe is not None and df_fcfe["debt_ratio"].dropna().max() - df_fcfe["debt_ratio"].dropna().min() > 0.10:
        score = score + 1
    
    if df_fcfe is not None:
        sd = pd.concat([df["fcff"], df_fcfe["fcfe"]], axis = 1, join = "inner", keys = ["fcff", "fcfe"]).dropna()
        
        if ((sd["fcfe"] <= 0) & (sd["fcff"] > 0)).any():
            score = score + 1
            
    roic = df["nopat"] / df["invested_capital"]
    
    if roic.max() - roic.min() < 0.05:
        score = score + 1
   
    interest_coverage = df["ebit"] / abs(df["interest_expense"])
    positions = []
    
    for coverage in interest_coverage:
        
        for i, min_coverage in enumerate(spreads["min_coverage"]):
            if coverage >= min_coverage:
                
                positions.append(i)
                break
    
    if positions and debt_latest / (debt_latest + E) >= 0.15 and max(positions) - min(positions) <= 1:
        score = score + 1

    if reliable is False:
        score = 0
        
    return run_two_stage, run_h_model, score





#______________________________________________________________________________
#
# OUTPUT
#______________________________________________________________________________

#------------------------------------------------------------------------------
# MASTER INTRINSIC VALUE
#------------------------------------------------------------------------------

def master_value(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected, target_shift = 0):
    
    ddm_twostage, ddm_hmodel, ddm_score = run_ddm(ticker, data, r, g_L, gdp_g, years_historical, years_projected)
    fcfe_twostage, fcfe_hmodel, fcfe_score = run_fcfe(ticker, data, r, g_L, gdp_g, years_projected)
    ri_value, ri_score = run_ri(ticker, data, r, years_projected, target_shift)
    fcff_twostage, fcff_hmodel, fcff_score = run_fcff(ticker, data, r, rf, spreads, g_L, gdp_g, years_projected)
    
    ddm = mean(ddm_twostage, ddm_hmodel), ddm_score
    fcfe = mean(fcfe_twostage, fcfe_hmodel), fcfe_score
    ri = ri_value, ri_score
    fcff = mean(fcff_twostage, fcff_hmodel), fcff_score
    
    pairs = ddm, fcfe, ri, fcff
    
    df = pd.DataFrame(list(pairs), index = ["ddm", "fcfe", "ri", "fcff"], columns = ["value", "reliability"])
    
    warnings = reliability_warnings(ticker, data, r, rf, spreads, g_L, gdp_g, df)
    
    if df["reliability"].sum() == 0:
        return None, df, warnings
    
    df["weight"] = (df["reliability"] / df["reliability"].sum()) * 100
    
    return ((df["reliability"] / df["reliability"].sum()) * df["value"]).sum(), df, warnings

#------------------------------------------------------------------------------
# RECOMMENDATION
#------------------------------------------------------------------------------

def recommendation(s_table, price):
    
    table_values = s_table.iloc[1:4, 1:4]
    
    if table_values.isna().any().any():
        valued = "Model fails within the 3x3 sensitivity range."
        verdict = "VERDICT: Model cannot distinguish price from fair value."
    
    if table_values.min().min() > price:
        valued = "Every value in the 3x3 sensitivity range is above the market price."
        verdict = "VERDICT: Price is below the model's range (UNDERVALUED)"
        
    elif table_values.max().max() < price:
        valued = "Every value in the 3x3 sensitivity range is below the market price."
        verdict = "VERDICT: Price is above the model's range (OVERVALUED)"
        
    else:
        valued = "Values in the 3x3 sensitivity range straddle the market price."
        verdict = "VERDICT: Model cannot distinguish price from fair value."
    
    return valued, verdict

#------------------------------------------------------------------------------
# RELIABILITY WARNINGS
#------------------------------------------------------------------------------

def reliability_warnings(ticker, data, r, rf, spreads, g_L, gdp_g, df):
    
    warnings = []
    
    rev_g = revenue_growth(ticker, data)
    
    if (df.loc["fcfe", "reliability"] > 0 or df.loc["fcff", "reliability"] > 0) and rev_g is not None and rev_g > 0.25:
        warnings.append(f"Revenue growth of {rev_g:.1%} is outside the measured range; growth input unreliable.")
        
    if (df.loc["ddm", "reliability"] > 0 or df.loc["fcfe", "reliability"] > 0) and r - g_L < 0.02:
        warnings.append("Cost of equity exceeds terminal growth by less than 2 points; value is too sensitive to the spread.")
        
    if df.loc["fcff", "reliability"] > 0:
        
        w = wacc(ticker, r, rf, spreads)
        
        if w is not None and w - g_L < 0.02:
            warnings.append("Cost of capital exceeds terminal growth by less than 2 points; FCFF value is too sensitive to the spread.")
        
    used_models = df[df["reliability"] > 0]
    
    if df["reliability"].max() <= 1:
        warnings.append("No model with strong reliability; master value composed of poor fits.")
        
    if used_models["value"].max() / used_models["value"].min() > 2:
        warnings.append("Models disagree by more than 2x; master value averages conflicting estimates.")
        
    _, _, df_fcfe = fcfe_highgrowth(ticker, data, g_L, gdp_g)
        
    if df_fcfe is not None:
        
        cf_to_ni = df_fcfe["fcfe"].sum() / df_fcfe["net_income"].sum()
        
        if df.loc["fcfe", "reliability"] > 0 and (cf_to_ni < 0.5 or cf_to_ni > 1.5):
            warnings.append(f"Cash flow is {cf_to_ni:.2f}x earnings; FCFE base unsustainable.")
            
        if (df_fcfe["equity"] < 0).any():
            warnings.append("Negative equity in the window; ROE-based inputs are unreliable.")
            
    if df.loc["ri", "reliability"] > 0 or g_L < min(gdp_g, rf):
                
        phi, _ = company_phi(data)
        
        if phi is not None and phi in (0, 1):
            warnings.append("ROE persistence is bounded; ROE fade is unreliable.")
            
        df_ri = ri_dataframe(ticker)
        
        if df_ri is not None and len(df_ri) >= 3 and (df_ri["equity"] > 0).all() and df_ri["net_income"].sum() > 0:
            
            roe_now = df_ri["net_income"].sum() / df_ri["equity"].sum()
            target = target_roe(data, r, roe_now)
            
            if roe_now > 1.5 * target:
                warnings.append(f"Recent ROE of {roe_now:.1%} is well above long-run target of {target:.1%}; value too sensitive to ROE persistence.")
        
    if "Net Income Common Stockholders" in ticker.income_stmt.index and "Total Revenue" in ticker.income_stmt.index:
        
        net_income = ticker.income_stmt.loc["Net Income Common Stockholders"]
        revenue = ticker.income_stmt.loc["Total Revenue"]
        
        earnings = pd.concat([net_income, revenue], axis = 1, join = "inner", keys = ["net_income", "revenue"]).dropna()
        
        if not earnings.empty and ((earnings["net_income"] <= 0).any() or earnings["net_income"].sum() / earnings["revenue"].sum() <= 0.02):
            warnings.append("Earnings near or below zero; derived ratios unstable.")
            
        latest_ni = (pd.Timestamp.now() - net_income.dropna().index.max()).days
        
        if latest_ni > 455:
            warnings.append(f"Latest statements are {latest_ni} days old; inputs are unreliable.")
        
    return warnings

#------------------------------------------------------------------------------
# IMPLIED GROWTH
#------------------------------------------------------------------------------

def implied_growth(ticker, data, r, g_L, gdp_g, years_projected, price):
    
    _, _, df = fcfe_highgrowth(ticker, data, g_L, gdp_g)
    
    if df is None:     
        return None
    
    if len(df) < 3: 
        return None
    
    if df["fcfe"].mean() <= 0:
        return None
    
    shares = ticker.info.get("sharesOutstanding")
    
    if not shares:
        return None
    
    if g_L >= r:
        return None
    
    low = -0.5
    high = 1.0
    
    for i in range(100):
        mid = (low + high) / 2
        base = rolled_base(df["fcfe"], df["net_income"], mid) / shares
        value = mean(two_stage(r, base, mid, g_L, years_projected), h_model(r, base, mid, g_L, years_projected))
        
        if value < price:
            low = mid
            
        else:
            high = mid
            
    return mid

#------------------------------------------------------------------------------
# SENSITIVITY TABLE
#------------------------------------------------------------------------------

def sensitivity(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected):
    
    with contextlib.redirect_stdout(io.StringIO()):
        _, models, _ = master_value(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected)

    ri_only = models.loc["ri", "reliability"] > 0 and models.loc[["ddm", "fcfe", "fcff"], "reliability"].sum() == 0

    if ri_only:
        col_values = [-0.02, -0.01, 0, 0.01, 0.02]
        col_name = "ROE Target"

    else:
        col_values = [-0.01, -0.005, 0, 0.005, 0.01]
        col_name = "Terminal Growth"

    r_values = [-0.02, -0.01, 0, 0.01, 0.02]

    r_labels = []
    col_labels = []

    for i in r_values:
        r_labels.append(f"{i * 100:+g}%")

    for i in col_values:
        col_labels.append(f"{i * 100:+g}%")

    rows = []

    for i in r_values:
        row = []

        for j in col_values:
            with contextlib.redirect_stdout(io.StringIO()):
                if ri_only:
                    value, _, _ = master_value(ticker, data, r + i, rf, spreads, g_L, gdp_g, years_historical, years_projected, target_shift = j)

                else:
                    value, _, _ = master_value(ticker, data, r + i, rf, spreads, g_L + j, gdp_g, years_historical, years_projected)

                row.append(value)

        rows.append(row)

    df = pd.DataFrame(rows, index = r_labels, columns = col_labels).astype(float)
    df.index.name = "Cost of Equity"
    df.columns.name = col_name
    
    return df





#______________________________________________________________________________
#
# MAIN CODE
#______________________________________________________________________________

#------------------------------------------------------------------------------
# INPUTS
#------------------------------------------------------------------------------

pywarnings.filterwarnings("ignore", category = UserWarning, module = "openpyxl")
print("The SEC requires a contact for EDGAR requests (name and email). It is sent only to sec.gov as the User-Agent header.")
first_last = input("First & Last Name: ")
email = input("Email: ")

HEADERS = {"User-Agent": f"{first_last} {email}"}
market = yf.Ticker("^GSPC")
tnx = yf.Ticker("^TNX")
rf = tnx.history(period="5d")["Close"].iloc[-1]/100
years_historical = 5
years_projected = 10
gdp_years = 30
gdp = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP")
gdp_now = gdp["GDP"].iloc[-1]
gdp_past = gdp["GDP"].iloc[-1-gdp_years*4]
gdp_g = CAGR(gdp_now,gdp_past,gdp_years)
ciks = load_ciks()
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
        
        data = edgar_rawdata(ticker, ciks)
        g_L = terminal_growth(ticker, data, r, rf, gdp_g, years_projected)
        price = ticker.history(period = "5d")["Close"].iloc[-1]
        name = ticker.info.get("longName", symbol)
    
        break
    
    if symbol == "":
        
        break
    
#------------------------------------------------------------------------------
# RESULTS
#------------------------------------------------------------------------------
    
    master, models, warnings = master_value(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected)
    
    print(" _________________________________________________________")
    print("| VALUATIONS: ", name)
    print("|")
    
    if master is None:
        print("| No valuation model can accurately estimate intrinsic value.")
    
    else:
        table = round(models, 2)
        table["weight"] = table["weight"].astype(str) + "%"
        table["value"] = table["value"].fillna("-")
        
        for i in table.to_string().split("\n"):
            print("|                        ", i)
        print("|")
        print("|                                      5 = Highly reliable")
        print("|                               0 = Not reliable, Unusable")
        print("|_________________________________________________________")
        print("| INITIAL MODEL RESULT")
        print("|                             Current Market Value: ", round(price, 2))
        print("|                           Master Intrinsic Value: ", round(master, 2))
        print("|_________________________________________________________")
        print("| WHAT THE PRICE ASSUMES")
        print("|")
        
        g_needed = implied_growth(ticker, data, r, g_L, gdp_g, years_projected, price)
        roe_needed = implied_roe(ticker, data, r, years_projected, price)
        
        if g_needed is not None:
            g_used, _, _ = fcfe_highgrowth(ticker, data, g_L, gdp_g)
            share = (base_rates >= g_needed).sum() / len(base_rates)
            print(f"| Market price implies FCFE growth of {g_needed:.1%}. Model uses {g_used:.1%}.")
            print(f"| Of {len(base_rates)} large companies 2010 - 2016, {share:.0%} grew that fast.")
            
        if roe_needed is not None:
            df_ri = ri_dataframe(ticker)
            
            roe_shorthistory = df_ri["net_income"].sum() / df_ri["equity"].sum()
            roe_longhistory = edgar_roe(data)
            
            print(f"| Market price implies a permanent ROE of {roe_needed:.1%}.")
            
            if roe_longhistory is not None:
                print(f"| ROE last {len(df_ri)} years is {roe_shorthistory:.1%}; median ROE over {len(roe_longhistory)} years is {roe_longhistory.median():.1%}.")
                
            else:
                print(f"| ROE last {len(df_ri)} years is {roe_shorthistory:.1%}.")
    
        if g_needed is None and roe_needed is None:
            print("| No reverse calculation available.")
    
        
        print("|_________________________________________________________")
        print("| SENSITIVITY ANALYSIS")
        print("|")
        
        s_table = round(sensitivity(ticker, data, r, rf, spreads, g_L, gdp_g, years_historical, years_projected), 2)
        for i in s_table.to_string().split("\n"):
            print ("|", i)
        print("|_________________________________________________________")
        print("| FINAL VERDICT")
        print("|")
        valued, verdict = recommendation(s_table, price)
        print("| ", valued)
        print("| ", verdict)
        if warnings:
            print("|")
            print("|                       VERDICT IS UNRELIABLE. REASON(S):")
            for i in warnings:
                print ("| ", i)
        
