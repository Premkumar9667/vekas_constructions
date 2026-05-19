"""
VEKAS Construction Project Portal
Flask + MySQL Backend — app.py
"""

import os
import json
import uuid
import shutil
from functools import wraps
from datetime import datetime, timedelta

import pymysql
import pymysql.cursors
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config

# ── Optional AI / Document libraries ──────────────────────────
try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from pypdf import PdfReader as _PdfReader
    PDF_LIB = 'pypdf'
except ImportError:
    try:
        import PyPDF2 as _PyPDF2
        PDF_LIB = 'pypdf2'
    except ImportError:
        PDF_LIB = None

try:
    from docx import Document as _DocxDoc
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        port=app.config['MYSQL_PORT'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


# ──────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────
def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS'])


def fmt_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def fmt_duration(seconds):
    seconds = int(seconds or 0)
    if seconds < 3600:
        minutes = max(1, seconds // 60) if seconds else 0
        return f"{minutes} min" if minutes else "No activity yet"
    hours = seconds // 3600
    days = hours // 24
    if days:
        rem_hours = hours % 24
        return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"
    return f"{hours}h"


def sanitize_project_prefix(prefix):
    cleaned = ''.join(ch for ch in (prefix or '').upper().strip() if ch.isalnum())
    return (cleaned or 'VKS')[:12]


def normalize_india_phone(value):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if digits.startswith('91') and len(digits) > 10:
        digits = digits[2:]
    digits = digits[-10:] if len(digits) >= 10 else digits
    return f"+91{digits}" if len(digits) == 10 else ''


def india_phone_digits(value):
    normalized = normalize_india_phone(value)
    return normalized[-10:] if normalized else ''


def normalize_project_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = datetime.now().year
    return min(2030, max(2000, year))


def ensure_project_identity_schema(cursor):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'projects'
          AND COLUMN_NAME IN ('project_prefix', 'project_year', 'project_sequence')
    """)
    existing_cols = {row['COLUMN_NAME'] for row in cursor.fetchall()}
    if 'project_prefix' not in existing_cols:
        cursor.execute("ALTER TABLE projects ADD COLUMN project_prefix VARCHAR(20) DEFAULT NULL AFTER project_code")
    if 'project_year' not in existing_cols:
        cursor.execute("ALTER TABLE projects ADD COLUMN project_year SMALLINT DEFAULT NULL AFTER project_prefix")
    if 'project_sequence' not in existing_cols:
        cursor.execute("ALTER TABLE projects ADD COLUMN project_sequence INT DEFAULT NULL AFTER project_year")

    cursor.execute("""
        SELECT INDEX_NAME
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'projects'
          AND INDEX_NAME IN ('uq_projects_company_name', 'uq_projects_contact_number')
    """)
    rows = cursor.fetchall()
    for row in rows:
        cursor.execute(f"DROP INDEX {row['INDEX_NAME']} ON projects")


def generate_project_code(cursor, prefix=None, year=None):
    prefix = sanitize_project_prefix(prefix)
    year = normalize_project_year(year)
    code_prefix = f"{prefix}-{year}-"
    cursor.execute("""
        SELECT project_code, project_sequence
        FROM projects
        WHERE project_code LIKE %s
           OR (project_prefix = %s AND project_year = %s)
           OR project_code IS NULL
        ORDER BY COALESCE(project_sequence, 0) DESC, project_code DESC
    """, (code_prefix + '%', prefix, year))
    rows = cursor.fetchall()
    max_num = 0
    for row in rows:
        candidates = []
        if row.get('project_sequence'):
            candidates.append(row['project_sequence'])
        if row.get('project_code'):
            try:
                candidates.append(int(row['project_code'].split('-')[-1]))
            except (ValueError, IndexError):
                pass
        if candidates:
            max_num = max(max_num, *candidates)
    next_num = max(max_num, len(rows)) + 1
    return f"{code_prefix}{next_num:03d}", prefix, year, next_num


def file_icon(file_type):
    icons = {
        'pdf':  'picture_as_pdf',
        'dwg':  'architecture', 'dxf': 'architecture',
        'rvt':  'architecture', 'ifc': 'architecture',
        'xlsx': 'table_view',   'xls': 'table_view', 'csv': 'table_view',
        'doc':  'description',  'docx': 'description', 'txt': 'article',
        'png':  'image',        'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
        'mp4':  'videocam',     'avi': 'videocam', 'mov': 'videocam',
        'zip':  'folder_zip',   'rar': 'folder_zip',
    }
    return icons.get((file_type or '').lower(), 'insert_drive_file')


def file_color(file_type):
    colors = {
        'pdf':  ('bg-red-50', 'text-red-600'),
        'dwg':  ('bg-blue-50', 'text-blue-600'),
        'dxf':  ('bg-blue-50', 'text-blue-600'),
        'xlsx': ('bg-green-50', 'text-green-600'),
        'xls':  ('bg-green-50', 'text-green-600'),
        'csv':  ('bg-green-50', 'text-green-600'),
        'doc':  ('bg-indigo-50', 'text-indigo-600'),
        'docx': ('bg-indigo-50', 'text-indigo-600'),
        'png':  ('bg-purple-50', 'text-purple-600'),
        'jpg':  ('bg-purple-50', 'text-purple-600'),
        'jpeg': ('bg-purple-50', 'text-purple-600'),
        'mp4':  ('bg-orange-50', 'text-orange-600'),
        'zip':  ('bg-yellow-50', 'text-yellow-600'),
    }
    return colors.get((file_type or '').lower(), ('bg-slate-50', 'text-slate-600'))


def time_ago(dt):
    if not dt:
        return ''
    now = datetime.now()
    diff = now - dt
    if diff < timedelta(minutes=1):
        return 'just now'
    elif diff < timedelta(hours=1):
        m = int(diff.total_seconds() / 60)
        return f"{m}m ago"
    elif diff < timedelta(days=1):
        h = int(diff.total_seconds() / 3600)
        return f"{h}h ago"
    elif diff < timedelta(days=30):
        return f"{diff.days}d ago"
    else:
        return dt.strftime('%b %d, %Y')


def log_activity(cursor, project_id, action, details=''):
    cursor.execute(
        "INSERT INTO activity_log (project_id, user_id, action, details) VALUES (%s,%s,%s,%s)",
        (project_id, session.get('user_id'), action, details)
    )


# ──────────────────────────────────────────────
# Auth decorator
# ──────────────────────────────────────────────
def start_login_session(user_id):
    """Create a login-session row and return its id; never block auth."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE login_sessions
            SET logout_at = NOW(),
                duration_seconds = GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0)
            WHERE user_id = %s AND logout_at IS NULL
        """, (user_id,))
        cursor.execute("INSERT INTO login_sessions (user_id) VALUES (%s)", (user_id,))
        conn.commit()
        login_session_id = cursor.lastrowid
        conn.close()
        return login_session_id
    except Exception:
        return None


def close_login_session():
    login_session_id = session.get('login_session_id')
    user_id = session.get('user_id')
    if not login_session_id or not user_id:
        return
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE login_sessions
            SET logout_at = NOW(),
                duration_seconds = GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0)
            WHERE id = %s AND user_id = %s AND logout_at IS NULL
        """, (login_session_id, user_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _json_auth_response(message):
    return jsonify({
        'success': False,
        'error': message,
        'redirect': url_for('login')
    }), 401


def _is_json_request():
    return request.path.startswith('/api/') or request.is_json or request.method != 'GET'


def refresh_session_user():
    """Ensure the signed-in user still exists before using session['user_id']."""
    user_id = session.get('user_id')
    user_email = session.get('user_email')

    if not user_id and not user_email:
        return None

    conn = get_db()
    cursor = conn.cursor()
    try:
        user = None
        if user_id:
            cursor.execute("SELECT id, name, email, role FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

        if not user and user_email:
            cursor.execute("SELECT id, name, email, role FROM users WHERE email = %s", (user_email,))
            user = cursor.fetchone()

        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['user_role'] = user['role']
            return user

        return None
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session and 'user_email' not in session:
            if _is_json_request():
                return _json_auth_response('Please sign in to continue.')
            flash('Please sign in to continue.', 'info')
            return redirect(url_for('login'))

        try:
            if not refresh_session_user():
                session.clear()
                if _is_json_request():
                    return _json_auth_response('Your sign-in session is no longer valid. Please sign in again.')
                flash('Your sign-in session expired. Please sign in again.', 'info')
                return redirect(url_for('login'))
        except Exception as e:
            if _is_json_request():
                return jsonify({'success': False, 'error': f'Unable to validate sign-in session: {e}'}), 500
            flash(f'Unable to validate sign-in session: {e}', 'error')
            return redirect(url_for('login'))

        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────
# Template context processor
# ──────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return {
        'current_user': {
            'id':    session.get('user_id'),
            'name':  session.get('user_name', ''),
            'email': session.get('user_email', ''),
            'role':  session.get('user_role', ''),
        }
    }


# ══════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    tab = request.args.get('tab', 'signin')

    if request.method == 'POST':
        action = request.form.get('action', 'signin')

        # ── Sign In ──
        if action == 'signin':
            email    = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')

            if not email or not password:
                flash('Please enter your email and password.', 'error')
                return render_template('login.html', tab='signin')

            try:
                conn   = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                conn.close()

                if user and check_password_hash(user['password_hash'], password):
                    session.permanent = True
                    session['user_id']    = user['id']
                    session['user_name']  = user['name']
                    session['user_email'] = user['email']
                    session['user_role']  = user['role']
                    session['login_session_id'] = start_login_session(user['id'])
                    try:
                        audit_conn = get_db()
                        audit_cursor = audit_conn.cursor()
                        log_activity(audit_cursor, None, 'Signed In', 'Dashboard access')
                        audit_conn.commit()
                        audit_conn.close()
                    except Exception:
                        pass
                    flash(f"Welcome back, {user['name'].split()[0]}!", 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Incorrect email or password.', 'error')
            except Exception as e:
                flash(f'Sign-in error: {e}', 'error')

            return render_template('login.html', tab='signin')

        # ── Sign Up ──
        elif action == 'signup':
            name             = request.form.get('name', '').strip()
            email            = request.form.get('reg_email', '').strip().lower()
            password         = request.form.get('reg_password', '')
            confirm_password = request.form.get('confirm_password', '')
            company          = request.form.get('company', '').strip()

            errors = []
            if not name:            errors.append('Full name is required.')
            if not email:           errors.append('Email is required.')
            if not password:        errors.append('Password is required.')
            if len(password) < 8:   errors.append('Password must be at least 8 characters.')
            if password != confirm_password:
                errors.append('Passwords do not match.')

            if errors:
                for e in errors:
                    flash(e, 'error')
                return render_template('login.html', tab='signup')

            try:
                conn   = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    flash('An account with this email already exists. Please sign in.', 'error')
                    conn.close()
                    return render_template('login.html', tab='signup')

                pw_hash = generate_password_hash(password)
                cursor.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (%s,%s,%s,%s)",
                    (name, email, pw_hash, 'manager')
                )
                conn.commit()
                user_id = cursor.lastrowid
                conn.close()

                session['user_id']    = user_id
                session['user_name']  = name
                session['user_email'] = email
                session['user_role']  = 'manager'
                session['login_session_id'] = start_login_session(user_id)
                flash(f'Account created! Welcome to VEKAS, {name.split()[0]}!', 'success')
                return redirect(url_for('dashboard'))
            except Exception as e:
                flash(f'Registration error: {e}', 'error')
                return render_template('login.html', tab='signup')

    return render_template('login.html', tab=tab)


@app.route('/logout')
def logout():
    close_login_session()
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('login'))


# ══════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        conn   = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT p.*,
                   u.name  AS creator_name,
                   (SELECT COUNT(*) FROM files f WHERE f.project_id = p.id) AS file_count,
                   (SELECT COALESCE(SUM(file_size),0) FROM files f WHERE f.project_id = p.id) AS storage_bytes,
                   (SELECT pn.note FROM project_notes pn WHERE pn.project_id = p.id ORDER BY pn.updated_at DESC LIMIT 1) AS note_text
            FROM projects p
            LEFT JOIN users u ON p.created_by = u.id
            ORDER BY p.created_at DESC
        """)
        projects = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) AS n FROM projects")
        total_projects = cursor.fetchone()['n']

        cursor.execute("SELECT COUNT(*) AS n FROM projects WHERE status='In Progress'")
        active_count = cursor.fetchone()['n']

        cursor.execute("SELECT COUNT(*) AS n FROM users")
        total_users = cursor.fetchone()['n']

        cursor.execute("SELECT COALESCE(SUM(file_size),0) AS n FROM files")
        portfolio_storage = fmt_size(cursor.fetchone()['n'])

        is_admin = session.get('user_role') == 'admin'
        team_members = []
        if is_admin:
            cursor.execute("""
                SELECT u.id, u.name, u.email, u.role, u.created_at,
                       (SELECT COUNT(*) FROM projects p WHERE p.created_by = u.id) AS project_count_all,
                       (SELECT COUNT(*) FROM projects p WHERE p.created_by = u.id AND DATE(p.created_at) = CURDATE()) AS project_count_today,
                       (SELECT COUNT(*) FROM projects p WHERE p.created_by = u.id AND p.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS project_count_7,
                       (SELECT COUNT(*) FROM projects p WHERE p.created_by = u.id AND p.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)) AS project_count_30,
                       (SELECT COUNT(*) FROM files f WHERE f.uploaded_by = u.id) AS file_count_all,
                       (SELECT COUNT(*) FROM files f WHERE f.uploaded_by = u.id AND DATE(f.uploaded_at) = CURDATE()) AS file_count_today,
                       (SELECT COUNT(*) FROM files f WHERE f.uploaded_by = u.id AND f.uploaded_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS file_count_7,
                       (SELECT COUNT(*) FROM files f WHERE f.uploaded_by = u.id AND f.uploaded_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)) AS file_count_30,
                       (SELECT COALESCE(SUM(file_size),0) FROM files f WHERE f.uploaded_by = u.id) AS storage_bytes,
                       (SELECT MAX(login_at) FROM login_sessions ls WHERE ls.user_id = u.id) AS last_login,
                       (SELECT COALESCE(SUM(CASE WHEN logout_at IS NULL THEN GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0) ELSE duration_seconds END),0) FROM login_sessions ls WHERE ls.user_id = u.id) AS usage_seconds_all,
                       (SELECT COALESCE(SUM(CASE WHEN logout_at IS NULL THEN GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0) ELSE duration_seconds END),0) FROM login_sessions ls WHERE ls.user_id = u.id AND DATE(ls.login_at) = CURDATE()) AS usage_seconds_today,
                       (SELECT COALESCE(SUM(CASE WHEN logout_at IS NULL THEN GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0) ELSE duration_seconds END),0) FROM login_sessions ls WHERE ls.user_id = u.id AND ls.login_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS usage_seconds_7,
                       (SELECT COALESCE(SUM(CASE WHEN logout_at IS NULL THEN GREATEST(TIMESTAMPDIFF(SECOND, login_at, NOW()), 0) ELSE duration_seconds END),0) FROM login_sessions ls WHERE ls.user_id = u.id AND ls.login_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)) AS usage_seconds_30
                FROM users u
                ORDER BY u.created_at DESC
            """)
            team_members = cursor.fetchall()

        conn.close()

        # Enrich project data
        customer_groups = {}
        for p in projects:
            p['storage_display'] = fmt_size(p['storage_bytes'] or 0)
            if p.get('start_date'):
                p['start_date_display'] = p['start_date'].strftime('%b %Y')
            else:
                p['start_date_display'] = '—'

        for p in projects:
            customer_key = (p.get('customer_name') or p.get('client_name') or '').strip()
            if customer_key:
                customer_groups[customer_key] = customer_groups.get(customer_key, 0) + 1

        customer_groups = [
            {'name': name, 'count': count}
            for name, count in sorted(customer_groups.items(), key=lambda item: item[0].lower())
        ]

        now = datetime.now()
        for u in team_members:
            last_login = u.get('last_login')
            recent_signal = last_login or u.get('created_at')
            days_since_activity = 99999
            if recent_signal:
                days_since_activity = max(0, (now - recent_signal).days)

            u['initials'] = ''.join(part[:1] for part in (u.get('name') or 'VK').split()[:2]).upper()
            for key in ('all', 'today', '7', '30'):
                u[f'project_count_{key}'] = u.get(f'project_count_{key}') or 0
                u[f'file_count_{key}'] = u.get(f'file_count_{key}') or 0
                u[f'usage_seconds_{key}'] = int(u.get(f'usage_seconds_{key}') or 0)
                u[f'usage_display_{key}'] = fmt_duration(u[f'usage_seconds_{key}'])
            u['storage_display'] = fmt_size(u.get('storage_bytes') or 0)
            u['last_active_display'] = time_ago(last_login) if last_login else 'Never logged in'
            u['days_since_activity'] = days_since_activity
            u['joined_display'] = u['created_at'].strftime('%b %d, %Y') if u.get('created_at') else 'N/A'

        return render_template('dashboard.html',
                               projects=projects,
                               total_projects=total_projects,
                               active_count=active_count,
                               total_users=total_users,
                               portfolio_storage=portfolio_storage,
                               team_members=team_members,
                               customer_groups=customer_groups,
                               is_admin=is_admin)

    except Exception as e:
        flash(f'Error loading dashboard: {e}', 'error')
        return render_template('dashboard.html', projects=[],
                               total_projects=0, active_count=0,
                               total_users=0, portfolio_storage='0 B',
                               team_members=[],
                               customer_groups=[],
                               is_admin=session.get('user_role') == 'admin')


# ══════════════════════════════════════════════
# PROJECT CRUD
# ══════════════════════════════════════════════

@app.route('/api/project/create', methods=['POST'])
@login_required
def create_project():
    data = request.get_json(silent=True) or request.form

    project_prefix = sanitize_project_prefix(data.get('projectPrefix'))
    project_year = normalize_project_year(data.get('projectYear'))
    name        = (data.get('projectName') or '').strip()
    company_name = (data.get('companyName') or '').strip()
    customer_name = (data.get('customerName') or '').strip()
    client_name = (data.get('clientName') or '').strip() or customer_name
    job_position = (data.get('jobPosition') or '').strip()
    contact_number = normalize_india_phone(data.get('contactNumber'))
    whatsapp_number = normalize_india_phone(data.get('whatsappNumber'))
    email_id = (data.get('emailId') or '').strip()
    address = (data.get('address') or '').strip()
    city = (data.get('city') or '').strip()
    district = (data.get('district') or '').strip()
    state = (data.get('state') or '').strip()
    country = (data.get('country') or 'India').strip() or 'India'
    project_type = (data.get('projectType') or '').strip()
    project_location = (data.get('projectLocation') or '').strip()
    building_area_details = data.get('buildingAreaDetails') or []
    total_builtup_area = data.get('totalBuiltupArea') or 0
    description = (data.get('description') or '').strip()
    start_date  = data.get('startDate') or None
    priority    = data.get('priority', 'Medium')
    status      = data.get('status', 'Planning')

    if not name:
        return jsonify({'success': False, 'error': 'Project name is required.'}), 400
    if not customer_name:
        return jsonify({'success': False, 'error': 'Customer name is required.'}), 400
    if not company_name:
        return jsonify({'success': False, 'error': 'Company name is required.'}), 400
    if not client_name:
        return jsonify({'success': False, 'error': 'Customer display name is required.'}), 400
    if not contact_number:
        return jsonify({'success': False, 'error': 'Contact number is required.'}), 400

    try:
        conn   = get_db()
        cursor = conn.cursor()
        ensure_project_identity_schema(cursor)

        project_code, project_prefix, project_year, project_sequence = generate_project_code(cursor, project_prefix, project_year)
        cursor.execute("""
            INSERT INTO projects (
                project_code, project_prefix, project_year, project_sequence,
                name, client_name, company_name, customer_name,
                job_position, contact_number, whatsapp_number, email_id,
                address, city, district, state, country, project_type,
                project_location, building_area_details, total_builtup_area,
                description, start_date, priority, status, created_by
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            project_code, project_prefix, project_year, project_sequence,
            name, client_name, company_name, customer_name,
            job_position, contact_number or None, whatsapp_number or None, email_id,
            address, city, district, state, country, project_type,
            project_location, json.dumps(building_area_details), total_builtup_area,
            description, start_date, priority, status, session['user_id']
        ))
        project_id = cursor.lastrowid

        # Seed the notes panel with the notes entered during initiation.
        cursor.execute("INSERT INTO project_notes (project_id, note, updated_by) VALUES (%s,%s,%s)",
                       (project_id, description, session['user_id']))

        log_activity(cursor, project_id, 'Project Created', f'{project_code} "{name}" initiated')
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'project_id': project_id,
            'redirect': url_for('project_detail', project_id=project_id)
        })
    except pymysql.err.IntegrityError as e:
        message = str(e)
        return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/project/next-code')
@login_required
def next_project_code():
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_project_identity_schema(cursor)
        project_code, prefix, year, sequence = generate_project_code(
            cursor,
            request.args.get('prefix'),
            request.args.get('year')
        )
        conn.commit()
        conn.close()
        return jsonify({
            'success': True,
            'projectCode': project_code,
            'prefix': prefix,
            'year': year,
            'sequence': sequence
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/project/<int:project_id>/update', methods=['POST'])
@login_required
def update_project(project_id):
    data = request.get_json(silent=True) or request.form
    fields, values = [], []

    for col in ('name', 'client_name', 'description', 'status', 'priority', 'start_date', 'end_date'):
        if col in data:
            fields.append(f"{col} = %s")
            values.append(data[col] or None)

    if not fields:
        return jsonify({'success': False, 'error': 'Nothing to update'}), 400

    try:
        conn   = get_db()
        cursor = conn.cursor()
        values.append(project_id)
        cursor.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = %s", values)
        log_activity(cursor, project_id, 'Project Updated', ', '.join(f[:-5] for f in fields))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM projects WHERE id = %s", (project_id,))
        proj = cursor.fetchone()
        if not proj:
            conn.close()
            return jsonify({'success': False, 'error': 'Project not found.'}), 404

        # Remove uploaded files from disk
        proj_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id))
        if os.path.isdir(proj_dir):
            shutil.rmtree(proj_dir)

        cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'redirect': url_for('dashboard')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════
# PROJECT DETAIL PAGE
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT p.*, u.name AS creator_name
            FROM projects p LEFT JOIN users u ON p.created_by = u.id
            WHERE p.id = %s
        """, (project_id,))
        project = cursor.fetchone()

        if not project:
            flash('Project not found.', 'error')
            conn.close()
            return redirect(url_for('dashboard'))

        # Files
        cursor.execute("""
            SELECT f.*, u.name AS uploader_name
            FROM files f LEFT JOIN users u ON f.uploaded_by = u.id
            WHERE f.project_id = %s
            ORDER BY f.uploaded_at DESC
        """, (project_id,))
        all_files = cursor.fetchall()

        # Group by folder
        drawing_files = [f for f in all_files if f['folder_type'] == 'Drawing']
        output_files  = [f for f in all_files if f['folder_type'] == 'Output']

        # Enrich files
        for f in all_files:
            f['icon']         = file_icon(f.get('file_type'))
            f['icon_bg'], f['icon_text'] = file_color(f.get('file_type'))
            f['size_display'] = fmt_size(f.get('file_size') or 0)
            f['time_ago']     = time_ago(f.get('uploaded_at'))

        # Note
        cursor.execute("SELECT * FROM project_notes WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                       (project_id,))
        note = cursor.fetchone()

        # Activity
        cursor.execute("""
            SELECT a.*, u.name AS user_name
            FROM activity_log a LEFT JOIN users u ON a.user_id = u.id
            WHERE a.project_id = %s
            ORDER BY a.created_at DESC LIMIT 15
        """, (project_id,))
        activities = cursor.fetchall()
        for a in activities:
            a['time_ago'] = time_ago(a.get('created_at'))

        # Members
        cursor.execute("""
            SELECT pm.role AS member_role, u.id, u.name, u.email
            FROM project_members pm JOIN users u ON pm.user_id = u.id
            WHERE pm.project_id = %s
        """, (project_id,))
        members = cursor.fetchall()

        # Storage capacity
        cursor.execute("SELECT COALESCE(SUM(file_size),0) AS total FROM files WHERE project_id = %s",
                       (project_id,))
        total_bytes = cursor.fetchone()['total']
        capacity_pct = min(100, round(total_bytes / app.config['PROJECT_STORAGE_LIMIT'] * 100, 1))

        # Projects for the same client (for sidebar switcher)
        client_name = (project.get('client_name') or '').strip()
        if client_name:
            cursor.execute("""
                SELECT id, name, status
                FROM projects
                WHERE client_name = %s
                ORDER BY id = %s DESC, created_at DESC
            """, (client_name, project_id))
            other_projects = cursor.fetchall()
        else:
            other_projects = []

        conn.close()

        return render_template('project_detail.html',
                               project=project,
                               drawing_files=drawing_files,
                               output_files=output_files,
                               note=note,
                               activities=activities,
                               members=members,
                               capacity_pct=capacity_pct,
                               storage_used=fmt_size(total_bytes),
                               other_projects=other_projects,
                               anthropic_available=ANTHROPIC_AVAILABLE,
                               anthropic_configured=bool(app.config.get('ANTHROPIC_API_KEY', '').strip()))

    except Exception as e:
        flash(f'Error loading project: {e}', 'error')
        return redirect(url_for('dashboard'))


# Project files dedicated page
@app.route('/project/<int:project_id>/files')
@login_required
def project_files(project_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        project = cursor.fetchone()
        if not project:
            flash('Project not found.', 'error')
            conn.close()
            return redirect(url_for('dashboard'))

        folder = request.args.get('folder', 'Drawing')

        cursor.execute("""
            SELECT f.*, u.name AS uploader_name
            FROM files f LEFT JOIN users u ON f.uploaded_by = u.id
            WHERE f.project_id = %s AND f.folder_type = %s
            ORDER BY f.uploaded_at DESC
        """, (project_id, folder))
        files = cursor.fetchall()

        for f in files:
            f['icon']         = file_icon(f.get('file_type'))
            f['icon_bg'], f['icon_text'] = file_color(f.get('file_type'))
            f['size_display'] = fmt_size(f.get('file_size') or 0)
            f['time_ago']     = time_ago(f.get('uploaded_at'))

        # Stats
        cursor.execute("SELECT COALESCE(SUM(file_size),0) AS t, COUNT(*) AS c FROM files WHERE project_id = %s",
                       (project_id,))
        stats = cursor.fetchone()

        # Notes
        cursor.execute("SELECT note FROM project_notes WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                       (project_id,))
        note_row = cursor.fetchone()
        note_text = note_row['note'] if note_row else ''

        # Members
        cursor.execute("""
            SELECT pm.role AS member_role, u.name, u.email
            FROM project_members pm JOIN users u ON pm.user_id = u.id
            WHERE pm.project_id = %s
        """, (project_id,))
        members = cursor.fetchall()

        capacity_pct = min(100, round((stats['t'] or 0) / app.config['PROJECT_STORAGE_LIMIT'] * 100, 1))

        conn.close()

        return render_template('project_files.html',
                               project=project,
                               files=files,
                               current_folder=folder,
                               stats=stats,
                               note_text=note_text,
                               members=members,
                               capacity_pct=capacity_pct,
                               storage_display=fmt_size(stats['t'] or 0))
    except Exception as e:
        flash(f'Error: {e}', 'error')
        return redirect(url_for('dashboard'))


# ══════════════════════════════════════════════
# FILE OPERATIONS
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_files(project_id):
    folder_type = request.form.get('folder_type', 'Drawing')
    uploaded, errors = [], []

    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'No files in request.'}), 400

    file_list = request.files.getlist('files')
    if not file_list or all(f.filename == '' for f in file_list):
        return jsonify({'success': False, 'error': 'No files selected.'}), 400

    try:
        conn   = get_db()
        cursor = conn.cursor()

        project_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id))
        os.makedirs(project_dir, exist_ok=True)

        for file in file_list:
            if not file or file.filename == '':
                continue
            if not allowed_file(file.filename):
                errors.append(f'{file.filename}: file type not allowed.')
                continue

            original_name = secure_filename(file.filename)
            ext           = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
            stored_name   = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
            file_path     = os.path.join(project_dir, stored_name)

            file.save(file_path)
            file_size = os.path.getsize(file_path)

            cursor.execute("""
                INSERT INTO files (project_id, folder_type, filename, original_name, file_size, file_type, uploaded_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (project_id, folder_type, stored_name, original_name, file_size, ext, session['user_id']))
            file_id = cursor.lastrowid

            log_activity(cursor, project_id, 'File Uploaded',
                         f'"{original_name}" → {folder_type}')

            uploaded.append({
                'id':           file_id,
                'original_name': original_name,
                'size_display':  fmt_size(file_size),
                'file_type':     ext,
                'folder_type':   folder_type,
                'icon':          file_icon(ext),
                'time_ago':      'just now',
            })

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'uploaded': uploaded, 'errors': errors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/project/<int:project_id>/download/<int:file_id>')
@login_required
def download_file(project_id, file_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id=%s AND project_id=%s", (file_id, project_id))
        f = cursor.fetchone()
        conn.close()

        if not f:
            flash('File not found.', 'error')
            return redirect(url_for('project_files', project_id=project_id))

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
        if not os.path.exists(file_path):
            flash('File missing from server.', 'error')
            return redirect(url_for('project_files', project_id=project_id))

        return send_file(file_path, as_attachment=True, download_name=f['original_name'])
    except Exception as e:
        flash(f'Download error: {e}', 'error')
        return redirect(url_for('project_detail', project_id=project_id))


@app.route('/project/<int:project_id>/file/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(project_id, file_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id=%s AND project_id=%s", (file_id, project_id))
        f = cursor.fetchone()

        if not f:
            conn.close()
            return jsonify({'success': False, 'error': 'File not found.'}), 404

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)

        cursor.execute("DELETE FROM files WHERE id=%s", (file_id,))
        log_activity(cursor, project_id, 'File Deleted', f'"{f["original_name"]}" removed')
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════
# NOTES
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>/notes', methods=['POST'])
@login_required
def update_notes(project_id):
    data = request.get_json(silent=True) or request.form
    note_text = data.get('note', '')

    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM project_notes WHERE project_id=%s", (project_id,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("UPDATE project_notes SET note=%s, updated_by=%s, updated_at=NOW() WHERE project_id=%s",
                           (note_text, session['user_id'], project_id))
        else:
            cursor.execute("INSERT INTO project_notes (project_id, note, updated_by) VALUES (%s,%s,%s)",
                           (project_id, note_text, session['user_id']))
        log_activity(cursor, project_id, 'Notes Updated', '')
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════
# JSON API ENDPOINTS
# ══════════════════════════════════════════════

@app.route('/api/projects')
@login_required
def api_projects():
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.name, p.client_name, p.status, p.priority,
                   p.start_date, p.created_at,
                   COUNT(f.id) AS file_count
            FROM projects p LEFT JOIN files f ON f.project_id = p.id
            GROUP BY p.id ORDER BY p.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            if r.get('start_date'):
                r['start_date'] = r['start_date'].strftime('%b %Y')
            if r.get('created_at'):
                r['created_at'] = r['created_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify({'success': True, 'projects': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/project/<int:project_id>/files')
@login_required
def api_project_files(project_id):
    folder = request.args.get('folder', 'Drawing')
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.*, u.name AS uploader_name
            FROM files f LEFT JOIN users u ON f.uploaded_by = u.id
            WHERE f.project_id=%s AND f.folder_type=%s
            ORDER BY f.uploaded_at DESC
        """, (project_id, folder))
        files = cursor.fetchall()
        conn.close()
        for f in files:
            f['icon']         = file_icon(f.get('file_type'))
            f['size_display'] = fmt_size(f.get('file_size') or 0)
            if f.get('uploaded_at'):
                f['uploaded_at'] = f['uploaded_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify({'success': True, 'files': files})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/project/<int:project_id>/storage')
@login_required
def api_project_storage(project_id):
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(file_size),0) AS t, COUNT(*) AS c FROM files WHERE project_id=%s",
                       (project_id,))
        stats = cursor.fetchone()
        conn.close()
        total = stats['t'] or 0
        return jsonify({
            'success': True,
            'bytes': total,
            'display': fmt_size(total),
            'count': stats['c'],
            'pct': min(100, round(total / app.config['PROJECT_STORAGE_LIMIT'] * 100, 2))
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum is 100 MB per upload.'}), 413


@app.errorhandler(404)
def not_found(e):
    return render_template('login.html', tab='signin'), 404


# ══════════════════════════════════════════════
# TEXT EXTRACTION HELPER
# ══════════════════════════════════════════════

def extract_file_text(file_path, file_type, max_chars=6000):
    """Extract readable text from uploaded files for AI analysis."""
    ft = (file_type or '').lower()
    try:
        if ft in ('txt', 'md', 'csv', 'log'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()[:max_chars]

        elif ft == 'pdf' and PDF_LIB:
            text = ''
            if PDF_LIB == 'pypdf':
                reader = _PdfReader(file_path)
                for page in reader.pages[:15]:
                    text += (page.extract_text() or '') + '\n'
            else:
                with open(file_path, 'rb') as f:
                    reader = _PyPDF2.PdfReader(f)
                    for page in reader.pages[:15]:
                        text += (page.extract_text() or '') + '\n'
            return text[:max_chars] if text.strip() else None

        elif ft in ('doc', 'docx') and DOCX_AVAILABLE:
            doc = _DocxDoc(file_path)
            text = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:max_chars] if text.strip() else None

        return None
    except Exception:
        return None


# ══════════════════════════════════════════════
# FILE VIEWER ROUTES
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>/view/<int:file_id>')
@login_required
def view_file(project_id, file_id):
    """Serve file inline (for iframe/img preview)."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id=%s AND project_id=%s", (file_id, project_id))
        f = cursor.fetchone()
        conn.close()
        if not f:
            return 'File not found', 404
        path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
        if not os.path.exists(path):
            return 'File not on server', 404
        return send_file(path, as_attachment=False)
    except Exception as e:
        return str(e), 500


@app.route('/project/<int:project_id>/content/<int:file_id>')
@login_required
def file_text_content(project_id, file_id):
    """Return text content of a file as JSON (for text preview modal)."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id=%s AND project_id=%s", (file_id, project_id))
        f = cursor.fetchone()
        conn.close()
        if not f:
            return jsonify({'success': False, 'error': 'File not found'}), 404
        path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
        content = extract_file_text(path, f.get('file_type', ''))
        if content is None:
            return jsonify({'success': False, 'error': 'Preview unavailable for this file type.'})
        return jsonify({'success': True, 'content': content, 'filename': f['original_name']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════
# AI CHAT
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>/chat', methods=['POST'])
@login_required
def project_chat(project_id):
    """AI chat using Anthropic Claude — with full project file context."""
    if not ANTHROPIC_AVAILABLE:
        return jsonify({'success': False,
                        'error': 'Anthropic library not installed. Run: pip install anthropic'}), 500

    api_key = app.config.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return jsonify({'success': False,
                        'error': 'ANTHROPIC_API_KEY not set in config.py'}), 500

    data = request.get_json(silent=True) or {}
    user_message = data.get('message', '').strip()
    history = data.get('history', [])

    if not user_message:
        return jsonify({'success': False, 'error': 'Message is empty'}), 400

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE id=%s", (project_id,))
        project = cursor.fetchone()

        cursor.execute("""SELECT * FROM files WHERE project_id=%s
                          ORDER BY uploaded_at DESC LIMIT 15""", (project_id,))
        files = cursor.fetchall()
        conn.close()

        # Build file context
        file_context = ''
        for f in files:
            path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
            txt = extract_file_text(path, f.get('file_type', ''), max_chars=2500)
            if txt:
                file_context += f"\n\n--- {f['original_name']} ---\n{txt}"

        system = f"""You are a senior construction project manager and quantity surveyor assistant for VEKAS Construction.

Project: {project['name']}
Client: {project.get('client_name') or 'N/A'}
Status: {project['status']} | Priority: {project['priority']}
{('Uploaded Documents:' + file_context) if file_context else 'No readable documents uploaded yet.'}

Your expertise covers: project planning, cost estimation, Bill of Quantities (BOQ),
structural analysis, material take-offs, scheduling, and construction specifications.
Always be concise, professional, and data-driven. Use INR for costs."""

        msgs = [{'role': h['role'], 'content': h['content']} for h in history[-12:]]
        msgs.append({'role': 'user', 'content': user_message})

        client = _anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2048,
            system=system,
            messages=msgs
        )
        reply = resp.content[0].text

        conn = get_db()
        cursor = conn.cursor()
        log_activity(cursor, project_id, 'AI Chat',
                     f'"{user_message[:60]}"' + ('…' if len(user_message) > 60 else ''))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'response': reply})

    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower() or 'api_key' in err.lower():
            return jsonify({'success': False, 'error': 'Invalid Anthropic API key. Check config.py'}), 401
        return jsonify({'success': False, 'error': err}), 500


# ══════════════════════════════════════════════
# BOQ GENERATION
# ══════════════════════════════════════════════

@app.route('/project/<int:project_id>/generate_boq', methods=['POST'])
@login_required
def generate_boq(project_id):
    """Generate Bill of Quantities from project drawing documents."""
    if not ANTHROPIC_AVAILABLE:
        return jsonify({'success': False,
                        'error': 'Install anthropic: pip install anthropic'}), 500

    api_key = app.config.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'ANTHROPIC_API_KEY not set in config.py'}), 500

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE id=%s", (project_id,))
        project = cursor.fetchone()

        cursor.execute("""SELECT * FROM files WHERE project_id=%s
                          AND folder_type IN ('Drawing','Blueprint','Output')
                          ORDER BY uploaded_at DESC""", (project_id,))
        files = cursor.fetchall()
        conn.close()

        docs, analyzed = '', []
        for f in files:
            path = os.path.join(app.config['UPLOAD_FOLDER'], str(project_id), f['filename'])
            txt = extract_file_text(path, f.get('file_type', ''), max_chars=3500)
            if txt:
                docs += f"\n\n=== {f['original_name']} ===\n{txt}"
                analyzed.append(f['original_name'])

        document_section = (
            "Project Documents:\n" + docs
            if docs
            else "No readable documents — generate a standard residential BOQ template."
        )

        boq_prompt = f"""You are an expert Quantity Surveyor for VEKAS Construction (Madurai, India).

Project: {project['name']}
Client: {project.get('client_name') or 'N/A'}

{document_section}

Generate a comprehensive Bill of Quantities (BOQ) as a styled HTML table.
Include these sections:
1. Preliminary & General
2. Site Clearance & Earthwork
3. Foundation & Substructure
4. RCC Structural Work (Columns, Beams, Slabs)
5. Masonry (Brick/Block)
6. Roofing & Waterproofing
7. Doors, Windows & Glazing
8. Internal Plastering & Painting
9. Flooring & Tiling
10. External Works & Landscaping
11. Plumbing & Sanitary
12. Electrical & Lighting
13. Provisional Sums

Columns: Item No | Description | Unit | Qty | Rate (₹) | Amount (₹)

End with:
- Subtotal
- Overhead & Profit (15%)
- Contingency (5%)
- GST @ 18%
- GRAND TOTAL

Return ONLY the HTML (no markdown fences). Use these inline styles:
- Table: style="width:100%;border-collapse:collapse;font-family:sans-serif;font-size:14px"
- Section headers: style="background:#1E6C93;color:white;padding:10px;font-weight:bold"
- Alt rows: style="background:#f6f3f2"
- Total row: style="background:#212121;color:white;font-weight:bold;font-size:16px"
- TH: style="background:#005375;color:white;padding:8px;text-align:left"
- TD: style="padding:8px;border-bottom:1px solid #e5e2e1"
"""
        client = _anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4096,
            messages=[{'role': 'user', 'content': boq_prompt}]
        )
        boq_html = resp.content[0].text
        # Strip any accidental markdown fences
        boq_html = boq_html.replace('```html', '').replace('```', '').strip()

        conn = get_db()
        cursor = conn.cursor()
        log_activity(cursor, project_id, 'BOQ Generated',
                     f'Analyzed {len(analyzed)} document(s)')
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'boq_html': boq_html,
            'docs_analyzed': analyzed,
            'project_name': project['name'],
            'client_name': project.get('client_name') or ''
        })

    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower():
            return jsonify({'success': False, 'error': 'Invalid API key'}), 401
        return jsonify({'success': False, 'error': err}), 500


# ══════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
