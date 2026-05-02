from flask import Blueprint, render_template, session, redirect, url_for, flash, request, g
import sqlite3
from functools import wraps
from werkzeug.security import generate_password_hash

admin_bp = Blueprint('admin', __name__, template_folder='templates/admin')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect('panel.db')
        db.row_factory = sqlite3.Row
    return db

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or session['username'] != 'scam':
            flash("You do not have permission to access the admin panel.", "error")
            # We redirect to index.html (the frontend main page) or login
            return redirect('/')
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@admin_required
def dashboard():
    db = get_db()
    # Fetch all tables
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    table_stats = []
    for table in tables:
        table_name = table['name']
        count = db.execute(f"SELECT COUNT(*) as count FROM {table_name}").fetchone()['count']
        table_stats.append({'name': table_name, 'count': count})
    
    return render_template('dashboard.html', table_stats=table_stats)

@admin_bp.route('/<table>')
@admin_required
def view_table(table):
    db = get_db()
    # Verify table exists to prevent injection
    tables = [row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if table not in tables:
        flash("Table not found.", "error")
        return redirect(url_for('admin.dashboard'))
        
    search = request.args.get('q', '')
    
    # Get columns
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    column_names = [col['name'] for col in columns]
    
    # Build query
    query = f"SELECT * FROM {table}"
    params = []
    
    if search:
        search_clauses = [f"{col} LIKE ?" for col in column_names]
        query += " WHERE " + " OR ".join(search_clauses)
        params = [f"%{search}%" for _ in column_names]
        
    query += " ORDER BY id DESC LIMIT 100" # Basic pagination/limit
        
    rows = db.execute(query, params).fetchall()
    
    return render_template('table.html', table=table, columns=column_names, rows=rows, search=search)

@admin_bp.route('/<table>/create', methods=['GET', 'POST'])
@admin_required
def create_row(table):
    db = get_db()
    tables = [row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if table not in tables:
        return redirect(url_for('admin.dashboard'))
        
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    # Remove 'id' from insertable columns if it's autoincrement, typically it's the first one
    insertable_columns = [col for col in columns if col['name'] != 'id']
    
    if request.method == 'POST':
        col_names = [col['name'] for col in insertable_columns]
        values = []
        for col in col_names:
            val = request.form.get(col)
            if col == 'password' and val:
                val = generate_password_hash(val)
            values.append(val)
        
        placeholders = ', '.join(['?'] * len(values))
        query = f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({placeholders})"
        
        try:
            db.execute(query, values)
            db.commit()
            flash("Record created successfully.", "success")
            return redirect(url_for('admin.view_table', table=table))
        except Exception as e:
            flash(f"Error: {e}", "error")
            
    return render_template('form.html', table=table, columns=insertable_columns, action="Create")

@admin_bp.route('/<table>/edit/<id>', methods=['GET', 'POST'])
@admin_required
def edit_row(table, id):
    db = get_db()
    tables = [row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if table not in tables:
        return redirect(url_for('admin.dashboard'))
        
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    insertable_columns = [col for col in columns if col['name'] != 'id']
    
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (id,)).fetchone()
    if not row:
        flash("Record not found.", "error")
        return redirect(url_for('admin.view_table', table=table))
        
    if request.method == 'POST':
        col_names = []
        values = []
        for col in insertable_columns:
            name = col['name']
            val = request.form.get(name)
            
            if name == 'password':
                if not val:  # Skip updating password if left blank
                    continue
                val = generate_password_hash(val)
                
            col_names.append(name)
            values.append(val)
        
        set_clause = ', '.join([f"{col} = ?" for col in col_names])
        query = f"UPDATE {table} SET {set_clause} WHERE id = ?"
        values.append(id)
        
        try:
            db.execute(query, values)
            db.commit()
            flash("Record updated successfully.", "success")
            return redirect(url_for('admin.view_table', table=table))
        except Exception as e:
            flash(f"Error: {e}", "error")
            
    return render_template('form.html', table=table, columns=insertable_columns, row=row, action="Edit")

@admin_bp.route('/<table>/delete/<id>', methods=['POST'])
@admin_required
def delete_row(table, id):
    db = get_db()
    tables = [row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if table in tables:
        try:
            db.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
            db.commit()
            flash("Record deleted successfully.", "success")
        except Exception as e:
            flash(f"Error: {e}", "error")
    return redirect(url_for('admin.view_table', table=table))

@admin_bp.route('/logout')
@admin_required
def logout():
    session.clear()
    flash("Admin logged out.", "success")
    return redirect('/')
