from apscheduler.schedulers.asyncio import AsyncIOScheduler
s = AsyncIOScheduler(timezone='Europe/Berlin')
s.add_job(check, 'cron', minute='*/30')
