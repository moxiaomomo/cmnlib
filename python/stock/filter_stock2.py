import tushare as ts
import pandas as pd

token = "0961c52e0496c838c12548031cb477ab498d355543d17adca49a90db"
ts.set_token(token)
pro = ts.pro_api()

df = pro.daily(trade_date='20260126')
for _, row in df.iterrows():
    print("{} {} {}".format(row["ts_code"], row["close"], row["pct_chg"]))
    
# df = pro.daily_basic(ts_code='920981.BJ', fields='ts_code,market_cap')
# print(df)