import pandas as pd
import requests

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

def load_ciks(headers):
    
    response = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers)
    response.raise_for_status()
    data = response.json()
    
    ciks = {}
    
    for company in data.values():
        ciks[company["ticker"]] = str(company["cik_str"]).zfill(10)
        
    return ciks

def edgar_rawdata(ticker, ciks, headers):
    
    if ticker.ticker not in ciks:
        return None
    
    response = requests.get("https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json".format(ciks[ticker.ticker]), headers = headers)
    
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