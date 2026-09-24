from apscheduler.schedulers.asyncio import AsyncIOScheduler
s = AsyncIOScheduler(timezone='Europe/Berlin', job_defaults={
    'misfire_grace_time': 600, 'coalesce': True, 'max_instances': 1})
s.add_job(check, 'cron', minute='*/30')
