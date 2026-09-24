def chart(t):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{t}')
    q = r.json()['chart']['result'][0]['indicators']['quote'][0]
    return pd.DataFrame({'Close': q['close']}).dropna(subset=['Close'])
