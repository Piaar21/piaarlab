# return_process/cron.py

from .views import update_return_items

def fetch_and_update_returns():
    update_return_items(None)
