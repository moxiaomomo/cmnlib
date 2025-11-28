import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd
from mplfinance.original_flavor import candlestick_ohlc
import matplotlib.dates as mdates
import numpy as np
import matplotlib.ticker as ticker

# 先设定一个日期转换方法
def format_date(x, pos=None): 
    # 由于前面股票数据在 date 这个位置传入的都是int # 因此 x=0,1,2,... 
    # date_tickers 是所有日期的字符串形式列表 
    if x<0 or x>len(dateCopy)-1: 
        return '' 
    return dateCopy[int(x)]

# 设置中文字体
plt.rcParams["font.sans-serif"] = ["SimHei"]  # 用来正常显示中文标签
plt.rcParams["axes.unicode_minus"] = False  # 用来正常显示负号

# 获取股票数据
stock_name = "广联航空"
stock_code = "300900"
start_date = "20250201"
end_date = "20250825"

print(f"正在获取股票 {stock_code} 从 {start_date} 到 {end_date} 的历史行情数据...")
stock_data = ak.stock_zh_a_hist(
    symbol=stock_code, start_date=start_date, end_date=end_date, adjust="qfq"
)
#print(stock_data)


# 将日期列转换为 matplotlib 可识别的日期格式
# stock_data["日期"] = pd.to_datetime(stock_data["日期"]).apply(
#     lambda x: mdates.date2num(x)
# )
dateCopy = [x for x in stock_data["日期"]]

# 重新排列列顺序以适应 mplfinance 的格式
stock_data = stock_data[["日期", "开盘", "最高", "最低", "收盘", "成交量"]]
stock_data["日期"] = range(0, len(stock_data["日期"]))
#print(stock_data)

# 计算布林线
stock_data["中轨"] = stock_data["收盘"].rolling(window=20).mean()
stock_data["上轨"] = (
    stock_data["中轨"] + 2 * stock_data["收盘"].rolling(window=20).std()
)
stock_data["下轨"] = (
    stock_data["中轨"] - 2 * stock_data["收盘"].rolling(window=20).std()
)

# 计算 MACD
exp1 = stock_data["收盘"].ewm(span=12, adjust=False).mean()
exp2 = stock_data["收盘"].ewm(span=26, adjust=False).mean()
stock_data["MACD"] = exp1 - exp2
stock_data["信号线"] = stock_data["MACD"].ewm(span=9, adjust=False).mean()
stock_data["MACD柱"] = stock_data["MACD"] - stock_data["信号线"]

# 绘制K线图
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

# 绘制K线
# # 用 set_major_formatter() 方法来修改主刻度的文字格式化方式
ax1.xaxis.set_major_formatter(ticker.FuncFormatter(format_date))#格式化x轴的格式
ax1.xaxis.set_major_locator(ticker.MultipleLocator(base=10))#用来修改主刻度的单位显示,设置为7个单位显示一次
candlestick_ohlc(
    ax1,
    stock_data[["日期", "开盘", "最高", "最低", "收盘"]].values,
    width=0.6,
    colorup="red",
    colordown="green",
)

ax1.plot(stock_data["日期"], stock_data["中轨"], label="中轨", linewidth=0.6)
ax1.plot(stock_data["日期"], stock_data["上轨"], label="上轨", linewidth=0.6)
ax1.plot(stock_data["日期"], stock_data["下轨"], label="下轨", linewidth=0.6)
#ax1.xaxis_date()
ax1.grid(True)

ax1.legend()
ax1.set_title(stock_name+" K线图与布林线")

# 绘制MACD
ax2.plot(stock_data["日期"], stock_data["MACD"], label="MACD")
ax2.plot(stock_data["日期"], stock_data["信号线"], label="信号线")
ax2.bar(stock_data["日期"], stock_data["MACD柱"], label="MACD柱")
ax2.xaxis_date()
ax2.legend()
ax2.set_title(stock_name+" MACD")

plt.tight_layout()
plt.show()