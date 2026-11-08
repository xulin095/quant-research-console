from data.us import USFetcher
from data.cn import CNFetcher
from data.crypto import CryptoFetcher

FETCHERS = {"us": USFetcher, "cn": CNFetcher, "crypto": CryptoFetcher}


def get_fetcher(market: str):
    if market not in FETCHERS:
        raise KeyError(market)
    return FETCHERS[market]()


if __name__ == "__main__":
    print("可用市场：" + ", ".join(FETCHERS))
