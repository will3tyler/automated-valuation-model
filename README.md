# Automated Stock Valuation Model

This program is designed to allow the user to input a stock ticker, and it will build a valuation from that ticker, followed by a sensitivity analysis and verdict.

## Overview & Motivation

I made this program because I wanted to learn how to properly code in Python, not to solve any existing problem related to valuations. If you seriously want to value a company, do not use this program. Intrinsic valuation is highly company-specific and it is next to impossible to create a generalized method. Alas, it is still fun to see how the program functions and the different outputs it will generate (many outputs will say the verdict is unreliable for x reason(s)).

## Installation

Requires Python 3.10+ and an internet connection.

```bash
git clone https://github.com/will3tyler/automated-valuation-model.git
cd automated-valuation-model
pip install -r requirements.txt
python main.py
```

`base_rates.csv` must stay in the same folder as the script; it's read at launch for the implied-growth comparison.

On launch the program fetches live inputs from Yahoo Finance, SEC EDGAR, FRED and Damodaran's NYU Stern data pages. EDGAR requires a name and email in the request header, so you are prompted for both before entering a ticker. They are sent only to sec.gov.

## How the Program Runs

1) Enter your first, last and email; the SEC requires a name and contact for any EDGAR requests.

2) Enter the ticker of whatever stock you want to evaluate. Blank input quits the loop. The program does not allow valuation of anything other than equity stocks, and within that, no REITs, companies with mismatched exchange currency and financial statement currency, stocks with insufficient price history, or stocks that are broken in yfinance.

3) The program will then run four methods of valuation that score themselves, build a weighted master value, and output what the price assumes, a sensitivity table, a verdict and any reasons it may be unreliable.

## Shared Inputs and Assumptions

All four models use the same cost of equity, terminal growth rate, and projection horizon (10 years).

### Required Returns

Cost of Equity from CAPM: 10-year Treasury Yield (Risk-free rate) + Beta * Equity Premium. Beta: Regression of five years of monthly returns from company and S&P500, Blume-adjusted and then pulled halfway toward 1. Equity Premium: From Dr. Damodaran's implied equity premium. Discounts every model.

Weighted-Average Cost of Capital: Blends cost of equity with after-tax cost of debt from a synthetic credit rating, and cost of preferred stock.

### Profitability Settlement

The program uses mean reversion to determine future profitability. A company that earns above its cost of equity will not do so forever as more competition arrives. In theory, it should fall towards the cost of equity, but backtesting across 255 firms shows it will not (highest ROE firms went from 34% to 33%). So, mean reversion is determined from current ROE and target ROE.

Current ROE: Sum of net income / Sum of common equity over the last four reported years. Summing dilutes off-years.

Target ROE: The median of the company's own ROE history from EDGAR (up to 18 years, normalized), blended toward the cost of equity. Extent of the blend depends on how long the history is. Clamped between the cost of equity and current ROE.

Fade Rate (Phi): How much of the gap between current and target ROE remains each year. This was calculated by regressing each year's ROE on the previous year's across the company's history. The less change, the higher the fade rate. This is then blended toward 0.62, which is Dechow, Hutton and Sloan (1999)'s estimate of earnings persistence. Extent of the blend depends on how long the history is.

Terminal ROE: Target ROE plus the difference between current and target ROE, multiplied by the fade rate to the power of 10 (years projected).

### Terminal Growth

Calculated by multiplying the terminal ROE with the retention ratio. Retention is 1 - (sum of dividends / sum of net income).

Cap: Terminal growth cannot exceed the lower of long-run GDP growth and the Treasury yield. No company can outgrow the country's GDP in perpetuity. The Treasury yield cap is from backtesting where, without it, interest rates determined the model's verdicts. This cap is also the fallback terminal growth in the case that growth inputs are missing or unreliable.

Residual income does not use terminal growth. It starts from book value per share and adds the profit earned above the cost of equity each year, discounted back. ROE follows the fade described, and the book grows by what is retained. After the growth period, any excess that isn't faded is added as a terminal value.

### Near-Term Growth

Measured over ten years, companies kept about half their past growth rate; the other half reverted toward the economy's. So:

FCFE and FCFF growth: GDP growth + half of revenue growth. Revenue growth is determined as a log-linear trend over up to ten years of SEC filings, with yfinance CAGR used as a fallback. In backtests, revenue predicted future earnings growth better than past earnings growth, ROE * reinvestment, or dividend growth did.

DDM growth: Half of five-year dividend growth + half of GDP growth.

### Starting Cash Flow

FCFE & FCFF: Average of the last four reported years. This represents the level about 1.5 years ago, so it is rolled forward by (1 + near-term growth) ^ 1.5. This is capped at average earnings (net income for FCFE, after-tax operating profit for FCFF) since cash above profit does not last.

DDM: Starts from the trailing year's dividend.

RI: Starts from the latest book value.

## The Four Models

DDM, FCFE, and FCFF all calculate two models, and average the two for a final intrinsic value. Those two models are:

Two-Stage Model: Cash flow grows at the near-term rate for ten years, then at the terminal growth rate forever, and every year is discounted back to today.

H-Model: Cash flow grows at the near-term rate that declines in a straight line to the terminal growth rate over the ten years, then at the terminal growth rate forever, and every year is discounted back to today.

### DIVIDEND DISCOUNT MODEL

Assumes the stock is worth the dividends it will pay, discounted at the cost of equity. This fits companies that pay out most of what they earn and have done so steadily.

DDM is REJECTED when:

- Company never paid a dividend
- Common net income row is missing
- Fewer than two payments recorded
- Payments occur in spans longer than a year
- Not enough dividend history for the growth calculation
- No usable dividend row in the cash flow statement
- Latest net income is negative, or four-year payout is under 20% of earnings
- Terminal growth reaches the cost of equity
- The value comes out negative

DDM Scoring Criteria:

- Dividends are the main use of earnings
- The dividend does not swing and tracks earnings
- There are no dividend cuts or special dividends in the measured window
- The company's earnings can fund the assumed dividend growth
- Dividends are close to free cash flow; so the model captures what the company actually generates

### FREE CASH FLOW TO EQUITY MODEL

Assumes the stock is worth the cash left for shareholders after operations, investments and net borrowing, whether or not it is paid out, discounted at the cost of equity. This fits companies that keep cash or have large buybacks and have a steady capital structure.

FCFE is REJECTED when:

- The company is a bank, insurer, broker or lender
- Any of the cash flow, capex, net income or equity rows are missing
- Fewer than three years of data
- Net income summed is zero or negative
- Average FCFE is zero or negative
- Shares outstanding are missing
- Terminal growth reaches the cost of equity
- The value comes out negative

FCFE Scoring Criteria:

- Cash flow is positive every year so there is always cash to value
- Cash flow is backed by earnings rather than timing circumstances
- The capital structure is stable; total debt as a share of total capital isn't volatile
- Cash is kept or allocated to buybacks that a DDM would miss
- FCFE moves with revenue to allow revenue growth as a proxy for FCFE growth

### RESIDUAL INCOME MODEL

Assumes the stock is worth its book value plus the present value of profit earned above the cost of equity, with that excess fading toward the company's own long-run level. This fits banks where book value is meaningful and dividends and free cash flow aren't.

RI is REJECTED when:

- Net income or equity rows are missing
- No usable dividend row
- Fewer than three years of data
- Equity is negative in any year
- Net income summed is zero or negative
- Shares outstanding is missing
- The value comes out negative

RI Scoring Criteria:

- Company's book grows by retained profit
- The book is a reasonable size; not too large (measured through intangibles) and not too small (measured through ROE)
- The company being valued is a financial company
- Excess returns are measurable
- The ROE fade rate is reliable

### FREE CASH FLOW TO THE FIRM MODEL

Assumes the stock is worth the cash available to all capital providers, discounted at the weighted average cost of capital, with debt and preferred stock removed and cash added afterwards to reach equity. This fits companies with large amounts of debt or an unstable capital structure.

FCFF is REJECTED when:

- The company is a bank, insurer, broker or lender
- Any of the cash flow, capex, EBIT or invested capital rows are missing
- Fewer than three years of data
- After-tax operating profit summed is zero or negative
- Shares outstanding is missing
- Market capitalization is missing
- Terminal growth reaches WACC
- The value comes out negative after subtracting debt

FCFF Scoring Criteria:

- The company is highly levered, enough to require a firm-level valuation
- Capital structure is shifting; total debt as a share of total capital is volatile
- FCFE is negative and FCFF is positive in at least one year; borrowing distorts equity cash flow
- Operating return is measurable (stable ROIC)
- Cost of debt is stable and can be held fixed (only when debt is at least 15% of capital)

## Reading the Output

### VALUATIONS

Provides a table with each model, its calculated intrinsic value, reliability, and weight. Reliability is the sum of the scored criteria. A dash means the model rejected the company.

### INITIAL MODEL RESULT

Provides the weighted master intrinsic value as well as the current market price.

### WHAT THE PRICE ASSUMES

Shows the ten-year FCFE growth the current market price requires, the growth the model used, and the share of 1,154 large companies that grew that fast.

For banks, this shows the permanent ROE the current market price requires as well as the four-year ROE and long-run median ROE.

### SENSITIVITY ANALYSIS

Provides a table that determines the master intrinsic value across negative and positive changes in cost of equity and terminal growth. For banks, the terminal growth axis is replaced with ROE target as RI model doesn't use terminal growth. The verdict uses the central 3x3 grid in this table.

### FINAL VERDICT

States whether the current market price is above, below, or within the model's range, as well as reasons the model may be unreliable. Those reasons may include:

- Revenue hypergrowth
- Thin spread between discount rate and terminal growth
- No model scoring above 1
- Models disagreeing by more than 2x
- Cash flow out of line with earnings
- Negative equity
- Fade rate is at a bound
- Recent ROE far above its long-run level
- Earnings are zero or negative at any point
- Latest statements are too old

## Example Output

```
Stock Ticker: KO

 _________________________________________________________
| VALUATIONS:  The Coca-Cola Company
|
|                               value  reliability  weight
|                         ddm   67.20            5  55.56%
|                         fcfe  73.26            3  33.33%
|                         ri    28.67            0    0.0%
|                         fcff  72.49            1  11.11%
|
|                                      5 = Highly reliable
|                               0 = Not reliable, Unusable
|_________________________________________________________
| INITIAL MODEL RESULT
|                             Current Market Value:  86.17
|                           Master Intrinsic Value:  69.8
|_________________________________________________________
| WHAT THE PRICE ASSUMES
|
| Market price implies FCFE growth of 8.4%. Model uses 6.3%.
| Of 1154 large companies 2010 - 2016, 45% grew that fast.
|_________________________________________________________
| SENSITIVITY ANALYSIS
|
| Terminal Growth     -1%   -0.5%     +0%   +0.5%     +1%
| Cost of Equity                                         
| -2%              105.91  132.07  178.64  285.05  798.19
| -1%               73.53   84.61  100.58  125.62  170.57
| +0%               56.16   62.07   69.80   80.35   95.60
| +1%               45.34   48.92   53.34   58.95   66.30
| +2%               37.95   40.29   43.09   46.48   50.67
|_________________________________________________________
| FINAL VERDICT
|
|  Values in the 3x3 sensitivity range straddle the market price.
|  VERDICT: Model cannot distinguish price from fair value.
```

```
Stock Ticker: JPM

Data behind high-growth assumption insufficient; FCFE model inappropriate.
Data behind high-growth assumption insufficient; FCFF model inappropriate.
 _________________________________________________________
| VALUATIONS:  JPMorgan Chase & Co.
|
|                                value  reliability  weight
|                         ddm   179.33            0    0.0%
|                         fcfe       -            0    0.0%
|                         ri    155.57            4  100.0%
|                         fcff       -            0    0.0%
|
|                                      5 = Highly reliable
|                               0 = Not reliable, Unusable
|_________________________________________________________
| INITIAL MODEL RESULT
|                             Current Market Value:  331.28
|                           Master Intrinsic Value:  155.57
|_________________________________________________________
| WHAT THE PRICE ASSUMES
|
| Market price implies a permanent ROE of 17.7%.
| ROE last 4 years is 15.9%; median ROE over 18 years is 9.7%.
|_________________________________________________________
| SENSITIVITY ANALYSIS
|
| ROE Target         -2%     -1%     +0%     +1%     +2%
| Cost of Equity                                        
| -2%             153.38  171.05  193.75  217.51  242.37
| -1%             145.08  153.19  172.36  192.41  213.36
| +0%             137.43  144.45  155.57  172.76  190.72
| +1%             131.87  138.52  145.33  160.43  176.17
| +2%             129.30  135.68  142.20  155.83  170.02
|_________________________________________________________
| FINAL VERDICT
|
|  Every value in the 3x3 sensitivity range is below the market price.
|  VERDICT: Price is above the model's range (OVERVALUED)
|
|                       VERDICT IS UNRELIABLE. REASON(S):
|  Recent ROE of 15.9% is well above long-run target of 9.4%; value too sensitive to ROE persistence.
```

## Known Limitations

Typical error is ~40% either way from a 2012 - 2026 backtest on 255 companies. Verdicts did not predict later returns. Output should not be treated as a signal or recommendation, but rather as something that shows what the market is assuming and whether that is believable.

The model values the last four years, which may be insufficient for companies with outlooks that change. Check for what the market is now pricing in the output.

Revenue growth above 25% is outside the range the growth formula was built from. A message will print with this warning.

Banks are valued only on residual income, which depends heavily on ROE persistence.

Companies with negative equity have a terminal growth at the fallback, which is very optimistic.

Scores are pass/fail on all models, so anything that's a near miss is a full miss.

## Project Files

main.py - the program
base_rates.csv - 1,154 realised ten-year earnings growth rates from SEC filings
requirements.txt - list of python packages the program needs
LICENSE - MIT License

## Data Sources

Yahoo Finance, via the yfinance package: prices, dividends, and the last four years of financial statements.
github.com/ranaroussi/yfinance

SEC EDGAR, companyfacts API: long filing histories (ROE persistence, target ROE, revenue growth).
sec.gov/edgar/sec-api-documentation
Ticker-to-CIK map: sec.gov/files/company_tickers.json

FRED (Federal Reserve Bank of St. Louis): nominal GDP, for the 30-year growth anchor.
fred.stlouisfed.org/series/GDP

Damodaran Online (NYU Stern): credit spreads by interest coverage, and the implied equity risk premium.
Spreads: pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html
Implied ERP (monthly): pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx

Base rates: 1,154 realized ten-year earnings growth rates, built from EDGAR filings of 227 large US companies (start years 2010 to 2016). Included as base_rates.csv.

## Disclaimer

This program is a learning project. Nothing it outputs is investment advice, and no accuracy or fitness for any purpose is warranted; use it at your own risk.

## Contact

Name: William Tyler
LinkedIn: www.linkedin.com/in/willtylerfinance
