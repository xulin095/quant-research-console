import os

CAPITAL = 100000
FAST = 5
SLOW = 20
LONG = 60
MACD = (12, 26, 9)
RSI_N = 14
FEE = 0.0003
SLIP = 0.0005
RF = 0.02
TRADING_DAYS = 252
MIN_ROWS = 60
VOL_N = 20
PROXY = os.environ.get("QUANT_PROXY", "")  # 空串 = 不用代理
