import logging
from telegram.ext import Application
logging.basicConfig(level=logging.INFO)
for name in ('httpx', 'httpcore'):
    logging.getLogger(name).setLevel(logging.WARNING)
