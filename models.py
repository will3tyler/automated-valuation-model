import pandas as pd
from helpers import CAGR, financialco_filter, rolled_base
from data import common_dividends
from rates import wacc
from growth import fcfe_highgrowth, fcff_highgrowth, company_phi, blended_phi, target_roe
from formulas import two_stage, h_model, residual_income

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
    
    g, _, df = fcfe_highgrowth(ticker, data, g_L, gdp_g)
    
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