import datetime
import random
import akshare as ak
import pandas as pd

def generate_nid():
    nid = ''.join(random.choices('0123456789abcdefghijklmnopqrstuvwxyz', k=32))
    create_time = int(datetime.now().timestamp()*1000)
    return nid, create_time

def filter_stocks_by_market_cap(min_cap, max_cap, min_price, max_price, min_turnover, max_turnover, min_price2book, max_price2book):
    """
    筛选出市值在[min_cap, max_cap]区间的A股股票
    
    参数:
    min_cap: 最小市值(亿元)
    max_cap: 最大市值(亿元)
    
    返回:
    符合条件的股票DataFrame
    """
    
    nid, create_time = generate_nid
    headers = {
        "cookie": f"nid18={nid}; nid18_create_time={create_time};",
    }
    
    # 获取A股实时行情数据（包含总市值）
    stock_df = ak.stock_zh_a_spot_em()
    
    # 查看数据中市值列的名称，通常是"总市值"
    # print(stock_df.columns)
    print(len(stock_df))
    
    # 1.过滤出市值在指定区间的股票
    # 注意：市值数据可能是字符串类型，需要转换为数值型
    stock_df["总市值"] = pd.to_numeric(stock_df["总市值"], errors="coerce")
    filtered_df = stock_df[(stock_df["总市值"] >= min_cap) & (stock_df["总市值"] <= max_cap)]

    # 2.过滤出最新股价在指定区间的股票
    filtered_df["最新价"] = pd.to_numeric(filtered_df["最新价"], errors="coerce")
    filtered_df = filtered_df[(filtered_df["最新价"] >= min_price) & (filtered_df["最新价"] <= max_price)] 
    
    # 3.过滤出换手率在指定区间的股票
    filtered_df["换手率"] = pd.to_numeric(filtered_df["换手率"], errors="coerce")
    filtered_df = filtered_df[(filtered_df["换手率"] >= min_turnover) & (filtered_df["换手率"] <= max_turnover)] 

    # 4.科创板股票代码以688开头，筛选掉这些股票
    # 注意：代码列的名称可能是"代码"或"证券代码"，根据实际返回调整
    filtered_df = filtered_df[~filtered_df["代码"].str.startswith("688")]

    # 5.60日涨跌幅超过-5%的股票
    filtered_df["60日涨跌幅"] = pd.to_numeric(filtered_df["60日涨跌幅"], errors="coerce")
    filtered_df = filtered_df[filtered_df["60日涨跌幅"] <= -5]

    # 6.排除年初至今涨跌幅 < 50%的股票
    filtered_df["年初至今涨跌幅"] = pd.to_numeric(filtered_df["年初至今涨跌幅"], errors="coerce")
    filtered_df = filtered_df[filtered_df["年初至今涨跌幅"] <= 50]

    # 7.过滤出市净率在指定区间的股票
    filtered_df["市净率"] = pd.to_numeric(filtered_df["市净率"], errors="coerce")
    filtered_df = filtered_df[(filtered_df["市净率"] >= min_price2book) & (filtered_df["市净率"] <= max_price2book)] 

    # 按市值降序排列
    filtered_df = filtered_df.sort_values(by="总市值", ascending=False)

    return filtered_df

# 示例：筛选总市值在50亿到3000亿之间、股价在6～30元、换手率在1%~15%之间的、非科创板的股票
result = filter_stocks_by_market_cap(5000000000, 300000000000, 6, 30, 1, 15, 0.5, 4)
print(f"符合搜索调教的股票共有{len(result)}只。")
#print(result[["代码", "名称", "总市值"]])
for i in range(int(len(result)/10)):
    print(result[i*10:i*10+10])