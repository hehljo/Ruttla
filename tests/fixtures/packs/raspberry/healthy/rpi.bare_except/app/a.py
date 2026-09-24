import logging
def go():
    try:
        x = 1
    except ValueError as e:
        logging.error(e)
