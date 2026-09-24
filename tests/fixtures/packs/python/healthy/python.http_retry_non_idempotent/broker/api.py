def _request(self, method, path, retries=3, **kw):
    idempotent = method.upper() in ('GET', 'DELETE')
    for attempt in range(retries):
        try:
            r = self.session.request(method, self.base + path, timeout=15, **kw)
            return r.json()
        except Exception:
            if not idempotent:
                raise
            time.sleep(2)
