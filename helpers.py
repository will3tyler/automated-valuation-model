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