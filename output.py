import pandas as pd
import contextlib
import io
from helpers import mean, rolled_base
from rates import wacc
from growth import fcfe_highgrowth, revenue_growth, company_phi, target_roe
from formulas import two_stage, h_model
from models import run_ddm, run_fcfe, run_ri, run_fcff, ri_dataframe

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