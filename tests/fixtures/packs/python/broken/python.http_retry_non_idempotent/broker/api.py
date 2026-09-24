def _request(self, method, path, retries=3, **kw):
    for attempt in range(retries):
        try:
            r = self.session.request(method, self.base + path, timeout=15, **kw)
            return r.json()
        except Exception:
            time.sleep(2)
