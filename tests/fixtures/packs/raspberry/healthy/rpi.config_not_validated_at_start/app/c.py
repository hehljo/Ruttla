import os
PORT = os.environ.get('PORT')
if not PORT:
    raise ValueError('PORT fehlt')
