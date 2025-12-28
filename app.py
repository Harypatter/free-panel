from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

# [تغییر جدید]: ایمپورت‌های فایربیس
import firebase_admin
from firebase_admin import credentials, messaging

app = Flask(__name__)
app.secret_key = 'KEY_KHILI_SECRET_VA_PIChIDE_BEDAHID'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# [تغییر جدید]: تنظیم فایربیس (فایل جیسون باید کنار app.py باشد)
# بررسی میکنیم اگر قبلا اینیشیالایز نشده، انجامش بده (برای جلوگیری از ارور در ریلود شدن سرور)
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        print("Firebase Initialized Successfully")
    except Exception as e:
        print(f"Firebase Init Error: {e}")

# --------------------------
# Models (Database)
# --------------------------

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    app_text = db.Column(db.Text, default="")
    v2ray_configs = db.Column(db.Text, default="")
    deprecated_version = db.Column(db.String(50), default="1.0.0")
    force_update = db.Column(db.Boolean, default=False)
    admin_password = db.Column(db.String(200))

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(100), unique=True, nullable=False)
    current_version = db.Column(db.String(50))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    # [تغییر جدید]: اضافه کردن ستون برای توکن فایربیس
    fcm_token = db.Column(db.String(255), nullable=True)

# --------------------------
# Helper Functions
# --------------------------

def compare_versions(ver1, ver2):
    def normalize(v):
        return [int(x) for x in v.split(".")]
    try:
        return normalize(ver1) < normalize(ver2)
    except:
        return False

# [تغییر جدید]: تابع ارسال نوتیفیکیشن به همه (اصلاح شده برای نسخه جدید فایربیس)
def send_notification_to_all(title, body):
    try:
        # گرفتن تمام دستگاه‌هایی که توکن دارند
        devices = Device.query.filter(Device.fcm_token != None).all()
        tokens = [d.fcm_token for d in devices if d.fcm_token]

        if not tokens:
            return 0

        # ارسال پیام به صورت دسته‌ای
        success_count = 0
        batch_size = 500
        
        for i in range(0, len(tokens), batch_size):
            batch_tokens = tokens[i:i + batch_size]
            
            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                tokens=batch_tokens,
            )
            
            # --- بخش تغییر یافته ---
            # متد send_multicast حذف شده و باید از send_each_for_multicast استفاده شود
            response = messaging.send_each_for_multicast(message)
            # ----------------------
            
            success_count += response.success_count
            
        return success_count
    except Exception as e:
        print(f"Error sending notification: {e}")
        return -1

def init_db():
    with app.app_context():
        db.create_all()
        if not Settings.query.first():
            hashed_pw = generate_password_hash("123456")
            default_settings = Settings(
                app_text="متن خوش آمد گویی",
                v2ray_configs="vless://...",
                deprecated_version="1.0.0",
                force_update=False,
                admin_password=hashed_pw
            )
            db.session.add(default_settings)
            db.session.commit()

# --------------------------
# API Routes (Android)
# --------------------------

@app.route('/api/handshake', methods=['POST'])
def handshake():
    data = request.json
    
    device_id = data.get('device_id')
    app_version = data.get('app_version')
    # [تغییر جدید]: دریافت توکن از کلاینت
    fcm_token = data.get('fcm_token')

    if not device_id or not app_version:
        return jsonify({'status': 'error', 'message': 'Missing parameters'}), 400

    device = Device.query.filter_by(device_id=device_id).first()
    
    if device:
        device.current_version = app_version
        device.last_seen = datetime.utcnow()
        # [تغییر جدید]: آپدیت توکن اگر ارسال شده بود
        if fcm_token:
            device.fcm_token = fcm_token
    else:
        # [تغییر جدید]: ذخیره توکن هنگام ساخت دستگاه جدید
        device = Device(device_id=device_id, current_version=app_version, fcm_token=fcm_token)
        db.session.add(device)
    
    db.session.commit()

    settings = Settings.query.first()
    update_needed = compare_versions(app_version, settings.deprecated_version)

    response = {
        'status': 'success',
        'data': {
            'text': settings.app_text,
            'configs': settings.v2ray_configs,
            'update_needed': update_needed,
            'force_update': settings.force_update,
            'server_version': settings.deprecated_version
        }
    }
    
    return jsonify(response)

# --------------------------
# Web Routes (Admin Panel)
# --------------------------

@app.route('/')
def index_redirect():
    return redirect('/admin/login')

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        settings = Settings.query.first()
        
        if settings and check_password_hash(settings.admin_password, password):
            session['is_admin'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('رمز عبور اشتباه است')
            
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
def dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    settings = Settings.query.first()

    if request.method == 'POST':
        # [تغییر جدید]: بررسی اینکه آیا فرم تنظیمات است یا فرم نوتیفیکیشن
        if 'send_notification' in request.form:
            notif_title = request.form.get('notif_title')
            notif_body = request.form.get('notif_body')
            
            if notif_title and notif_body:
                count = send_notification_to_all(notif_title, notif_body)
                if count >= 0:
                    flash(f'نوتیفیکیشن با موفقیت برای {count} دستگاه ارسال شد.')
                else:
                    flash('خطا در ارسال نوتیفیکیشن. لاگ سرور را چک کنید.')
            else:
                flash('عنوان و متن پیام الزامی است.')
        else:
            # ذخیره تنظیمات معمولی
            settings.app_text = request.form.get('app_text')
            settings.v2ray_configs = request.form.get('v2ray_configs')
            settings.deprecated_version = request.form.get('deprecated_version')
            settings.force_update = True if request.form.get('force_update') else False
            
            db.session.commit()
            flash('تنظیمات با موفقیت ذخیره شد')
            
        return redirect(url_for('dashboard'))

    return render_template('dashboard.html', settings=settings)

@app.route('/admin/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)