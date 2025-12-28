import sys
import os

# اضافه کردن مسیر پروژه
sys.path.insert(0, os.path.dirname(__file__))

# ایمپورت برنامه Flask
from app import app as application, init_db

# ساخت دیتابیس اگر وجود ندارد
db_path = os.path.join(os.path.dirname(__file__), "database.db")
if not os.path.exists(db_path):
    with application.app_context():
        init_db()
