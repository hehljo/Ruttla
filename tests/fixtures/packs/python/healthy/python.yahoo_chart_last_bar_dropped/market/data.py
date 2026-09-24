def chart(t):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{t}')
    res = r.json()['chart']['result'][0]
    df = frame(res)
    df.iloc[-1, 0] = res['meta']['regularMarketPrice']
    return df.dropna(subset=['Close'])
