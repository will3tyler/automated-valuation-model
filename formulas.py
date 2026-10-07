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