from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session, jsonify
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
import io
import tempfile
import csv
import re
import zipfile
from urllib.parse import quote
import hashlib
import secrets
import time
from rapidfuzz import fuzz
import unicodedata
from werkzeug.utils import secure_filename

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    """Get current time in Indian Standard Time (IST)"""
    return datetime.now(IST)

def make_aware(dt):
    """Make a datetime object timezone-aware (IST) if it's naive"""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            # Try ISO first
            dt = datetime.fromisoformat(dt)
        except (ValueError, TypeError):
            # Fallbacks for common string formats that may be stored in older DBs
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
                try:
                    dt = datetime.strptime(dt, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt

def format_ist_datetime(dt):
    """Format datetime to IST string"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

# Import the core processing functions from the new module
from attendance_processing import (
    process_sessions_for_file, parse_datetime, write_excel
)

# Import database functions
from database import (
    init_db, log_file_processing, get_processing_summary,
    get_user_processing_stats, get_user, update_user,
    delete_user, get_all_users, ensure_superadmin_exists, search_users,
    create_batch, update_batch, delete_batch, get_batches,
    get_batch, add_student_to_batch, update_batch_student,
    delete_batch_student, get_batch_students,
    get_all_batch_students_with_batches,
    create_user as db_create_user,  # Import with alias to avoid conflict
    register_processed_file, get_processed_files, get_processed_file_by_path,
    mark_file_eligible_for_deletion, mark_file_manually_deleted,
    add_excluded_participant, remove_excluded_participant, get_excluded_participants,
    get_excluded_identifiers, bulk_add_excluded_participants, update_excluded_participant,
    get_files_eligible_for_auto_deletion, permanently_delete_old_records, grant_file_access, revoke_file_access,
    get_file_permissions, can_user_access_file,
    log_user_login, get_last_login, get_user_login_history, get_dashboard_stats, get_user_usage_summary,
    get_app_setting, set_app_setting, get_all_app_settings, create_app_setting, delete_app_setting,
    get_output_format_settings, set_output_format_settings, get_all_output_format_settings,
    log_activity, get_activity_logs, get_activity_log_count, delete_activity_logs, clear_all_activity_logs,
    get_app_output_format, set_app_output_format, get_all_app_output_formats
)

# Helper function to get app names
def get_app_names():
    """Get application names from settings"""
    try:
        return {
            'app1': get_app_setting('app1_name', 'Zoom Attendance Analyzer'),
            'app2': get_app_setting('app2_name', 'Intelligent Record Matcher'),
            'app3': get_app_setting('app3_name', 'Session Report Generator')
        }
    except Exception as e:
        print(f"Error fetching app names: {e}")
        return {
            'app1': 'Zoom Attendance Analyzer',
            'app2': 'Intelligent Record Matcher',
            'app3': 'Session Report Generator'
        }

app = Flask(__name__, static_url_path='/static', static_folder='static')
# SECURITY: Set FLASK_SECRET_KEY environment variable in production!
# Generate a secure key: python -c "import secrets; print(secrets.token_hex(32))"
secret_key = os.environ.get('FLASK_SECRET_KEY')
if not secret_key:
    import warnings
    warnings.warn("FLASK_SECRET_KEY not set! Using fallback key. Set environment variable for production!", UserWarning)
    secret_key = 'fallback-key-change-in-production-' + secrets.token_hex(16)
app.secret_key = secret_key
# Template auto-reload should be disabled in production for security and performance
# Only enable in development by setting FLASK_ENV=development
is_development = os.environ.get('FLASK_ENV', 'production').lower() == 'development'
app.config['TEMPLATES_AUTO_RELOAD'] = is_development
if not is_development:
    # In production, use template caching for better performance
    app.jinja_env.cache = {}
else:
    # In development, clear cache to force template recompile
    app.jinja_env.cache = {}

# Configure session settings
# Security: In production with HTTPS, SESSION_COOKIE_SECURE must be True
# For local development over HTTP, it can be False
is_production = os.environ.get('FLASK_ENV', 'production').lower() == 'production'
app.config['SESSION_COOKIE_SECURE'] = is_production  # True in production (HTTPS), False in development
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Prevent CSRF
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)  # Session expires after 24 hours
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Refresh session on each request

@app.before_request
def make_session_permanent():
    session.permanent = True  # Make session persistent

# Make get_remaining_time available to templates
@app.context_processor
def inject_remaining_time():
    return dict(get_remaining_time=get_remaining_time)

# Custom Jinja2 filter for formatting datetime strings
@app.template_filter('format_datetime')
def format_datetime_filter(s):
    """Format a datetime string for display and convert to IST."""
    dt = None
    if isinstance(s, str):
        try:
            # Attempt to parse the most common format first
            dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                # Fallback for other ISO-like formats
                dt = datetime.fromisoformat(s)
            except (ValueError, TypeError):
                return s  # Return original string if parsing fails
    elif isinstance(s, datetime):
        dt = s

    if dt:
        # Convert to IST (UTC+5:30)
        ist_dt = dt + timedelta(hours=5, minutes=30)
        return ist_dt.strftime('%Y-%m-%d %H:%M:%S')
    
    return s

# Directory for temporary files - use dedicated uploads folder instead of system temp
# This prevents OS-level temp cleanup and gives us more control
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# For backward compatibility, TEMP_DIR points to our uploads directory
TEMP_DIR = UPLOAD_DIR

# Path to main SQLite database (for backup/restore)
DB_PATH = os.path.join(os.path.dirname(__file__), 'attendancify.db')

# Periodic cleanup for temp files created by this app
LAST_CLEANUP = 0

def cleanup_temp_files(max_age_minutes: int = 120):
    """Remove temp files created by this app older than max_age_minutes.
    Files are identified by a 16-hex prefix followed by an underscore.
    This function excludes files that are registered in processed_files table,
    and also excludes files that are not yet eligible for deletion."""
    cutoff = time.time() - max_age_minutes * 60
    try:
        # Get all registered processed files to exclude from cleanup
        registered_files = get_processed_files(include_deleted=False)
        registered_paths = set()
        now = datetime.now()
        
        for f in registered_files:
            file_path = f['file_path']
            # Only exclude if file is not yet eligible for deletion
            if f['eligible_for_deletion_at']:
                try:
                    eligible_dt = datetime.strptime(f['eligible_for_deletion_at'], '%Y-%m-%d %H:%M:%S')
                    # If not yet eligible, exclude from cleanup
                    if eligible_dt > now:
                        registered_paths.add(file_path)
                except Exception:
                    # If we can't parse the date, exclude it to be safe
                    registered_paths.add(file_path)
            else:
                # If no eligibility time set, exclude it (still being processed)
                registered_paths.add(file_path)
        
        for name in os.listdir(TEMP_DIR):
            # Only target files that match our random-prefix pattern "<16hex>_..."
            if '_' in name and len(name.split('_', 1)[0]) == 16:
                path = os.path.join(TEMP_DIR, name)
                if os.path.isfile(path):
                    # Skip if file is registered and not yet eligible for deletion
                    if path in registered_paths:
                        continue
                    try:
                        if os.path.getmtime(path) < cutoff:
                            os.remove(path)
                    except OSError:
                        pass
    except Exception:
        pass

def cleanup_eligible_processed_files():
    """Auto-delete processed files that are eligible for deletion (15 minutes after eligibility time)"""
    try:
        eligible_files = get_files_eligible_for_auto_deletion()
        for file_record in eligible_files:
            file_path = file_record['file_path']
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    mark_file_manually_deleted(file_path)
                except OSError:
                    pass
    except Exception:
        pass

def cleanup_old_database_records():
    """Permanently remove database records for files deleted more than 30 days ago"""
    try:
        # Delete records older than 30 days (configurable)
        deleted_count = permanently_delete_old_records(days_old=30)
        if deleted_count > 0:
            print(f"Permanently removed {deleted_count} old deleted file records from database")
    except Exception as e:
        print(f"Error cleaning up old database records: {e}")

# Track last database cleanup (run less frequently)
LAST_DB_CLEANUP = 0

@app.before_request
def _periodic_cleanup():
    global LAST_CLEANUP, LAST_DB_CLEANUP
    now = time.time()
    # Run file cleanup roughly every 60 seconds
    if now - LAST_CLEANUP > 60:
        cleanup_temp_files()
        cleanup_eligible_processed_files()
        LAST_CLEANUP = now
    
    # Run database cleanup once per day (86400 seconds)
    if now - LAST_DB_CLEANUP > 86400:
        cleanup_old_database_records()
        LAST_DB_CLEANUP = now

# Configure upload settings
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# Initialize database and ensure superadmin exists
init_db()
ensure_superadmin_exists()

# ----------- Authentication Functions -----------
def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_password_hash, provided_password):
    """Verify a stored password hash against one provided by user"""
    return stored_password_hash == hashlib.sha256(provided_password.encode()).hexdigest()

@app.before_request
def check_session_validity():
    """Check session validity before each request"""
    # List of endpoints that don't require authentication
    public_endpoints = ['static', 'login', 'logout', 'index']
    
    # Don't check session for public endpoints
    if request.endpoint in public_endpoints:
        return
        
    try:
        if 'user_id' in session and 'logged_in' in session:
            # Update last activity
            session['last_activity'] = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
            
            # Get user information from database
            user = get_user(session['user_id'])
            if not user:
                session.clear()
                flash('User account no longer exists.')
                return redirect(url_for('login'))
            
            # Convert to dict for reliable access
            user_dict = dict(user) if hasattr(user, 'keys') else user
            
            # Refresh session permissions from database
            session['can_manage_roles'] = bool(user_dict.get('can_manage_roles', 0))
            session['can_manage_batch_matching'] = bool(user_dict.get('can_manage_batch_matching', 0))
            session['can_manage_batches'] = bool(user_dict.get('can_manage_batches', 0))
            session['can_access_processed_files'] = bool(user_dict.get('can_access_processed_files', 0))
            session['can_view_dashboard'] = bool(user_dict.get('can_view_dashboard', 0))
            
            # Check if it's superadmin or admin - they always have access (no expiration check)
            user_role = user_dict.get('role', '')
            if user_role in ['superadmin', 'admin']:
                return
                
            # For non-superadmin users, check expiration and password change requirement
            expires_at = make_aware(user_dict.get('expires_at'))
            if expires_at and datetime.now(IST) > expires_at:
                session.clear()
                flash('Account has expired.')
                return redirect(url_for('login'))
                
            # Redirect to force password change if required (except for superadmin)
            if user_dict.get('must_change_password', False) and request.endpoint != 'force_change_password':
                flash('You must change your password before continuing.', 'warning')
                return redirect(url_for('force_change_password'))
                
        elif request.endpoint not in public_endpoints:
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
            
    except Exception as e:
        print(f"Session validity check error: {str(e)}")
        session.clear()
        flash('Session error occurred. Please login again.')
        return redirect(url_for('login'))

def is_logged_in():
    """Check if user is logged in"""
    return 'user_id' in session and ('logged_in' in session and session['logged_in'])

def is_admin():
    """Check if the logged-in user is an admin, subsuperadmin, or superadmin"""
    if not is_logged_in():
        return False
    
    # Debug logging
    print(f"is_admin() - Session data: {dict(session)}")
    
    # Check session first
    if 'role' in session:
        print(f"is_admin() - Role from session: {session['role']}")
        return session['role'] in ['admin', 'superadmin', 'subsuperadmin']
    
    # Fallback to database check
    user = get_user(session['user_id'])
    if user:
        print(f"is_admin() - User from DB: {dict(user)}")
        if 'role' in user:
            # Update session with role from database
            session['role'] = user['role']
            return user['role'] in ['admin', 'superadmin', 'subsuperadmin']
    
    return False

def is_superadmin():
    """Check if the logged-in user is a superadmin"""
    if not is_logged_in():
        print("is_superadmin: User not logged in")
        return False
    
    # Always check the database to ensure the role is up-to-date
    user = get_user(session['user_id'])
    if not user:
        print("is_superadmin: User not found in database")
        return False
    
    # Convert to dict if it's a Row object
    user_dict = dict(user)
    is_super = user_dict.get('role') == 'superadmin'
    
    # Update session role if needed
    if is_super and session.get('role') != 'superadmin':
        session['role'] = 'superadmin'
        print(f"Updated session role to 'superadmin' for {session['user_id']}")
    
    print(f"is_superadmin check for {session['user_id']}: {is_super}")
    return is_super

def check_token_validity():
    """Check if user's token is still valid"""
    if not is_logged_in():
        return False
    
    user = get_user(session['user_id'])
    if not user:
        return False
    
    # Convert to dict for reliable access
    user_dict = dict(user) if hasattr(user, 'keys') else user
    
    # Superadmin, subsuperadmin, and admin always valid (no expiration)
    if user_dict.get('role') in ['superadmin', 'subsuperadmin', 'admin']:
        return True
    
    # Check if account has expired
    expires_at = make_aware(user_dict.get('expires_at'))
    if expires_at and datetime.now(IST) > expires_at:
        return False
    
    return True

def get_remaining_time(user_id):
    """Get remaining time for a user account"""
    user = get_user(user_id)
    if not user:
        return None
    
    # Convert sqlite3.Row to dict for reliable key access
    user_dict = dict(user) if hasattr(user, 'keys') else user
    
    expires_at_raw = user_dict.get('expires_at')
    if not expires_at_raw:
        return None
    
    expires_at = make_aware(expires_at_raw)
    if not expires_at:
        return None
    
    now = datetime.now(IST)
    
    if expires_at <= now:
        return "Expired"
    
    remaining = expires_at - now
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    if days > 0:
        return f"{days} days, {hours} hours"
    elif hours > 0:
        return f"{hours} hours, {minutes} minutes"
    else:
        return f"{minutes} minutes"

# ----------- Authentication Decorator -----------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in() or not check_token_validity():
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in() or not is_admin() or not check_token_validity():
            flash('Access denied. Admin privileges required.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def superadmin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in() or not is_superadmin() or not check_token_validity():
            flash('Access denied. Superadmin privileges required.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def subsuperadmin_required(f):
    """Allow superadmin or subsuperadmin access"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in() or not check_token_validity():
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
        
        user = get_user(session.get('user_id'))
        if user:
            user_dict = dict(user) if hasattr(user, 'keys') else user
            if user_dict.get('role') in ['superadmin', 'subsuperadmin']:
                return f(*args, **kwargs)
        
        flash('Access denied. Sub-Superadmin or Superadmin privileges required.')
        return redirect(url_for('login'))
    return decorated_function

def batch_manager_required(f):
    """Allow superadmin, admin, or any user with can_manage_batches permission."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_logged_in() or not check_token_validity():
            flash('Please log in to access this page.')
            return redirect(url_for('login'))
        # Superadmin and admin always allowed
        if is_superadmin() or is_admin():
            return f(*args, **kwargs)
        # Check can_manage_batches permission for regular users
        user = get_user(session.get('user_id'))
        if user:
            user_dict = dict(user) if hasattr(user, 'keys') else user
            if user_dict.get('can_manage_batches'):
                return f(*args, **kwargs)
        flash('Access denied. Batch management privileges required.')
        return redirect(url_for('index'))
    return decorated_function

# ----------- Authentication Routes -----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()  # Normalize email
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('login_advanced.html')
        
        user = get_user(email)
        
        if not user:
            flash('Invalid email or password.', 'error')
            return render_template('login_advanced.html')
        
        # Convert sqlite3.Row to dict if needed
        user_dict = dict(user) if hasattr(user, 'keys') else user
        
        # Verify password
        if not verify_password(user_dict.get('password_hash', ''), password):
            flash('Invalid email or password.', 'error')
            return render_template('login_advanced.html')
        
        # Check if account is expired
        expires_at = make_aware(user_dict.get('expires_at'))
        if expires_at and expires_at < datetime.now(IST):
            flash('This account has expired. Please contact an administrator.', 'error')
            return render_template('login_advanced.html')
        
        # Get IP address
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        if ip_address and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()
        
        # Log login with IP address
        log_user_login(email, ip_address)
        
        # Set up session
        session.clear()
        session['user_id'] = user_dict.get('email')
        session['logged_in'] = True
        session['role'] = user_dict.get('role', 'user')
        # Store basic profile info for display
        session['first_name'] = user_dict.get('first_name') or ''
        # Feature/permission flags
        session['can_manage_roles'] = bool(user_dict.get('can_manage_roles', 0))
        session['can_manage_batch_matching'] = bool(user_dict.get('can_manage_batch_matching', 0))
        session['can_manage_batches'] = bool(user_dict.get('can_manage_batches', 0))
        session['can_access_processed_files'] = bool(user_dict.get('can_access_processed_files', 0))
        session['can_view_dashboard'] = bool(user_dict.get('can_view_dashboard', 0))
        expires_at = make_aware(user_dict.get('expires_at'))
        if expires_at:
            session['expires_at_display'] = expires_at.strftime('%Y-%m-%d %H:%M')
        else:
            session['expires_at_display'] = ''
        session.permanent = True
        
        print("\n=== LOGIN SUCCESSFUL ===")
        print(f"User: {email}")
        print(f"Role from DB: {user_dict.get('role')}")
        print(f"Session data: {dict(session)}")
        print("======================\n")
        
        # Check if password needs to be changed
        if user_dict.get('must_change_password', False):
            flash('You must change your password on first login.', 'warning')
            return redirect(url_for('force_change_password'))
        
        flash('Login successful!', 'success')
        return redirect(url_for('index'))
    
    return render_template('login_advanced.html')

# Debug route - REMOVE IN PRODUCTION or restrict to superadmin only
@app.route('/debug/user')
@login_required
@superadmin_required  # Only superadmin can access debug routes
def debug_user():
    user = get_user(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    user_dict = dict(user)
    return jsonify({
        'email': user_dict.get('email'),
        'role': user_dict.get('role'),
        'session_role': session.get('role'),
        'is_superadmin': is_superadmin(),
        'is_admin': is_admin(),
        'session_data': dict(session)
    })

@app.route('/process_attendance_matching', methods=['POST'])
@login_required
def process_attendance_matching():
    """Process one or more attendance matching pairs.

    Supports:
    - File mode: each pair has its own master + raw file.
    - Batch mode: a single selected batch is matched against multiple raw files.
    - Auto-extract: automatically extract raw data from Attendance Generator output.
    """
    try:
        user_email = session.get('user_id')
        output_format = request.form.get('output_format', 'xlsx')
        pair_count = int(request.form.get('pair_count', 1))
        match_mode = request.form.get('match_mode', 'file')  # 'file' or 'batch'
        auto_extract = request.form.get('auto_extract') == '1'  # Auto-extract from Attendance Generator output

        output_files = []

        # Check if user can use batch matching
        db_user_row = get_user(user_email)
        db_user = dict(db_user_row) if db_user_row and hasattr(db_user_row, 'keys') else db_user_row
        can_use_batch = bool(db_user and (db_user.get('role') == 'superadmin' or db_user.get('can_use_batch_matching')))

        batch = None
        batch_students_data = None

        # If batch mode requested, prepare batch data once
        if match_mode == 'batch' and can_use_batch:
            batch_id_raw = request.form.get('batch_id')
            try:
                batch_id = int(batch_id_raw) if batch_id_raw else None
            except (TypeError, ValueError):
                batch_id = None

            if not batch_id:
                flash('Please select a batch for batch mode matching.', 'error')
                return redirect(url_for('index'))

            batch = get_batch(batch_id)
            if not batch:
                flash('Selected batch was not found.', 'error')
                return redirect(url_for('index'))

            students_rows = get_batch_students(batch_id)
            if not students_rows:
                flash('Selected batch has no students to match against.', 'error')
                return redirect(url_for('index'))

            batch_students_data = [
                {"Email": s['email'], "Participant Name": s['name']}
                for s in students_rows
            ]

        # Debug logging
        print(f"[Smart Matcher] Processing {pair_count} pairs, auto_extract={auto_extract}, match_mode={match_mode}, can_use_batch={can_use_batch}")
        
        # Process each pair according to mode
        for i in range(pair_count):
            raw_file = request.files.get(f'raw_file_{i}')
            if not raw_file or not raw_file.filename:
                print(f"[Smart Matcher] Pair {i}: No raw file uploaded, skipping")
                continue

            # Check per-pair master source (for Split View dashboard)
            pair_master_source = request.form.get(f'master_source_{i}', 'file')
            pair_batch_id_raw = request.form.get(f'batch_id_{i}')
            print(f"[Smart Matcher] Pair {i}: master_source={pair_master_source}, batch_id={pair_batch_id_raw}, raw_file={raw_file.filename}")
            
            # Determine if this pair uses batch mode
            use_batch_for_pair = False
            pair_batch = None
            pair_batch_students = None
            
            if pair_master_source == 'batch' and can_use_batch:
                # Per-pair batch mode
                try:
                    pair_batch_id = int(pair_batch_id_raw) if pair_batch_id_raw else None
                except (TypeError, ValueError):
                    pair_batch_id = None
                
                print(f"[Smart Matcher] Pair {i}: Using per-pair batch mode, batch_id={pair_batch_id}")
                
                if pair_batch_id:
                    pair_batch = get_batch(pair_batch_id)
                    if pair_batch:
                        students_rows = get_batch_students(pair_batch_id)
                        if students_rows:
                            pair_batch_students = [
                                {"Email": s['email'], "Participant Name": s['name']}
                                for s in students_rows
                            ]
                            use_batch_for_pair = True
                            print(f"[Smart Matcher] Pair {i}: Batch found with {len(pair_batch_students)} students")
                        else:
                            print(f"[Smart Matcher] Pair {i}: Batch has no students")
                    else:
                        print(f"[Smart Matcher] Pair {i}: Batch not found")
                else:
                    print(f"[Smart Matcher] Pair {i}: No batch_id provided for batch mode")
            elif match_mode == 'batch' and can_use_batch and batch and batch_students_data:
                # Global batch mode
                use_batch_for_pair = True
                pair_batch = batch
                pair_batch_students = batch_students_data

            # ----- Batch mode: use batch students as master -----
            if use_batch_for_pair and pair_batch and pair_batch_students:
                try:
                    suffix = secrets.token_hex(8)
                    raw_filename = f"{suffix}_" + secure_filename(raw_file.filename)
                    raw_path = os.path.join(TEMP_DIR, raw_filename)
                    raw_file.save(raw_path)
                    
                    # Auto-extract: run Excel Extractor on the raw file first
                    if auto_extract:
                        try:
                            extracted_df = extract_raw_from_excel(raw_path)
                            extracted_filename = f"{suffix}_extracted_{secure_filename(raw_file.filename)}"
                            extracted_path = os.path.join(TEMP_DIR, extracted_filename.replace('.xlsx', '.csv').replace('.xls', '.csv'))
                            extracted_df.to_csv(extracted_path, index=False)
                            raw_path = extracted_path  # Use extracted file for matching
                        except Exception as e:
                            flash(f'Auto-extract failed for {raw_file.filename}: {str(e)}. Using original file.', 'warning')

                    start_time = time.time()
                    output_path = match_and_write_from_students(pair_batch['name'], pair_batch_students, raw_path, output_format)
                    processing_time = time.time() - start_time

                    if output_path and os.path.exists(output_path):
                        output_filename = os.path.basename(output_path)
                        # Register processed file in database immediately (not eligible for deletion yet)
                        # This protects the file during the entire workflow
                        register_processed_file(
                            file_path=output_path,
                            file_name=output_filename,
                            user_email=user_email,
                            processing_type='attendance_matching',
                            eligible_for_deletion_at=None  # Not eligible yet - will be set after completion
                        )
                        output_files.append({'path': output_path, 'name': output_filename})

                    raw_file_size = os.path.getsize(raw_path) if os.path.exists(raw_path) else 0
                    log_file_processing(
                        user_email=user_email,
                        file_name=f"batch:{pair_batch['name']}",
                        processing_type='attendance_matching_batch',
                        file_size=raw_file_size,
                        processing_time=processing_time
                    )
                except Exception as e:
                    print(f"Batch mode matching error for pair {i}: {e}")
                    continue

            # ----- File mode: per-pair master + raw -----
            else:
                print(f"[Smart Matcher] Pair {i}: Trying file mode (batch mode not used)")
                master_file = request.files.get(f'master_file_{i}')
                if not master_file or not master_file.filename:
                    print(f"[Smart Matcher] Pair {i}: No master file uploaded for file mode, skipping")
                    continue

                suffix = secrets.token_hex(8)
                master_filename = f"{suffix}_" + secure_filename(master_file.filename)
                raw_filename = f"{suffix}_" + secure_filename(raw_file.filename)
                master_path = os.path.join(TEMP_DIR, master_filename)
                raw_path = os.path.join(TEMP_DIR, raw_filename)
                master_file.save(master_path)
                raw_file.save(raw_path)
                
                # Auto-extract: run Excel Extractor on the raw file first
                if auto_extract:
                    try:
                        extracted_df = extract_raw_from_excel(raw_path)
                        extracted_filename = f"{suffix}_extracted_{secure_filename(raw_file.filename)}"
                        extracted_path = os.path.join(TEMP_DIR, extracted_filename.replace('.xlsx', '.csv').replace('.xls', '.csv'))
                        extracted_df.to_csv(extracted_path, index=False)
                        raw_path = extracted_path  # Use extracted file for matching
                    except Exception as e:
                        flash(f'Auto-extract failed for {raw_file.filename}: {str(e)}. Using original file.', 'warning')

                start_time = time.time()
                output_path = match_and_write(master_path, raw_path, output_format)
                processing_time = time.time() - start_time

                output_filename = os.path.basename(output_path)
                # Register processed file in database immediately (not eligible for deletion yet)
                # This protects the file during the entire workflow
                register_processed_file(
                    file_path=output_path,
                    file_name=output_filename,
                    user_email=user_email,
                    processing_type='attendance_matching',
                    eligible_for_deletion_at=None  # Not eligible yet - will be set after completion
                )
                output_files.append({'path': output_path, 'name': output_filename})

                master_file_size = os.path.getsize(master_path) if os.path.exists(master_path) else 0
                raw_file_size = os.path.getsize(raw_path) if os.path.exists(raw_path) else 0
                log_file_processing(
                    user_email=user_email,
                    file_name=master_filename,
                    processing_type='attendance_matching_master',
                    file_size=master_file_size,
                    processing_time=processing_time
                )
                log_file_processing(
                    user_email=user_email,
                    file_name=raw_filename,
                    processing_type='attendance_matching_raw',
                    file_size=raw_file_size,
                    processing_time=processing_time
                )

        if not output_files:
            # Check if request is AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': f'No valid file pairs were processed. Pairs requested: {pair_count}'}), 400
            flash(f'No valid file pairs were processed. Please ensure each pair has a master source (file or batch) and a raw file.')
            return redirect(url_for('index'))

        # Debug logging
        print(f"Successfully processed {len(output_files)} file pairs")
        print(f"Output files: {output_files}")

        session['matching_output_files'] = output_files
        
        # Mark all files as eligible for deletion after 2 hours from now
        # (Files are already registered above, but we ensure eligibility time is set)
        eligible_time = (datetime.now() + timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
        for file_info in output_files:
            mark_file_eligible_for_deletion(file_info['path'], eligible_time)

        # Check if request is AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # For AJAX requests, return JSON with download URL
            if len(output_files) == 1:
                download_url = url_for('download_attendance_matching', file=output_files[0]['name'])
            else:
                download_url = url_for('download_attendance_matching')
            return jsonify({'success': True, 'download_url': download_url})

        return redirect(url_for('download_attendance_matching'))

    except Exception as e:
        error_message = f'Error processing files: {str(e)}'
        print(f"Error in process_attendance_matching: {error_message}")
        # Check if request is AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error_message}), 500
        flash(error_message)
        return redirect(url_for('index'))

@app.route('/force_change_password', methods=['GET', 'POST'])
@login_required
def force_change_password():
    user_row = get_user(session['user_id'])
    user = dict(user_row) if user_row is not None and hasattr(user_row, 'keys') else user_row
    
    # Check if password change is still required
    if not user or not user.get('must_change_password', False):
        # If not required, redirect to index
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # Verify current password
        if not user or not verify_password(user['password_hash'], current_password):
            flash('Current password is incorrect.', 'error')
            return render_template('force_change_password.html')
        
        # Check if new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return render_template('force_change_password.html')
        
        # Check password length
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('force_change_password.html')
        
        # Update password
        update_user(session['user_id'], 
                   password_hash=hash_password(new_password),
                   must_change_password=False,
                   password_plain=new_password if user.get('role') == 'superadmin' else '[hidden]')
        
        # Remove force change flag from user data
        flash('Password changed successfully! You can now continue using the application.', 'success')
        return redirect(url_for('index'))
    
    return render_template('force_change_password.html')

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        user = get_user(session['user_id'])
        
        # Verify current password
        if not user or not verify_password(user['password_hash'], current_password):
            flash('Current password is incorrect.')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400
            return render_template('change_password.html')
        
        # Check if new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match.')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'New passwords do not match.'}), 400
        
        # Update password
        update_user(session['user_id'], password_hash=hash_password(new_password))
        flash('Password changed successfully.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Password changed successfully.'})
        return redirect(url_for('index'))
    
    return render_template('change_password.html')

@app.route('/admin/create_user', methods=['GET', 'POST'])
@admin_required
def create_user_route():
    if request.method == 'POST':
        try:
            email = request.form.get('email', '').strip().lower()  # Normalize email
            password = request.form.get('password', '').strip()
            role = request.form.get('role', 'user').strip().lower()
            expires_at = request.form.get('expires_at', '').strip()
            first_name = request.form.get('first_name', '').strip() or None
            last_name = request.form.get('last_name', '').strip() or None
            
            # Basic validation
            if not email or '@' not in email:
                flash('Please enter a valid email address.', 'error')
                return render_template('create_user.html', show_navigation=True)
                
            if len(password) < 8:
                flash('Password must be at least 8 characters long.', 'error')
                return render_template('create_user.html', show_navigation=True)
            
            # Role validation
            current_user_role = session.get('role', 'user')
            valid_roles = ['user', 'admin', 'superadmin', 'subsuperadmin']
            if role not in valid_roles:
                flash(f'Invalid role specified. Valid roles are: {", ".join(valid_roles)}', 'error')
                return redirect(url_for('admin_panel'))
            
            if current_user_role == 'admin' and role in ['admin', 'superadmin', 'subsuperadmin']:
                flash('Admins cannot create other admins, superadmins, or subsuperadmins. Only superadmins can create these roles.', 'error')
                return redirect(url_for('admin_panel'))
            
            if current_user_role == 'subsuperadmin' and role in ['superadmin', 'subsuperadmin']:
                flash('Subsuperadmins cannot create superadmins or other subsuperadmins.', 'error')
                return redirect(url_for('admin_panel'))
            
            # Check if user already exists
            if get_user(email):
                flash('A user with this email already exists.', 'error')
                return render_template('create_user.html', show_navigation=True)
            
            # Handle expiration date
            expires_at_datetime = None
            if expires_at:
                try:
                    expires_at_datetime = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M')
                    # Make it timezone-aware for comparison
                    expires_at_datetime = expires_at_datetime.replace(tzinfo=IST)
                    if expires_at_datetime < datetime.now(IST):
                        flash('Expiration date cannot be in the past.', 'error')
                        return render_template('create_user.html', show_navigation=True)
                except ValueError:
                    flash('Invalid expiration date format. Please use the date picker.', 'error')
                    return render_template('create_user.html', show_navigation=True)
            
            # Hash the password
            password_hash = hash_password(password)

            # Create the user, recording who created it
            creator_email = session.get('user_id')
            db_create_user(
                email=email,
                password_hash=password_hash,
                role=role,
                expires_at=expires_at_datetime,
                must_change_password=True,  # Force password change on first login
                password_plain=password if role == 'superadmin' else None,  # Only store plaintext for superadmin
                first_name=first_name,
                last_name=last_name,
                created_by=creator_email
            )
            
            flash('User created successfully. They will be required to change password on first login.', 'success')
            return redirect(url_for('admin_panel'))
            
        except Exception as e:
            flash(f'Error creating user: {str(e)}', 'error')
            print(f"Error in create_user_route: {str(e)}")
            import traceback
            traceback.print_exc()
            return render_template('create_user.html', show_navigation=True)
    
    # For GET request, show the form
    return render_template('create_user.html', show_navigation=True)

@app.route('/admin')
@admin_required
def admin_panel():
    try:
        # Get list of all users except the superadmin from database
        db_users = get_all_users()
        user_list = []
        
        for user in db_users:
            if user['email'] != 'superadmin@attendancify.com':  # Don't show the superadmin
                # Convert sqlite3.Row to dict if needed
                user_dict = dict(user) if hasattr(user, 'keys') else user
                
                # Ensure timestamps are in the correct format
                created_at = user_dict.get('created_at')
                expires_at = user_dict.get('expires_at')
                
                if created_at and isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at)
                    except (ValueError, TypeError):
                        created_at = None
                
                if expires_at and isinstance(expires_at, str):
                    try:
                        expires_at = datetime.fromisoformat(expires_at)
                    except (ValueError, TypeError):
                        expires_at = None
                
                # Get remaining time for the user
                remaining_time = None
                if expires_at and isinstance(expires_at, datetime):
                    # Make expires_at timezone-aware if it's naive
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=IST)
                    now = datetime.now(IST)
                    remaining = expires_at - now
                    if remaining.total_seconds() > 0:
                        remaining_time = str(remaining).split('.')[0]  # Remove microseconds
                
                user_list.append({
                    'email': user_dict.get('email'),
                    'role': user_dict.get('role', 'user'),
                    'created_at': created_at,
                    'expires_at': expires_at,
                    'must_change_password': user_dict.get('must_change_password', False),
                    'remaining_time': remaining_time,
                    'can_use_batch_matching': user_dict.get('can_use_batch_matching', 0),
                    'created_by': user_dict.get('created_by'),
                })
        
        # Get user usage statistics for superadmin
        user_stats = {}
        if is_superadmin():
            # Get processing summary for all users
            processing_summary = get_processing_summary()
            # Convert to a dictionary for easier access in the template
            for summary in processing_summary:
                user_stats[summary['user_email']] = {
                    'total_files_processed': summary['total_files_processed'],
                    'total_file_size': summary['total_file_size'],
                    'avg_processing_time': summary['avg_processing_time'],
                    'first_processing': summary['first_processing'],
                    'last_processing': summary['last_processing']
                }
        
        return render_template('admin_panel.html', 
                            users=user_list, 
                            user_stats=user_stats,
                            show_navigation=True)
                            
    except Exception as e:
        flash(f'Error loading admin panel: {str(e)}')
        print(f"Error in admin_panel: {str(e)}")
        return render_template('admin_panel.html', 
                            users=[], 
                            user_stats={},
                            show_navigation=True)


@app.route('/admin/update_user_flags/<user_id>', methods=['POST'])
@superadmin_required
def update_user_flags(user_id):
    """Update per-user feature flags such as can_use_batch_matching (superadmin only)."""
    can_use_batch_matching = 1 if request.form.get('can_use_batch_matching') == '1' else 0
    try:
        update_user(user_id, can_use_batch_matching=can_use_batch_matching)
        flash('User feature flags updated.', 'success')
    except Exception as e:
        flash(f'Error updating user flags: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_user/<user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = get_user(user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('admin_panel'))
    # Ensure we have a plain dict for safe access
    user_dict = dict(user) if hasattr(user, 'keys') else user

    # Enforce that admins can only edit users they created and can never touch superadmins
    current_role = session.get('role')
    current_email = session.get('user_id')
    target_role = user_dict.get('role')
    target_creator = user_dict.get('created_by')

    # Superadmin safety: nobody except superadmin can ever edit a superadmin account
    if target_role == 'superadmin' and current_role != 'superadmin':
        flash('Only superadmin can edit superadmin accounts.')
        return redirect(url_for('admin_panel'))

    # Admins are restricted to editing only users they created
    if current_role == 'admin' and target_creator and target_creator != current_email:
        flash('Admins can only edit users they have created.')
        return redirect(url_for('admin_panel'))
    # Normalize expires_at to a datetime object if it's a string
    expires_at_value = user_dict.get('expires_at') if isinstance(user_dict, dict) else None
    if expires_at_value and isinstance(expires_at_value, str):
        try:
            from datetime import datetime
            user_dict['expires_at'] = datetime.fromisoformat(expires_at_value)
        except (ValueError, TypeError):
            user_dict['expires_at'] = None
    
    if request.method == 'POST':
        # Only admin or superadmin can edit users (already enforced by decorator)
        if session.get('role') not in ['admin', 'superadmin']:
            flash('Only admins can edit users.')
            return redirect(url_for('admin_panel'))

        # Update user data
        update_data = {}
        if 'first_name' in request.form:
            update_data['first_name'] = request.form['first_name'].strip() or None
        if 'last_name' in request.form:
            update_data['last_name'] = request.form['last_name'].strip() or None
        if 'role' in request.form:
            requested_role = request.form['role']
            current_role = session.get('role')
            can_manage_roles_flag = bool(session.get('can_manage_roles'))
            # Only superadmin, or admins explicitly allowed, may change roles
            if current_role == 'admin' and not can_manage_roles_flag:
                flash('You are not allowed to change user roles.')
                return render_template('edit_user.html', user=user_dict, user_id=user_id, show_navigation=True)
            # Admins are not allowed to promote anyone to superadmin or modify superadmin role
            if current_role == 'admin' and requested_role == 'superadmin':
                flash('Admins are not allowed to assign the superadmin role.')
                return render_template('edit_user.html', user=user_dict, user_id=user_id, show_navigation=True)
            # Extra safety: never allow non-superadmin to change an existing superadmin
            if target_role == 'superadmin' and current_role != 'superadmin':
                flash('Only superadmin can change superadmin role.')
                return redirect(url_for('admin_panel'))
            update_data['role'] = requested_role
        
        if 'expires_at' in request.form:
            expires_at = request.form['expires_at']
            update_data['expires_at'] = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M') if expires_at else None
        
        # Handle batch matching permission (only for superadmin or admins explicitly allowed)
        can_manage_batch_flag = bool(session.get('can_manage_batch_matching'))
        if session.get('role') == 'superadmin' or (session.get('role') == 'admin' and can_manage_batch_flag):
            update_data['can_use_batch_matching'] = 1 if 'can_use_batch_matching' in request.form else 0
        
        # Handle email change
        if 'email' in request.form and request.form['email'] != user_id:
            new_email = request.form['email']
            if get_user(new_email):
                flash('Email already exists.')
                return render_template('edit_user.html', user=user_dict, user_id=user_id, show_navigation=True)
            # Create new user with updated email and delete old one
            update_data['email'] = new_email
            db_create_user(
                email=new_email, 
                password_hash=user_dict['password_hash'], 
                role=user_dict['role'], 
                expires_at=user_dict.get('expires_at'), 
                must_change_password=user_dict.get('must_change_password', False), 
                password_plain=user_dict.get('password_plain'),
                first_name=update_data.get('first_name', user_dict.get('first_name')),
                last_name=update_data.get('last_name', user_dict.get('last_name'))
            )
            delete_user(user_id)
            flash('User email updated successfully.')
            return redirect(url_for('edit_user', user_id=new_email))
        
        if session.get('role') == 'superadmin':
            # Superadmin can also update per-admin management flags for this user
            can_manage_roles_val = 1 if request.form.get('can_manage_roles') == '1' else 0
            can_manage_batch_val = 1 if request.form.get('can_manage_batch_matching') == '1' else 0
            can_manage_batches_val = 1 if request.form.get('can_manage_batches') == '1' else 0
            can_access_processed_files_val = 1 if request.form.get('can_access_processed_files') == '1' else 0
            can_view_dashboard_val = 1 if request.form.get('can_view_dashboard') == '1' else 0
            update_data['can_manage_roles'] = can_manage_roles_val
            update_data['can_manage_batch_matching'] = can_manage_batch_val
            update_data['can_manage_batches'] = can_manage_batches_val
            update_data['can_access_processed_files'] = can_access_processed_files_val
            update_data['can_view_dashboard'] = can_view_dashboard_val

        if update_data:
            update_user(user_id, **update_data)
        
        flash('User updated successfully.')
        return redirect(url_for('admin_panel'))
    
    return render_template('edit_user.html', user=user_dict, user_id=user_id, show_navigation=True)

@app.route('/admin/view_password/<user_id>')
@superadmin_required
def view_user_password(user_id):
    # Feature retired for security. Keep route to avoid 404s for stale clients.
    return jsonify({'success': False, 'message': 'Password viewing is disabled'}), 404

@app.route('/admin/change_password/<user_id>', methods=['POST'])
@admin_required
def admin_change_password(user_id):
    # Only superadmin and admin can change passwords
    if session.get('role') not in ['admin', 'superadmin', 'subsuperadmin']:
        flash('Access denied.')
        return redirect(url_for('admin_panel'))
    
    user = get_user(user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('admin_panel'))
    
    new_password = request.form.get('new_password')
    if not new_password:
        flash('New password is required.')
        return redirect(url_for('admin_panel'))
    
    # Update password
    update_user(user_id, password_hash=hash_password(new_password))
    
    # Log the activity
    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
    log_activity(session.get('user_id'), 'password_change', f'Changed password for user: {user_id}', ip_address)
    
    flash(f'Password for {user_id} changed successfully.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<user_id>', methods=['POST'])
@superadmin_required
def delete_user_route(user_id):
    """Delete a user - Only superadmin can delete users"""
    try:
        # Prevent deleting superadmin accounts
        user = get_user(user_id)
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_panel'))
        
        user_dict = dict(user) if hasattr(user, 'keys') else user
        if user_dict.get('role') == 'superadmin':
            flash('Cannot delete superadmin accounts.', 'error')
            return redirect(url_for('admin_panel'))
        
        # Log the deletion
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'user_deletion', f'Deleted user: {user_id}', ip_address)
        
        # Delete the user
        delete_user(user_id)
        flash(f'User {user_id} deleted successfully.', 'success')
        
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')
        print(f"Error in delete_user_route: {str(e)}")
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/hide_user/<user_id>', methods=['POST'])
@superadmin_required
def hide_user_route(user_id):
    """Hide a user - User can still login but activity hidden from dashboard"""
    try:
        user = get_user(user_id)
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_panel'))
        
        user_dict = dict(user) if hasattr(user, 'keys') else user
        if user_dict.get('role') == 'superadmin':
            flash('Cannot hide superadmin accounts.', 'error')
            return redirect(url_for('admin_panel'))
        
        # Hide the user
        update_user(user_id, hidden=1)
        
        # Log the action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'user_hidden', f'Hidden user: {user_id}', ip_address)
        
        flash(f'User {user_id} hidden successfully. They can still login but their activity is hidden.', 'success')
        
    except Exception as e:
        flash(f'Error hiding user: {str(e)}', 'error')
        print(f"Error in hide_user_route: {str(e)}")
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/unhide_user/<user_id>', methods=['POST'])
@superadmin_required
def unhide_user_route(user_id):
    """Unhide a user - Show their activity again"""
    try:
        user = get_user(user_id)
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_panel'))
        
        # Protect superadmin accounts from being toggled by mistake
        user_dict = dict(user) if hasattr(user, 'keys') else user
        if user_dict.get('role') == 'superadmin':
            flash('Cannot unhide superadmin accounts via this action.', 'error')
            return redirect(url_for('admin_panel'))
        
        # Unhide the user
        update_user(user_id, hidden=0)
        
        # Log the action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'user_unhidden', f'Unhidden user: {user_id}', ip_address)
        
        flash(f'User {user_id} unhidden successfully. Their activity is now visible.', 'success')
        
    except Exception as e:
        flash(f'Error unhiding user: {str(e)}', 'error')
        print(f"Error in unhide_user_route: {str(e)}")
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/view_hidden_users')
@superadmin_required
def view_hidden_users():
    """View all hidden users"""
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE hidden = 1 ORDER BY created_at DESC')
            hidden_users = cursor.fetchall()
            cursor.close()
        finally:
            conn.close()
        
        return render_template(
            'hidden_users.html',
            hidden_users=hidden_users,
            show_navigation=True
        )
    except Exception as e:
        flash(f'Error viewing hidden users: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))

@app.route('/admin/file_processing_stats')
@superadmin_required
def file_processing_stats():
    """Display file processing statistics for all users"""
    # Get processing summary
    processing_summary = get_processing_summary()
    
    # Get detailed logs
    detailed_logs = get_user_processing_stats()
    
    return render_template('file_processing_stats.html', 
                         processing_summary=processing_summary,
                         detailed_logs=detailed_logs,
                         show_navigation=True)


@app.route('/admin/backup')
@superadmin_required
def download_backup():
    """Download a full SQLite database backup (superadmin only)."""
    if not os.path.exists(DB_PATH):
        flash('Database file not found for backup.', 'error')
        return redirect(url_for('admin_panel'))

    backup_name = f"attendancify_backup_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=backup_name)


@app.route('/admin/restore', methods=['POST'])
@superadmin_required
def restore_backup():
    """Restore the SQLite database from an uploaded backup (superadmin only)."""
    file = request.files.get('backup_file')
    if not file or not file.filename:
        flash('Please select a backup file to restore.', 'error')
        return redirect(url_for('admin_panel'))

    try:
        filename = secure_filename(file.filename)
        temp_path = os.path.join(TEMP_DIR, f"{secrets.token_hex(8)}_{filename}")
        file.save(temp_path)

        # Optional: basic sanity check for SQLite file header
        try:
            with open(temp_path, 'rb') as f:
                header = f.read(16)
            if not header.startswith(b'SQLite format 3'):
                flash('Uploaded file does not look like a valid SQLite backup.', 'error')
                os.remove(temp_path)
                return redirect(url_for('admin_panel'))
        except Exception:
            pass

        # Replace current DB with uploaded backup
        os.replace(temp_path, DB_PATH)
        flash('Database restored successfully from backup.', 'success')
    except Exception as e:
        flash(f'Error restoring backup: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))


# ----------- Batch Management (Admin, Superadmin, or users with can_manage_batches) -----------

@app.route('/admin/batches')
@batch_manager_required
def manage_batches():
    """List all batches and optionally show a selected batch's students."""
    batches = get_batches()
    batch_counts = {}
    batch_students = {}
    for b in batches:
        students = get_batch_students(b['id'])
        batch_counts[b['id']] = len(students)
        batch_students[b['id']] = students

    # Determine which batch should be selected (if any)
    selected_batch = None
    selected_id = request.args.get('batch_id', type=int)
    if selected_id:
        for b in batches:
            if b['id'] == selected_id:
                selected_batch = b
                break

    return render_template(
        'batches.html',
        batches=batches,
        batch_counts=batch_counts,
        batch_students=batch_students,
        selected_batch=selected_batch,
        show_navigation=True
    )


@app.route('/admin/batches/create', methods=['GET', 'POST'])
@batch_manager_required
def create_batch_route():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        if not name:
            flash('Batch name is required.', 'error')
            return redirect(url_for('create_batch_route'))
        try:
            create_batch(name, description, session.get('user_id', 'superadmin@attendancify.com'))
            flash('Batch created successfully.', 'success')
            return redirect(url_for('manage_batches'))
        except Exception as e:
            flash(f'Error creating batch: {str(e)}', 'error')
            return redirect(url_for('create_batch_route'))
    return render_template('simple_form.html',
                           title='Create Batch',
                           form_action=url_for('create_batch_route'),
                           fields=[
                               {'name': 'name', 'label': 'Batch Name', 'type': 'text', 'required': True},
                               {'name': 'description', 'label': 'Description', 'type': 'text', 'required': False},
                           ],
                           show_navigation=True)


@app.route('/admin/batches/<int:batch_id>/edit', methods=['GET', 'POST'])
@batch_manager_required
def edit_batch_route(batch_id):
    batch = get_batch(batch_id)
    if not batch:
        flash('Batch not found.', 'error')
        return redirect(url_for('manage_batches'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        if not name:
            flash('Batch name is required.', 'error')
            return redirect(url_for('edit_batch_route', batch_id=batch_id))
        try:
            update_batch(batch_id, name=name, description=description)
            flash('Batch updated successfully.', 'success')
        except Exception as e:
            flash(f'Error updating batch: {str(e)}', 'error')
        return redirect(url_for('manage_batches', batch_id=batch_id))
    return render_template('simple_form.html',
                           title='Edit Batch',
                           form_action=url_for('edit_batch_route', batch_id=batch_id),
                           fields=[
                               {'name': 'name', 'label': 'Batch Name', 'type': 'text', 'required': True, 'value': batch['name']},
                               {'name': 'description', 'label': 'Description', 'type': 'text', 'required': False, 'value': batch['description']},
                           ],
                           show_navigation=True)


@app.route('/admin/batches/<int:batch_id>/delete', methods=['POST'])
@batch_manager_required
def delete_batch_route(batch_id):
    try:
        delete_batch(batch_id)
        flash('Batch deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting batch: {str(e)}', 'error')
    return redirect(url_for('manage_batches'))


@app.route('/admin/batches/<int:batch_id>/upload_students', methods=['POST'])
@batch_manager_required
def upload_batch_students(batch_id):
    batch = get_batch(batch_id)
    if not batch:
        flash('Batch not found.', 'error')
        return redirect(url_for('manage_batches'))
    file = request.files.get('students_file')
    replace = request.form.get('replace') == '1'
    if not file or not file.filename:
        flash('Please select a file to upload.', 'error')
        return redirect(url_for('manage_batches', batch_id=batch_id))
    try:
        # Read CSV or Excel into DataFrame
        filename = secure_filename(file.filename)
        temp_path = os.path.join(TEMP_DIR, f"{secrets.token_hex(8)}_{filename}")
        file.save(temp_path)
        if temp_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(temp_path)
        else:
            df = pd.read_csv(temp_path)
        df.columns = df.columns.str.strip()
        if 'Name' not in df.columns or 'Email' not in df.columns:
            flash('Upload file must contain columns "Name" and "Email".', 'error')
            return redirect(url_for('manage_batches', batch_id=batch_id))
        if replace:
            # Delete existing students
            existing = get_batch_students(batch_id)
            for s in existing:
                delete_batch_student(s['id'])
        # Insert students
        for _, row in df.iterrows():
            name = str(row['Name']).strip()
            email = str(row['Email']).strip().lower()
            if not name or not email:
                continue
            add_student_to_batch(batch_id, name, email)
        flash('Students uploaded successfully.', 'success')
    except Exception as e:
        flash(f'Error uploading students: {str(e)}', 'error')
    return redirect(url_for('manage_batches', batch_id=batch_id))


@app.route('/admin/batches/<int:batch_id>/students/<int:student_id>/delete', methods=['POST'])
@batch_manager_required
def delete_batch_student_route(batch_id, student_id):
    try:
        delete_batch_student(student_id)
        flash('Student deleted from batch.', 'success')
    except Exception as e:
        flash(f'Error deleting student: {str(e)}', 'error')
    return redirect(url_for('manage_batches', batch_id=batch_id))


@app.route('/admin/batches/<int:batch_id>/students/<int:student_id>/edit', methods=['POST'])
@batch_manager_required
def edit_batch_student_route(batch_id, student_id):
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    if not name or not email:
        flash('Name and Email are required.', 'error')
        return redirect(url_for('manage_batches', batch_id=batch_id))
    try:
        update_batch_student(student_id, name=name, email=email)
        flash('Student updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating student: {str(e)}', 'error')
    return redirect(url_for('manage_batches', batch_id=batch_id))


@app.route('/admin/batches/<int:batch_id>/students/add', methods=['POST'])
@batch_manager_required
def add_batch_student_manual(batch_id):
    """Allow superadmin to add a single student manually to a batch."""
    batch = get_batch(batch_id)
    if not batch:
        flash('Batch not found.', 'error')
        return redirect(url_for('manage_batches'))

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    if not name or not email:
        flash('Name and Email are required to add a student.', 'error')
        return redirect(url_for('manage_batches', batch_id=batch_id))

    try:
        add_student_to_batch(batch_id, name, email)
        flash('Student added successfully.', 'success')
    except Exception as e:
        flash(f'Error adding student: {str(e)}', 'error')
    return redirect(url_for('manage_batches', batch_id=batch_id))


@app.route('/admin/batches/download_template')
@batch_manager_required
def download_batch_template():
    """Download a simple CSV template for batch student upload (Name,Email)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Name', 'Email'])
    writer.writerow(['John Doe', 'john.doe@example.com'])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name='batch_students_template.csv', mimetype='text/csv')


@app.route('/admin/batches/<int:batch_id>/download')
@batch_manager_required
def download_batch_students(batch_id):
    batch = get_batch(batch_id)
    if not batch:
        flash('Batch not found.', 'error')
        return redirect(url_for('manage_batches'))
    students = get_batch_students(batch_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Name', 'Email'])
    for s in students:
        writer.writerow([s['name'], s['email']])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    mem.seek(0)
    filename = f"batch_{batch['name']}_students.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype='text/csv')


@app.route('/admin/batches/download_all')
@batch_manager_required
def download_all_batches_students():
    rows = get_all_batch_students_with_batches()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['BatchName', 'Name', 'Email'])
    for r in rows:
        writer.writerow([r['batch_name'], r['student_name'], r['student_email']])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name='all_batches_students.csv', mimetype='text/csv')


@app.route('/admin/batch_student_search')
@batch_manager_required
def batch_student_search_api():
    """Search batch students by name or email and return suggestions with batch info."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    # Simple search over batch_students joined with batches
    from database import get_all_batch_students_with_batches
    try:
        pattern = q.lower()
        rows = get_all_batch_students_with_batches()
        suggestions = []
        for r in rows:
            d = dict(r) if hasattr(r, 'keys') else r
            name = d.get('student_name', '') or ''
            email = d.get('student_email', '') or ''
            if pattern in name.lower() or pattern in email.lower():
                suggestions.append({
                    'student_id': d.get('student_id'),
                    'name': name,
                    'email': email,
                    'batch_id': d.get('batch_id'),
                    'batch_name': d.get('batch_name'),
                })
            if len(suggestions) >= 20:
                break
        return jsonify(suggestions)
    except Exception as e:
        print(f"batch_student_search_api error: {e}")
        return jsonify([]), 500


@app.route('/admin/batches/download_bulk_template')
@batch_manager_required
def download_batches_bulk_template():
    """Template for bulk batch + students upload (BatchName,Name,Email)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['BatchName', 'Name', 'Email'])
    writer.writerow(['Batch A 2025', 'John Doe', 'john.doe@example.com'])
    writer.writerow(['Batch A 2025', 'Jane Smith', 'jane.smith@example.com'])
    writer.writerow(['Batch B 2025', 'Alice Kumar', 'alice.kumar@example.com'])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name='batches_bulk_template.csv', mimetype='text/csv')


@app.route('/admin/batches/upload_bulk', methods=['POST'])
@batch_manager_required
def upload_batches_bulk():
    """Bulk upload batches and students from a single file with columns BatchName,Name,Email."""
    file = request.files.get('batches_file')
    replace = request.form.get('replace') == '1'
    if not file or not file.filename:
        flash('Please select a file to upload.', 'error')
        return redirect(url_for('manage_batches'))
    try:
        filename = secure_filename(file.filename)
        temp_path = os.path.join(TEMP_DIR, f"{secrets.token_hex(8)}_{filename}")
        file.save(temp_path)
        if temp_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(temp_path)
        else:
            df = pd.read_csv(temp_path)
        df.columns = df.columns.str.strip()
        required_cols = {'BatchName', 'Name', 'Email'}
        if not required_cols.issubset(set(df.columns)):
            flash('Bulk file must contain columns BatchName, Name, and Email.', 'error')
            return redirect(url_for('manage_batches'))

        # Optionally clear students for affected batches first
        if replace:
            affected_batches = set(df['BatchName'].dropna().astype(str).str.strip())
            for bname in affected_batches:
                if not bname:
                    continue
                # Find or create batch
                existing_batches = [b for b in get_batches() if b['name'] == bname]
                if existing_batches:
                    b = existing_batches[0]
                    existing_students = get_batch_students(b['id'])
                    for s in existing_students:
                        delete_batch_student(s['id'])

        # Insert/append students
        for _, row in df.iterrows():
            batch_name = str(row['BatchName']).strip()
            name = str(row['Name']).strip()
            email = str(row['Email']).strip().lower()
            if not batch_name or not name or not email:
                continue
            # Find or create batch
            existing_batches = [b for b in get_batches() if b['name'] == batch_name]
            if existing_batches:
                b = existing_batches[0]
                batch_id = b['id']
            else:
                batch_id = create_batch(batch_name, None, session.get('user_id', 'superadmin@attendancify.com'))
            add_student_to_batch(batch_id, name, email)
        flash('Bulk batches and students uploaded successfully.', 'success')
    except Exception as e:
        flash(f'Error uploading bulk batches: {str(e)}', 'error')
    return redirect(url_for('manage_batches'))

# ----------- Excluded Participants Management -----------
@app.route('/admin/excluded_participants')
@login_required
def manage_excluded_participants():
    """Manage excluded participants - Superadmin only"""
    if session.get('role') != 'superadmin':
        flash('Access denied. Superadmin access required.', 'error')
        return redirect(url_for('index'))
    
    excluded = get_excluded_participants()
    return render_template('excluded_participants.html', excluded=excluded, show_navigation=True)

@app.route('/admin/excluded_participants/add', methods=['POST'])
@login_required
def add_excluded():
    """Add a participant to exclusion list"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    identifier = request.form.get('identifier', '').strip()
    identifier_type = request.form.get('identifier_type', 'name')
    
    if not identifier:
        flash('Please enter a name or email to exclude.', 'error')
        return redirect(url_for('manage_excluded_participants'))
    
    if add_excluded_participant(identifier, identifier_type, session.get('user_id')):
        flash(f'Added "{identifier}" to exclusion list.', 'success')
    else:
        flash(f'"{identifier}" is already in the exclusion list.', 'warning')
    
    return redirect(url_for('manage_excluded_participants'))

@app.route('/admin/excluded_participants/bulk_add', methods=['POST'])
@login_required
def bulk_add_excluded():
    """Add multiple participants to exclusion list"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    identifiers_text = request.form.get('identifiers', '').strip()
    identifier_type = request.form.get('identifier_type', 'name')
    
    if not identifiers_text:
        flash('Please enter names or emails to exclude.', 'error')
        return redirect(url_for('manage_excluded_participants'))
    
    # Split by newlines and commas
    identifiers = []
    for line in identifiers_text.split('\n'):
        for item in line.split(','):
            item = item.strip()
            if item:
                identifiers.append(item)
    
    added = bulk_add_excluded_participants(identifiers, identifier_type, session.get('user_id'))
    flash(f'Added {added} entries to exclusion list.', 'success')
    
    return redirect(url_for('manage_excluded_participants'))

@app.route('/admin/excluded_participants/upload', methods=['POST'])
@login_required
def upload_excluded():
    """Upload CSV/Excel file with participants to exclude"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    file = request.files.get('file')
    identifier_type = request.form.get('identifier_type', 'name')
    
    if not file or not file.filename:
        flash('Please select a file.', 'error')
        return redirect(url_for('manage_excluded_participants'))
    
    try:
        # Read file
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # Find the column with identifiers (first column or column named 'name'/'email')
        identifiers = []
        if identifier_type == 'email' and 'email' in df.columns.str.lower().tolist():
            col = df.columns[df.columns.str.lower() == 'email'][0]
            identifiers = df[col].dropna().astype(str).tolist()
        elif identifier_type == 'name' and 'name' in df.columns.str.lower().tolist():
            col = df.columns[df.columns.str.lower() == 'name'][0]
            identifiers = df[col].dropna().astype(str).tolist()
        else:
            # Use first column
            identifiers = df.iloc[:, 0].dropna().astype(str).tolist()
        
        added = bulk_add_excluded_participants(identifiers, identifier_type, session.get('user_id'))
        flash(f'Uploaded {added} entries to exclusion list.', 'success')
    except Exception as e:
        flash(f'Error uploading file: {str(e)}', 'error')
    
    return redirect(url_for('manage_excluded_participants'))

@app.route('/admin/excluded_participants/edit/<int:participant_id>', methods=['POST'])
@login_required
def edit_excluded(participant_id):
    """Edit an excluded participant's identifier"""
    if session.get('role') != 'superadmin':
        return {'success': False, 'message': 'Access denied'}, 403
    
    data = request.get_json()
    identifier = data.get('identifier', '').strip()
    identifier_type = data.get('identifier_type', 'email')
    
    if not identifier:
        return {'success': False, 'message': 'Identifier cannot be empty'}
    
    if update_excluded_participant(participant_id, identifier, identifier_type):
        return {'success': True, 'message': 'Updated successfully'}
    else:
        return {'success': False, 'message': 'Update failed. Identifier may already exist.'}

@app.route('/admin/excluded_participants/delete/<int:participant_id>', methods=['POST'])
@login_required
def delete_excluded(participant_id):
    """Remove a participant from exclusion list"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    remove_excluded_participant(participant_id)
    flash('Removed from exclusion list.', 'success')
    return redirect(url_for('manage_excluded_participants'))

@app.route('/admin/excluded_participants/clear_all', methods=['POST'])
@login_required
def clear_all_excluded():
    """Clear all excluded participants"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    try:
        import sqlite3
        from database import DATABASE
        with sqlite3.connect(DATABASE) as conn:
            conn.execute('DELETE FROM excluded_participants')
            conn.commit()
        flash('Cleared all exclusions.', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('manage_excluded_participants'))

@app.route('/admin/excluded_participants/download_template')
@login_required
def download_excluded_template():
    """Download template file for excluded participants"""
    if session.get('role') != 'superadmin':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    try:
        import io
        # Create a simple CSV template
        template_data = io.StringIO()
        template_data.write('Email\n')
        template_data.write('user1@example.com\n')
        template_data.write('user2@example.com\n')
        template_data.write('user3@example.com\n')
        template_data.seek(0)
        
        # Create BytesIO for response
        output = io.BytesIO()
        output.write(template_data.getvalue().encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name='excluded_participants_template.csv'
        )
    except Exception as e:
        flash(f'Error generating template: {str(e)}', 'error')
        return redirect(url_for('manage_excluded_participants'))

# ----------- Name Normalization -----------
def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        name = str(name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().lower()

# ----------- Raw Excel Generator Functions -----------
SHEET_NAME = "Attendance"

def extract_raw_from_excel(xl_path):
    """
    Extract attendance data from Excel file.
    - Looks for 'Name (Original Name)' column for names
    - Looks for date-time columns (e.g., '2025-10-18 10:30:00') for P/A status
    - Output: Name, Session 1 (date_time), Session 2 (date_time), ...
    - xl_path can be a file path (str) or a file-like object (BytesIO)
    """
    # Always extract sheet named "Attendance"
    xl = pd.ExcelFile(xl_path)
    if SHEET_NAME not in xl.sheet_names:
        raise ValueError(f"Sheet '{SHEET_NAME}' not found in the file.")
    df = xl.parse(SHEET_NAME)
    
    # Find the Name column - prioritize "Name (Original Name)"
    name_col = None
    name_candidates = [
        "name (original name)", 
        "name(original name)",
        "name (original)",
        "original name",
        "name",
        "participant name"
    ]
    
    for col in df.columns:
        col_lower = str(col).strip().lower()
        for candidate in name_candidates:
            if candidate in col_lower or col_lower == candidate:
                name_col = col
                break
        if name_col:
            break
    
    if not name_col:
        raise ValueError("No 'Name' or 'Name (Original Name)' column found.")
    
    # Find date-time columns for P/A status
    # These columns typically have datetime format like '2025-10-18 10:30:00'
    datetime_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}[\s_]\d{2}:\d{2}:\d{2}$')
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    
    session_cols = []
    for col in df.columns:
        col_str = str(col).strip()
        # Check if column name matches datetime pattern
        if datetime_pattern.match(col_str) or date_pattern.match(col_str):
            session_cols.append(col)
        # Also check if column contains P/A values (fallback)
        elif col != name_col:
            unique_vals = df[col].dropna().astype(str).str.strip().str.upper().unique()
            if set(unique_vals).issubset({'P', 'A', 'N/A', ''}):
                session_cols.append(col)
    
    # If no datetime columns found, try columns with "Session" in name
    if not session_cols:
        session_cols = [c for c in df.columns if "session" in str(c).lower() and c != name_col]
    
    # If still no session columns, look for any columns with P/A values
    if not session_cols:
        for col in df.columns:
            if col != name_col:
                unique_vals = df[col].dropna().astype(str).str.strip().str.upper().unique()
                # Check if column has mostly P/A values
                pa_count = sum(1 for v in unique_vals if v in ('P', 'A'))
                if pa_count > 0 and pa_count >= len(unique_vals) * 0.5:
                    session_cols.append(col)
    
    if not session_cols:
        raise ValueError("No session/date-time columns with P/A values found.")
    
    # Create output dataframe
    out = df[[name_col] + session_cols].copy()
    
    # Rename columns: Name stays as "Name", date-time columns become "Session N (datetime)"
    new_column_names = ["Name"]
    for i, col in enumerate(session_cols, 1):
        col_str = str(col).strip()
        # If it's a datetime column, format as "Session N (datetime)"
        if datetime_pattern.match(col_str) or date_pattern.match(col_str):
            new_column_names.append(f"Session {i} ({col_str})")
        else:
            # Keep original name if it already has Session format
            new_column_names.append(str(col))
    
    out.columns = new_column_names
    
    # Normalize P/A values - only keep "P"/"A", replace anything else with "N/A"
    for col in out.columns[1:]:  # Skip the Name column
        out[col] = out[col].apply(lambda x: str(x).strip().upper() if str(x).strip().upper() in ("P", "A") else "N/A")
    
    return out

# ----------- Attendance Matching Functions -----------

def normalize_session_header(header: str) -> str:
    """
    Normalize session column headers to support multiple date formats.
    Supports:
    - "Session 1 (26.11.2025_19:30)" - DD.MM.YYYY_HH:MM format
    - "Session 1 (2025-09-06 17:30:00)" - YYYY-MM-DD HH:MM:SS format
    - "Session 1 (2025-09-06)" - YYYY-MM-DD format
    - Any other format is preserved as-is
    """
    header = str(header).strip()
    
    # Pattern for DD.MM.YYYY_HH:MM format (e.g., "Session 1 (26.11.2025_19:30)")
    pattern1 = r'^(Session\s*\d+)\s*\((\d{1,2})\.(\d{1,2})\.(\d{4})_(\d{1,2}):(\d{2})\)$'
    match1 = re.match(pattern1, header, re.IGNORECASE)
    if match1:
        session_name = match1.group(1)
        day, month, year, hour, minute = match1.groups()[1:]
        # Normalize to "Session N (YYYY-MM-DD HH:MM)"
        return f"{session_name} ({year}-{month.zfill(2)}-{day.zfill(2)} {hour.zfill(2)}:{minute})"
    
    # Pattern for YYYY-MM-DD HH:MM:SS format (e.g., "Session 1 (2025-09-06 17:30:00)")
    pattern2 = r'^(Session\s*\d+)\s*\((\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2}):?(\d{2})?\)$'
    match2 = re.match(pattern2, header, re.IGNORECASE)
    if match2:
        session_name = match2.group(1)
        year, month, day, hour, minute = match2.groups()[1:6]
        # Normalize to "Session N (YYYY-MM-DD HH:MM)"
        return f"{session_name} ({year}-{month.zfill(2)}-{day.zfill(2)} {hour.zfill(2)}:{minute})"
    
    # Pattern for YYYY-MM-DD format without time (e.g., "Session 1 (2025-09-06)")
    pattern3 = r'^(Session\s*\d+)\s*\((\d{4})-(\d{1,2})-(\d{1,2})\)$'
    match3 = re.match(pattern3, header, re.IGNORECASE)
    if match3:
        session_name = match3.group(1)
        year, month, day = match3.groups()[1:]
        return f"{session_name} ({year}-{month.zfill(2)}-{day.zfill(2)})"
    
    # Return original header if no pattern matches
    return header


def read_raw_file(raw_path: str, normalize_headers: bool = True) -> pd.DataFrame:
    """
    Read raw attendance file and normalize headers.
    Supports both CSV and Excel formats.
    Handles multiple session header date formats.
    """
    df = pd.read_csv(raw_path) if raw_path.lower().endswith(".csv") else pd.read_excel(raw_path)
    
    # Normalize headers (strip unicode spaces, unify casing)
    def _norm_header(h):
        s = unicodedata.normalize('NFKC', str(h))
        s = s.replace('\u00A0', ' ').replace('\u200B', '')  # NBSP and zero-width space
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s
    
    original_cols = list(df.columns)
    norm_map = {orig: _norm_header(orig) for orig in original_cols}

    # Try to find a 'Name' column by robust matching
    candidates_exact = {"name", "participant name", "participant", "full name", "name (original name)", "name (original)"}
    name_col = None
    for orig, norm in norm_map.items():
        if norm in candidates_exact:
            name_col = orig
            break
    if name_col is None:
        # Fallback: any header containing whole word 'name'
        for orig, norm in norm_map.items():
            if re.search(r"\bname\b", norm):
                name_col = orig
                break
    if name_col is None:
        # Last resort: strip non-letters and compare
        def letters_only(s):
            return re.sub(r"[^a-z]", "", s)
        for orig, norm in norm_map.items():
            lo = letters_only(norm)
            if lo in {"name", "participantname", "fullname"}:
                name_col = orig
                break
    if name_col is None:
        raise ValueError("Raw file needs a 'Name' column.")

    # Session/status columns are all others
    session_cols = [c for c in original_cols if c != name_col]
    if not session_cols:
        raise ValueError("Raw file contains no session/status columns.")
    
    # Normalize session column headers if requested
    if normalize_headers:
        new_session_cols = [normalize_session_header(c) for c in session_cols]
        rename_map = {old: new for old, new in zip(session_cols, new_session_cols)}
        df = df.rename(columns=rename_map)
        session_cols = new_session_cols
    
    def norm(x):
        val = str(x).strip().upper()
        return val if val in ("P", "A") else "N/A"
    for col in session_cols:
        df[col] = df[col].apply(norm)
    out = df[[name_col] + session_cols].copy()
    out.columns = ["Name"] + session_cols
    return out

def postprocess_attendance(df, session_cols):
    # Replace P→present, A→absent (case-insensitive), but only in session columns
    for col in session_cols:
        df[col] = df[col].replace({"P": "present", "A": "absent", "p": "present", "a": "absent"})
    return df

def _match_and_write_core(mdf: pd.DataFrame, raw_file: str, out_fmt: str, master_label: str) -> str:
    email_col = next((c for c in mdf.columns if str(c).strip().lower() in ("email", "email_id")), None)
    name_col = next((c for c in mdf.columns if str(c).strip().lower() in ("participant name", "name")), None)
    
    if email_col is None or name_col is None:
        raise ValueError("Master file must have 'Email' and 'Participant Name' columns.")
    mdf = mdf[[email_col, name_col]].copy()
    mdf.columns = ["Email", "Participant Name"]
    rdf = read_raw_file(raw_file)
    session_cols = list(rdf.columns[1:])
    raw_norm_names = [normalize_name(n) for n in list(rdf["Name"])]
    
    matched_df = mdf.copy()
    # Insert Raw Name column right after Participant Name
    matched_df.insert(2, 'Raw Name', '')
    for col in session_cols:
        matched_df[col] = "N/A"
    threshold = 85
    matched_indices = set()
    for idx, row in matched_df.iterrows():
        master_name = normalize_name(str(row["Participant Name"]))
        best_score, best_j = -1, None
        for j, raw_norm in enumerate(raw_norm_names):
            score = fuzz.token_set_ratio(master_name, raw_norm)
            if score > best_score:
                best_score = score
                best_j = j
        if best_score >= threshold:
            raw_row = rdf.iloc[best_j]
            # Set raw name (from the raw file)
            try:
                matched_df.at[idx, 'Raw Name'] = raw_row['Name']
            except Exception:
                matched_df.at[idx, 'Raw Name'] = ''
            for col in session_cols:
                matched_df.at[idx, col] = raw_row[col]
            matched_indices.add(best_j)
    
    unmatched_df = rdf.iloc[[i for i in range(len(rdf)) if i not in matched_indices]].copy()
    if not unmatched_df.empty:
        unmatched_df.rename(columns={"Name": "Raw Name (not found in Master)"}, inplace=True)
    # ---- Here: replace P/A
    matched_df = postprocess_attendance(matched_df, session_cols)
    if not unmatched_df.empty:
        unmatched_df = postprocess_attendance(unmatched_df, session_cols)
    out_dir = TEMP_DIR
    # Use a clean master label for output filenames (batch name or master file base)
    mbase = master_label
    rstored = os.path.basename(raw_file)
    rbase_raw = rstored.split('_', 1)[1] if '_' in rstored else rstored
    rbase = os.path.splitext(rbase_raw)[0]
    if out_fmt == "xlsx":
        # Get app-specific naming for App2 (Smart Matcher)
        app_name_display = get_app_setting('app2_name', 'Intelligent_Record_Matcher')
        app_name_for_file = app_name_display.replace(' ', '_').replace('-', '_')
        
        # Get original raw filename (strip random hex prefix)
        rstored = os.path.basename(raw_file)
        rbase_raw = rstored.split('_', 1)[1] if '_' in rstored else rstored
        rbase = os.path.splitext(rbase_raw)[0]
        
        # Get custom column mappings if configured
        app_format = get_app_output_format('app2')
        custom_columns = None
        try:
            if app_format and app_format['custom_columns_json']:
                import json
                custom_columns = json.loads(app_format['custom_columns_json'])
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"Warning: Could not parse custom columns JSON for App2: {e}")
        
        # Apply custom column mappings if provided
        if custom_columns and isinstance(custom_columns, dict):
            matched_df = matched_df.rename(columns=custom_columns)
            if not unmatched_df.empty:
                unmatched_df = unmatched_df.rename(columns=custom_columns)
        
        # Prefix with tool name: AppName_OriginalFileName.xlsx
        out_path = os.path.join(out_dir, f"{app_name_for_file}_{rbase}.xlsx")
        with pd.ExcelWriter(out_path, engine="openpyxl") as w:
            matched_df.to_excel(w, index=False, sheet_name="Matched")
            if not unmatched_df.empty:
                unmatched_df.to_excel(w, index=False, sheet_name="Unmatched Raw")
            pd.DataFrame([], columns=["email_id", "attendance(absent/present/leave)"]).to_excel(w, index=False, sheet_name="Summary")
        return out_path
    prefix = os.path.join(out_dir, f"{mbase}_matched_with_{rbase}_")
    matched_df.to_csv(prefix + "matched.csv", index=False)
    if not unmatched_df.empty:
        unmatched_df.to_csv(prefix + "unmatched.csv", index=False)
    pd.DataFrame([], columns=["email_id", "attendance(absent/present/leave)"]).to_csv(prefix + "summary.csv", index=False)
    return prefix + "matched.csv"


def match_and_write(master_file: str, raw_file: str, out_fmt: str = "xlsx") -> str:
    """Existing entry point that reads master from a file path."""
    mdf = pd.read_csv(master_file) if master_file.lower().endswith(".csv") else pd.read_excel(master_file)
    # Derive a user-facing label from the stored filename (strip random hex)
    mstored = os.path.basename(master_file)
    mbase_raw = mstored.split('_', 1)[1] if '_' in mstored else mstored
    master_label = os.path.splitext(mbase_raw)[0]
    return _match_and_write_core(mdf, raw_file, out_fmt, master_label)


def match_and_write_from_students(batch_name: str, students: list[dict], raw_file: str, out_fmt: str = "xlsx") -> str:
    """Match using an in-memory student list (batch-based master)."""
    if not students:
        raise ValueError("Selected batch has no students.")
    mdf = pd.DataFrame(students)
    
    # Ensure expected column names
    if 'Email' not in mdf.columns or 'Participant Name' not in mdf.columns:
        raise ValueError(f"Batch student data must have 'Email' and 'Participant Name' columns. Got: {list(mdf.columns)}")
    return _match_and_write_core(mdf, raw_file, out_fmt, batch_name)

# ----------- Routes -----------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Handle login form submission
        email = request.form['email']
        password = request.form['password']
        
        user = get_user(email)
        
        if user:
            user_dict = dict(user) if hasattr(user, 'keys') else user
            if verify_password(user_dict.get('password_hash', ''), password):
                # Check if account has expired
                expires_at_dt = make_aware(user_dict.get('expires_at'))
                if expires_at_dt and datetime.now(IST) > expires_at_dt:
                    flash('Your access has expired. Please contact the admin to renew your access.')
                    return render_template('comprehensive_index.html', show_navigation=True)
                
                # Get IP address
                ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
                
                # Log login with IP address
                log_user_login(email, ip_address)
                
                # Set session variables
                session['user_id'] = email
                session['role'] = user_dict.get('role', 'user')
                session['logged_in'] = True
                session['last_activity'] = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
                # Store profile info for display
                session['first_name'] = user_dict.get('first_name') or ''
                # Feature/permission flags
                session['can_manage_roles'] = bool(user_dict.get('can_manage_roles', 0))
                session['can_manage_batch_matching'] = bool(user_dict.get('can_manage_batch_matching', 0))
                session['can_manage_batches'] = bool(user_dict.get('can_manage_batches', 0))
                session['can_access_processed_files'] = bool(user_dict.get('can_access_processed_files', 0))
                session['can_view_dashboard'] = bool(user_dict.get('can_view_dashboard', 0))
                if expires_at_dt:
                    session['expires_at_display'] = expires_at_dt.strftime('%Y-%m-%d %H:%M')
                else:
                    session['expires_at_display'] = ''
                
                # Check if password change is required
                if user_dict.get('must_change_password', False):
                    flash('You must change your password on first login.', 'warning')
                    return redirect(url_for('force_change_password'))
                
                flash('Login successful!')
                return redirect(url_for('index'))
            else:
                flash('Invalid email or password.')
        else:
            flash('Invalid email or password.')
    
    # Allow public access to the homepage
    # Compute batch mode context for Smart Matcher modal
    can_use_batch_matching_flag = False
    batches = []
    batch_counts = {}
    if 'user_id' in session:
        session_role = session.get('role')
        if session_role == 'superadmin':
            can_use_batch_matching_flag = True
            batches = get_batches()
            for b in batches:
                try:
                    students = get_batch_students(b['id'])
                    batch_counts[b['id']] = len(students)
                except Exception:
                    batch_counts[b['id']] = 0
        else:
            try:
                user_row = get_user(session['user_id'])
                user = dict(user_row) if user_row is not None and hasattr(user_row, 'keys') else user_row
            except Exception:
                user = None
            if user and user.get('can_use_batch_matching'):
                can_use_batch_matching_flag = True
                batches = get_batches()
                for b in batches:
                    try:
                        students = get_batch_students(b['id'])
                        batch_counts[b['id']] = len(students)
                    except Exception:
                        batch_counts[b['id']] = 0
    # Get custom app names from settings
    app_names = {
        'app1': get_app_setting('app1_name', 'Zoom Attendance Analyzer'),
        'app2': get_app_setting('app2_name', 'Intelligent Record Matcher'),
        'app3': get_app_setting('app3_name', 'Session Report Generator'),
    }
    
    return render_template(
        'comprehensive_index.html',
        show_navigation=True,
        can_use_batch_matching=can_use_batch_matching_flag,
        batches=batches,
        batch_counts=batch_counts,
        app_names=app_names
    )

# ----------- Attendance Generator Routes -----------
@app.route('/attendance_generator')
def attendance_generator():
    # Allow public viewing of the tool UI
    app_names = get_app_names()
    return render_template('attendance_generator.html', show_navigation=True, app_names=app_names)

@app.route('/upload_attendance', methods=['POST'])
@login_required
def upload_attendance_file():
    # Get the mode (single or multiple)
    mode = request.form.get('mode', 'single')
    
    files = request.files.getlist('csv_files')
    if not files or not any(f.filename for f in files):
        flash('No files selected')
        return redirect(url_for('attendance_generator'))

    # Save all files and store their info
    file_paths = []
    file_names = []
    for file in files:
        if file.filename:
            suffix = secrets.token_hex(8)
            filename = f"{suffix}_" + secure_filename(file.filename)
            file_path = os.path.join(TEMP_DIR, filename)
            file.save(file_path)
            file_paths.append(file_path)
            file_names.append(filename)

    # Determine mode based on number of files
    mode = 'multiple' if len(file_paths) > 1 else 'single'

    # Store file info in session
    session['file_paths'] = file_paths
    session['file_names'] = file_names
    session['mode'] = mode
    
    # For single file mode, also store singular path/name for compatibility
    if mode == 'single':
        session['file_path'] = file_paths[0]
        session['filename'] = file_names[0]

    return redirect(url_for('configure_attendance_sessions'))

@app.route('/configure_attendance_sessions')
@login_required
def configure_attendance_sessions():
    mode = session.get('mode', 'single')
    file_names = session.get('file_names', [])
    file_paths = session.get('file_paths', [])
    session_config = session.get('session_config', [])
    session_config_filename = session.get('session_config_filename', '')
    session_config_time_only = session.get('session_config_time_only', False)
    
    # Verify files still exist - check on every page load
    if not file_paths:
        flash('No files uploaded. Please upload your Zoom log files first.', 'error')
        return redirect(url_for('attendance_generator'))
    
    # Check which files still exist
    valid_paths = []
    valid_names = []
    for fp, fn in zip(file_paths, file_names):
        if os.path.exists(fp):
            valid_paths.append(fp)
            valid_names.append(fn)
    
    if not valid_paths:
        flash('Your uploaded files have expired. Please upload again. (Files are kept for 2 hours)', 'error')
        session.pop('file_paths', None)
        session.pop('file_names', None)
        return redirect(url_for('attendance_generator'))
    
    # Update session if some files were lost
    if len(valid_paths) < len(file_paths):
        session['file_paths'] = valid_paths
        session['file_names'] = valid_names
        file_names = valid_names
        flash(f'{len(file_paths) - len(valid_paths)} file(s) expired. {len(valid_paths)} file(s) remaining.', 'warning')

    # If no config loaded, seed with default time-only slots
    if not session_config:
        def _hm(s):
            try:
                dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
            except Exception:
                dt = datetime.fromisoformat(s.replace(' ', 'T'))
            return dt.strftime('%H:%M')
        defaults = [
            ('2025-10-25 09:00:00','2025-10-25 10:15:00',65),
            ('2025-10-25 10:30:00','2025-10-25 11:45:00',45),
            ('2025-10-25 12:00:00','2025-10-25 13:15:00',45),
            ('2025-10-25 14:30:00','2025-10-25 15:45:00',45),
            ('2025-10-25 16:00:00','2025-10-25 17:15:00',45),
            ('2025-10-25 15:00:00','2025-10-25 16:15:00',0),
            ('2025-10-25 16:30:00','2025-10-25 17:45:00',0),
            ('2025-10-25 15:30:00','2025-10-25 16:45:00',0),
            ('2025-10-25 17:00:00','2025-10-25 18:15:00',0),
            ('2025-10-25 17:30:00','2025-10-25 18:45:00',45),
            ('2025-10-25 19:00:00','2025-10-25 20:15:00',45),
            ('2025-10-25 20:00:00','2025-10-25 21:15:00',0),
            ('2025-10-25 20:30:00','2025-10-25 21:45:00',0),
        ]
        session_config = [
            {'file': None, 'start_hm': _hm(s), 'end_hm': _hm(e), 'time_required': tr}
            for (s,e,tr) in defaults
        ]
        session['session_config'] = session_config
        session['session_config_time_only'] = True
        session_config_time_only = True

    return render_template('configure_attendance.html', mode=mode, file_names=file_names, session_config=session_config, session_config_filename=session_config_filename, session_config_time_only=session_config_time_only, show_navigation=True)

@app.route('/upload_session_config', methods=['POST'])
@login_required
def upload_session_config():
    try:
        file = request.files.get('session_config_csv')
        if not file or not file.filename:
            flash('Please choose a Session Config CSV file to upload.')
            return redirect(url_for('configure_attendance_sessions'))

        # Save temporary
        suffix = secrets.token_hex(8)
        filename = f"{suffix}_" + secure_filename(file.filename)
        temp_path = os.path.join(TEMP_DIR, filename)
        file.save(temp_path)

        # Parse CSV
        df = pd.read_csv(temp_path)
        df.columns = df.columns.str.strip()
        required = ["Session Start", "Session End", "Time Required"]
        for col in required:
            if col not in df.columns:
                flash(f"Session Config CSV must contain column '{col}'.")
                return redirect(url_for('configure_attendance_sessions'))
        has_file = 'File' in df.columns
        rows = []
        for _, row in df.iterrows():
            try:
                s = row["Session Start"]
                e = row["Session End"]
                tr = float(row["Time Required"]) if pd.notna(row["Time Required"]) else 0.0
                # Parse and strip date -> keep HH:MM only
                def _parse_any(x):
                    if pd.isna(x):
                        return None
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
                        try:
                            return datetime.strptime(str(x).strip(), fmt)
                        except Exception:
                            continue
                    try:
                        return pd.to_datetime(x).to_pydatetime()
                    except Exception:
                        return None
                sd = _parse_any(s)
                ed = _parse_any(e)
                if not sd or not ed:
                    continue
                file_val = str(row['File']).strip() if has_file and pd.notna(row['File']) else None
                rows.append({
                    'file': file_val,
                    'start_hm': sd.strftime('%H:%M'),
                    'end_hm': ed.strftime('%H:%M'),
                    'time_required': tr
                })
            except Exception:
                continue

        if not rows:
            flash('No valid session configurations found in uploaded CSV.')
            return redirect(url_for('configure_attendance_sessions'))

        # Store in session
        session['session_config'] = rows
        session['session_config_filename'] = file.filename
        session['session_config_time_only'] = True
        flash('Session configuration loaded. You can now import sessions from it.', 'success')
        return redirect(url_for('configure_attendance_sessions'))
    except Exception as e:
        flash(f'Failed to load session configuration: {str(e)}')
        return redirect(url_for('configure_attendance_sessions'))

@app.route('/process_attendance', methods=['POST'])
@login_required
def process_attendance():
    try:
        mode = session.get('mode', 'single')
        user_email = session.get('user_id')
        
        # Determine date mode from form (defaults to per_session)
        date_mode = request.form.get('date_mode', 'per_session')

        file_paths = session.get('file_paths', [])
        file_names = session.get('file_names', [])
        
        if not file_paths:
            flash('No files found in session. Please upload your files again.', 'error')
            return redirect(url_for('attendance_generator'))
        
        # Verify all files still exist on disk
        missing_files = []
        valid_paths = []
        valid_names = []
        for fp, fn in zip(file_paths, file_names):
            if os.path.exists(fp):
                valid_paths.append(fp)
                valid_names.append(fn)
            else:
                missing_files.append(fn)
        
        if missing_files:
            if not valid_paths:
                flash(f'All uploaded files have expired or were removed. Please upload again. Files may expire after 2 hours of inactivity.', 'error')
                # Clear session data
                session.pop('file_paths', None)
                session.pop('file_names', None)
                return redirect(url_for('attendance_generator'))
            else:
                flash(f'Some files were not found and will be skipped: {", ".join(missing_files)}. Please re-upload if needed.', 'warning')
                # Update session with valid files only
                session['file_paths'] = valid_paths
                session['file_names'] = valid_names
                file_paths = valid_paths
                file_names = valid_names

        # Get session configurations from form
        sessions_by_file = {}
        session_row_count = int(request.form.get('session_row_count', 0))

        if session_row_count <= 0:
            flash('Please add at least one session configuration.')
            return redirect(url_for('configure_attendance_sessions'))

        # Global date handling
        global_date_str = request.form.get('global_date') if date_mode == 'global' else None
        global_date = None
        if global_date_str:
            try:
                global_date = datetime.strptime(global_date_str, '%Y-%m-%d').date()
            except Exception as e:
                flash(f'Invalid global date format: {str(e)}')
                return redirect(url_for('configure_attendance_sessions'))

        # Collect session info from form
        for i in range(session_row_count):
            # In single mode, file_name is not in the form, so get it from the session
            if mode == 'single':
                file_name = file_names[0] if file_names else None
            else:
                file_name = request.form.get(f'file_name_{i}')
            
            start_str = request.form.get(f'start_time_{i}')
            end_str = request.form.get(f'end_time_{i}')
            time_required = float(request.form.get(f'time_required_{i}', 30))

            if not file_name or not start_str or not end_str:
                continue

            # Find the corresponding file path
            file_path = next((fp for fn, fp in zip(file_names, file_paths) if fn == file_name), None)
            if not file_path:
                continue

            # Parse start and end times
            try:
                if date_mode == 'global' and global_date:
                    start_dt = datetime.strptime(start_str, '%H:%M').time()
                    end_dt = datetime.strptime(end_str, '%H:%M').time()
                    session_start = datetime.combine(global_date, start_dt)
                    session_end = datetime.combine(global_date, end_dt)
                else:
                    session_start = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
                    session_end = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')
            except Exception as e:
                flash(f'Invalid date/time format for session in file {file_name}: {str(e)}')
                return redirect(url_for('configure_attendance_sessions'))

            if session_start >= session_end:
                flash(f'Error in session for file {file_name}: Start time must be before end time.')
                return redirect(url_for('configure_attendance_sessions'))

            # Store session info
            if file_path not in sessions_by_file:
                sessions_by_file[file_path] = {"file_name": file_name, "sessions": []}
            sessions_by_file[file_path]["sessions"].append({
                "session_start": session_start,
                "session_end": session_end,
                "time_required": time_required
            })

        if not sessions_by_file:
            flash('No valid sessions were configured. Please check your inputs.')
            return redirect(url_for('configure_attendance_sessions'))

        # Process each file
        output_files = []
        for file_path, data in sessions_by_file.items():
            try:
                # Check if file still exists before processing
                if not os.path.exists(file_path):
                    flash(f'File {data["file_name"]} no longer exists. Please upload again.', 'error')
                    continue
                
                start_time = time.time()
                # Determine user role for output formatting (normal vs admin/superadmin)
                user_role = session.get('role', 'user')
                output_records, _, _ = process_sessions_for_file(file_path, data["sessions"], user_role=user_role)
                processing_time = time.time() - start_time

                # Read raw log data for Excel output (support CSV and Excel uploads)
                if file_path.lower().endswith(('.xlsx', '.xls')):
                    try:
                        raw_log_df = pd.read_excel(file_path, header=None)
                    except Exception as e:
                        raise ValueError(f"Error reading Excel file '{data['file_name']}': {e}")
                else:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            raw_data = list(csv.reader(f))
                        raw_log_df = pd.DataFrame(raw_data)
                    except UnicodeDecodeError:
                        # Try fallback encoding if UTF-8 fails
                        with open(file_path, 'r', encoding='latin-1') as f:
                            raw_data = list(csv.reader(f))
                        raw_log_df = pd.DataFrame(raw_data)

                # Create output Excel file with app-specific naming
                # Get app-specific format settings
                app_format = get_app_output_format('app1')
                app_name_display = get_app_setting('app1_name', 'Zoom_Attendance_Analyzer')
                
                # Format app name for filename (replace spaces with underscores)
                app_name_for_file = app_name_display.replace(' ', '_').replace('-', '_')
                
                # Get original filename (strip random hex prefix from stored temp name)
                stored_name = data["file_name"]
                base_name = stored_name.split('_', 1)[1] if '_' in stored_name else stored_name
                # Remove extension from original name
                base_root = os.path.splitext(base_name)[0]
                
                # Get file extension from app format
                file_ext = app_format['file_format'] if app_format else 'xlsx'
                
                # Get custom column mappings if configured
                custom_columns = None
                try:
                    if app_format and app_format['custom_columns_json']:
                        import json
                        custom_columns = json.loads(app_format['custom_columns_json'])
                except (KeyError, TypeError, json.JSONDecodeError) as e:
                    print(f"Warning: Could not parse custom columns JSON for App1: {e}")
                
                # Generate filename: AppName_OriginalFileName.ext
                output_filename = f"{app_name_for_file}_{base_root}.{file_ext}"
                output_path = os.path.join(TEMP_DIR, output_filename)
                write_excel(raw_log_df, output_records, output_path, custom_columns=custom_columns)
                
                # Register processed file in database immediately (not eligible for deletion yet)
                # This protects the file during the entire workflow
                # Will be marked eligible for deletion after batch completion
                register_processed_file(
                    file_path=output_path,
                    file_name=output_filename,
                    user_email=user_email,
                    processing_type='attendance_generation',
                    eligible_for_deletion_at=None  # Not eligible yet - will be set after completion
                )
                
                output_files.append({'path': output_path, 'name': output_filename})

                # Log processing
                file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                log_file_processing(
                    user_email=user_email,
                    file_name=data["file_name"],
                    processing_type='attendance_generation',
                    file_size=file_size,
                    processing_time=processing_time
                )
            except Exception as e:
                flash(f'Error processing file {data["file_name"]}: {str(e)}')
                return redirect(url_for('configure_attendance_sessions'))

        # Store output files in session for download
        session['attendance_output_files'] = output_files
        flash('Processing Complete! Your attendance reports have been generated.', 'success')
        
        # Mark all files as eligible for deletion after 2 hours from now
        # This happens AFTER all processing is complete, ensuring files are protected during the entire workflow
        eligible_time = (datetime.now() + timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
        for file_info in output_files:
            mark_file_eligible_for_deletion(file_info['path'], eligible_time)

        # Redirect to download page (or processed files page) to show success message and allow downloads
        # This ensures the flash message is displayed and users can download files
        if len(output_files) == 1:
            # For single file, redirect to download page which will auto-download
            return redirect(url_for('download_attendance'))
        else:
            # For multiple files, redirect to download page to show all files
            return redirect(url_for('download_attendance'))
        
    except Exception as e:
        flash(f'Error processing attendance: {str(e)}')
        return redirect(url_for('configure_attendance_sessions'))

@app.route('/download_attendance')
@login_required
def download_attendance():
    output_files = session.get('attendance_output_files', [])
    
    if not output_files:
        flash('No processed files found.')
        return redirect(url_for('attendance_generator'))

    # Check if a specific file is requested for download
    requested_file = request.args.get('file')
    if requested_file:
        for file_info in output_files:
            if file_info['name'] == requested_file:
                # Check if file exists before sending
                if os.path.exists(file_info['path']):
                    # Don't delete file - it's tracked in database and will be auto-deleted later
                    return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
                else:
                    flash(f'File {file_info["name"]} no longer exists.', 'error')
                    return redirect(url_for('attendance_generator'))
    
    # Check if download=true parameter is set (for auto-download)
    if request.args.get('download') == 'true':
        if len(output_files) == 1:
            file_info = output_files[0]
            if os.path.exists(file_info['path']):
                return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
            else:
                flash('Processed file no longer exists. Please process again.', 'error')
                return redirect(url_for('attendance_generator'))
        else:
            # Multiple files - create zip
            zip_filename = 'attendance_reports.zip'
            zip_path = os.path.join(TEMP_DIR, zip_filename)
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file_info in output_files:
                    if os.path.exists(file_info['path']):
                        zipf.write(file_info['path'], file_info['name'])
            if os.path.exists(zip_path):
                return send_file(zip_path, as_attachment=True, download_name=zip_filename)
            else:
                flash('Error creating zip file.', 'error')
                return redirect(url_for('attendance_generator'))

    # If single file, auto-download it
    if len(output_files) == 1:
        file_info = output_files[0]
        if os.path.exists(file_info['path']):
            return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
        else:
            flash('Processed file no longer exists. Please process again.', 'error')
            return redirect(url_for('attendance_generator'))

    # If not a specific file request and multiple files, render the download page
    app_names = get_app_names()
    return render_template('download_attendance.html',
                         files=output_files,
                         single_file=len(output_files) == 1,
                         app_names=app_names)

@app.route('/download_session_config_template')
@login_required
def download_session_config_template():
    defaults = [
        ('2025-10-25 09:00:00','2025-10-25 10:15:00',65),
        ('2025-10-25 10:30:00','2025-10-25 11:45:00',45),
        ('2025-10-25 12:00:00','2025-10-25 13:15:00',45),
        ('2025-10-25 14:30:00','2025-10-25 15:45:00',45),
        ('2025-10-25 16:00:00','2025-10-25 17:15:00',45),
        ('2025-10-25 15:00:00','2025-10-25 16:15:00',0),
        ('2025-10-25 16:30:00','2025-10-25 17:45:00',0),
        ('2025-10-25 15:30:00','2025-10-25 16:45:00',0),
        ('2025-10-25 17:00:00','2025-10-25 18:15:00',0),
        ('2025-10-25 17:30:00','2025-10-25 18:45:00',45),
        ('2025-10-25 19:00:00','2025-10-25 20:15:00',45),
        ('2025-10-25 20:00:00','2025-10-25 21:15:00',0),
        ('2025-10-25 20:30:00','2025-10-25 21:45:00',0),
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Session Start','Session End','Time Required','File'])
    for s,e,tr in defaults:
        writer.writerow([s,e,tr,''])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name='session_config_template.csv', mimetype='text/csv')

# ----------- Raw Excel Generator Routes -----------
@app.route('/raw_excel_generator')
def raw_excel_generator():
    # Allow public viewing of the tool UI
    app_names = get_app_names()
    return render_template('raw_excel_generator.html', show_navigation=True, app_names=app_names)

@app.route('/process_raw_excel', methods=['POST'])
@login_required
def process_raw_excel():
    try:
        # Get uploaded files
        files = request.files.getlist('excel_files')
        user_email = session.get('user_id')
        
        if not files or not any(f.filename for f in files):
            flash('No files selected')
            return redirect(url_for('raw_excel_generator'))
        
        # Process files in memory and return direct downloads (no storage)
        processed_data = []
        
        for file in files:
            if file.filename:
                # Read file into memory
                file_content = file.read()
                file.seek(0)  # Reset file pointer
                
                # Start timing the processing
                start_time = time.time()
                
                # Process the file in memory using BytesIO
                file_stream = io.BytesIO(file_content)
                raw_df = extract_raw_from_excel(file_stream)
                
                # Calculate processing time
                processing_time = time.time() - start_time
                
                # Generate output filename
                base_name = secure_filename(file.filename)
                base_root = os.path.splitext(base_name)[0]
                output_filename = f"Raw Excel Generator - {base_root}-RAW.xlsx"
                
                # Create Excel file in memory
                output_buffer = io.BytesIO()
                with pd.ExcelWriter(output_buffer, engine='openpyxl') as writer:
                    raw_df.to_excel(writer, index=False)
                output_buffer.seek(0)
                
                processed_data.append({
                    'buffer': output_buffer,
                    'filename': output_filename
                })
                
                # Log the file processing (file size from content length)
                file_size = len(file_content)
                log_file_processing(
                    user_email=user_email,
                    file_name=file.filename,
                    processing_type='raw_excel_generation',
                    file_size=file_size,
                    processing_time=processing_time
                )
        
        # If only one file, return direct download
        if len(processed_data) == 1:
            data = processed_data[0]
            return send_file(
                data['buffer'],
                as_attachment=True,
                download_name=data['filename'],
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        else:
            # Multiple files: create zip in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zipf:
                for data in processed_data:
                    zipf.writestr(data['filename'], data['buffer'].getvalue())
            zip_buffer.seek(0)
            
            return send_file(
                zip_buffer,
                as_attachment=True,
                download_name='raw_excel_files.zip',
                mimetype='application/zip'
            )
        
    except Exception as e:
        flash(f'Error processing files: {str(e)}')
        return redirect(url_for('raw_excel_generator'))

@app.route('/download_raw_excel')
@login_required
def download_raw_excel():
    output_files = session.get('raw_output_files', [])
    
    # Check if a specific file is requested
    requested_file = request.args.get('file')
    if requested_file:
        for file_info in output_files:
            if file_info['name'] == requested_file:
                if os.path.exists(file_info['path']):
                    response = send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
                    # Clean up the temporary file after sending
                    try:
                        os.remove(file_info['path'])
                    except OSError:
                        pass  # File might already be deleted
                    return response
                else:
                    flash(f'File {file_info["name"]} no longer exists.', 'error')
                    return redirect(url_for('raw_excel_generator'))
    
    if not output_files:
        flash('No processed files found.')
        return redirect(url_for('raw_excel_generator'))
    
    # If only one file, download it directly
    if len(output_files) == 1:
        file_info = output_files[0]
        if os.path.exists(file_info['path']):
            response = send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
            # Clean up the temporary file after sending
            try:
                os.remove(file_info['path'])
            except OSError:
                pass  # File might already be deleted
            return response
        else:
            flash('Processed file no longer exists. Please process again.', 'error')
            return redirect(url_for('raw_excel_generator'))
    else:
        # Create a zip file with all outputs
        zip_filename = 'raw_excel_files.zip'
        zip_path = os.path.join(TEMP_DIR, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_info in output_files:
                zipf.write(file_info['path'], file_info['name'])
        
        response = send_file(zip_path, as_attachment=True, download_name=zip_filename)
        # Clean up the temporary zip file after sending
        try:
            os.remove(zip_path)
        except OSError:
            pass  # File might already be deleted
        return response

# ----------- Attendance Matching Routes -----------
@app.route('/attendance_matching')
def attendance_matching():
    """Attendance Matching UI. Public can view, but batch mode requires login and permission."""
    can_use_batch_matching_flag = False
    batches = []
    batch_counts = {}
    if 'user_id' in session:
        # Trust session role for superadmin, fall back to DB for flags
        session_role = session.get('role')
        if session_role == 'superadmin':
            can_use_batch_matching_flag = True
            batches = get_batches()
            for b in batches:
                try:
                    students = get_batch_students(b['id'])
                    batch_counts[b['id']] = len(students)
                except Exception:
                    batch_counts[b['id']] = 0
        else:
            try:
                user_row = get_user(session['user_id'])
                user = dict(user_row) if user_row is not None and hasattr(user_row, 'keys') else user_row
            except Exception:
                user = None
            if user and user.get('can_use_batch_matching'):
                can_use_batch_matching_flag = True
                batches = get_batches()
                for b in batches:
                    try:
                        students = get_batch_students(b['id'])
                        batch_counts[b['id']] = len(students)
                    except Exception:
                        batch_counts[b['id']] = 0
    app_names = get_app_names()
    return render_template(
        'attendance_matching.html',
        show_navigation=True,
        can_use_batch_matching=can_use_batch_matching_flag,
        batches=batches,
        batch_counts=batch_counts,
        app_names=app_names
    )


@app.route('/download_attendance_matching')
@login_required
def download_attendance_matching():
    output_files = session.get('matching_output_files', [])
    
    # Check if a specific file is requested
    requested_file = request.args.get('file')
    if requested_file:
        for file_info in output_files:
            if file_info['name'] == requested_file:
                if os.path.exists(file_info['path']):
                    # Don't delete file - it's tracked in database and will be auto-deleted later
                    return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
                else:
                    flash(f'File {file_info["name"]} no longer exists.', 'error')
                    return redirect(url_for('attendance_matching'))
    
    if not output_files:
        flash('No processed files found.')
        return redirect(url_for('attendance_matching'))
    
    # If only one file, download it directly
    if len(output_files) == 1:
        file_info = output_files[0]
        if os.path.exists(file_info['path']):
            # Don't delete file - it's tracked in database and will be auto-deleted later
            return send_file(file_info['path'], as_attachment=True, download_name=file_info['name'])
        else:
            flash('Processed file no longer exists. Please process again.', 'error')
            return redirect(url_for('attendance_matching'))
    else:
        # Create a zip file with all outputs (temporary zip, can be deleted immediately)
        zip_filename = 'matching_results.zip'
        zip_path = os.path.join(TEMP_DIR, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_info in output_files:
                zipf.write(file_info['path'], file_info['name'])
        
        response = send_file(zip_path, as_attachment=True, download_name=zip_filename)
        # Clean up the temporary zip file after sending (zip is not tracked)
        try:
            os.remove(zip_path)
        except OSError:
            pass  # File might already be deleted
        return response

# ----------- Processed Files Management Routes (Superadmin Only) -----------
@app.route('/admin/processed_files')
@login_required
def processed_files_management():
    """List processed files - Superadmin sees all, other users see only their own"""
    user_email = session.get('user_id')
    user_role = session.get('role')
    
    # Debug logging
    print(f"\n=== Processed Files Access Check ===")
    print(f"User: {user_email}")
    print(f"Role: {user_role}")
    print(f"Session can_access_processed_files: {session.get('can_access_processed_files')}")
    
    # Check if user has permission (superadmin always has permission)
    if user_role != 'superadmin':
        try:
            user = get_user(user_email)
            if not user:
                print("ERROR: User not found in database")
                flash('User not found. Please login again.', 'error')
                return redirect(url_for('index'))
            user_dict = dict(user) if hasattr(user, 'keys') else user
            db_permission = user_dict.get('can_access_processed_files', 0)
            print(f"DB can_access_processed_files: {db_permission}")
            if not user_dict or not db_permission:
                print("ERROR: User does not have permission")
                flash('Access denied. You do not have permission to access processed files.', 'error')
                return redirect(url_for('index'))
        except Exception as e:
            print(f"ERROR checking user permissions: {e}")
            import traceback
            traceback.print_exc()
            flash('Error checking permissions. Please try again.', 'error')
            return redirect(url_for('index'))
    
    # Get ALL processed files from database (Excel Extractor files are not stored)
    try:
        if user_role == 'superadmin':
            # Superadmin sees all files (no type filter to get everything)
            files = list(get_processed_files())
            # Note: Deleted files are automatically hidden (manually_deleted = 1)
            # This is normal behavior - deleted files stay in database but are not shown
        else:
            # Regular users see their own files AND files shared with them
            # Get files owned by the user
            own_files = list(get_processed_files(user_email=user_email))
            
            # Get files shared with the user via permissions
            shared_files = []
            try:
                all_files = list(get_processed_files())  # Get all files to check permissions
                for f in all_files:
                    try:
                        if can_user_access_file(f['id'], user_email) and f['user_email'] != user_email:
                            # This file is shared with the user (not owned by them)
                            shared_files.append(f)
                    except Exception as e:
                        print(f"Error checking access for file {f.get('id')}: {e}")
                        continue  # Skip this file if there's an error
            except Exception as e:
                print(f"Error getting all files for permission check: {e}")
                # If we can't get all files, just use own files
                shared_files = []
            
            # Combine and deduplicate (in case of any duplicates)
            file_ids_seen = set()
            files = []
            for f in own_files + shared_files:
                if f['id'] not in file_ids_seen:
                    file_ids_seen.add(f['id'])
                    files.append(f)
    except Exception as e:
        print(f"Error getting processed files: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading processed files. Please try again.', 'error')
        return redirect(url_for('index'))
    
    # Format files with additional info
    files_list = []
    for f in files:
        file_info = dict(f)
        # Check if file still exists
        file_info['exists'] = os.path.exists(file_info['file_path'])
        # Calculate time remaining until deletion eligibility
        if file_info['eligible_for_deletion_at']:
            try:
                eligible_dt = datetime.strptime(file_info['eligible_for_deletion_at'], '%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                if eligible_dt > now:
                    remaining = eligible_dt - now
                    file_info['time_remaining'] = f"{int(remaining.total_seconds() / 60)} minutes"
                else:
                    file_info['time_remaining'] = "Eligible for deletion"
            except Exception:
                file_info['time_remaining'] = "Unknown"
        else:
            file_info['time_remaining'] = "Not set"
        
        files_list.append(file_info)
    
    return render_template('processed_files.html', files=files_list, show_navigation=True)

@app.route('/admin/processed_files/download/<int:file_id>')
@login_required
def download_processed_file(file_id):
    """Download a processed file - Superadmin, owner, or user with granted access"""
    user_email = session.get('user_id')
    user_role = session.get('role')
    
    # Get file record - check all files to find the one requested
    all_files = get_processed_files()
    file_record = None
    for f in all_files:
        if f['id'] == file_id:
            file_record = dict(f)
            break
    
    if not file_record:
        flash('File not found or access denied.', 'error')
        return redirect(url_for('processed_files_management'))
    
    # Security check: ensure user has access (superadmin, owner, or has permission)
    if user_role != 'superadmin':
        if not can_user_access_file(file_id, user_email):
            flash('Access denied. You do not have permission to download this file.', 'error')
            return redirect(url_for('processed_files_management'))
    
    if not os.path.exists(file_record['file_path']):
        flash('File no longer exists on server.', 'error')
        return redirect(url_for('processed_files_management'))
    
    return send_file(
        file_record['file_path'],
        as_attachment=True,
        download_name=file_record['file_name']
    )

@app.route('/admin/processed_files/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_processed_file(file_id):
    """Delete a processed file manually - Superadmin only (users cannot delete files)"""
    user_email = session.get('user_id')
    user_role = session.get('role')
    
    if user_role != 'superadmin':
        flash('Access denied. Only superadmin can delete files.', 'error')
        return redirect(url_for('index'))
    
    # Get file record
    files = get_processed_files()
    file_record = None
    for f in files:
        if f['id'] == file_id:
            file_record = dict(f)
            break
    
    if not file_record:
        flash('File not found.', 'error')
        return redirect(url_for('processed_files_management'))
    
    # Delete file from disk
    if os.path.exists(file_record['file_path']):
        try:
            os.remove(file_record['file_path'])
        except OSError:
            pass
    
    # Mark as manually deleted in database
    mark_file_manually_deleted(file_record['file_path'])
    
    flash('File deleted successfully.', 'success')
    return redirect(url_for('processed_files_management'))

@app.route('/admin/processed_files/rename/<int:file_id>', methods=['POST'])
@login_required
def rename_processed_file(file_id):
    """Rename a processed file - User can rename their own files"""
    user_email = session.get('user_id')
    user_role = session.get('role')
    
    # Get new name from request
    data = request.get_json()
    new_name = data.get('new_name', '').strip() if data else ''
    
    if not new_name:
        return {'success': False, 'message': 'New name is required'}
    
    # Get file record - check all files
    all_files = get_processed_files(include_deleted=False)
    file_record = None
    for f in all_files:
        if f['id'] == file_id:
            file_record = dict(f)
            break
    
    if not file_record:
        return {'success': False, 'message': 'File not found'}
    
    # Check permission: Superadmin can rename any, users can rename their own or shared files
    if user_role != 'superadmin':
        if not can_user_access_file(file_id, user_email):
            return {'success': False, 'message': 'Access denied'}
    
    # Update file name in database
    try:
        from database import update_processed_file_name
        if update_processed_file_name(file_id, new_name):
            return {'success': True, 'message': 'File renamed successfully'}
        else:
            return {'success': False, 'message': 'Failed to rename file'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@app.route('/admin/processed_files/<int:file_id>/permissions', methods=['GET', 'POST'])
@login_required
def manage_file_permissions(file_id):
    """Manage user permissions for a processed file - Superadmin only"""
    if session.get('role') != 'superadmin':
        flash('Access denied. Superadmin access required.', 'error')
        return redirect(url_for('index'))
    
    # Get file record
    files = get_processed_files()
    file_record = None
    for f in files:
        if f['id'] == file_id:
            file_record = dict(f)
            break
    
    if not file_record:
        flash('File not found.', 'error')
        return redirect(url_for('processed_files_management'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_email = request.form.get('user_email', '').strip().lower()
        
        if action == 'grant':
            if user_email:
                if grant_file_access(file_id, user_email, session.get('user_id')):
                    flash(f'Access granted to {user_email}.', 'success')
                else:
                    flash(f'Error granting access to {user_email}.', 'error')
        elif action == 'revoke':
            if user_email:
                revoke_file_access(file_id, user_email)
                flash(f'Access revoked from {user_email}.', 'success')
    
    # Get current permissions
    permissions = get_file_permissions(file_id)
    all_users = get_all_users()
    
    return render_template(
        'file_permissions.html',
        file=file_record,
        permissions=permissions,
        all_users=all_users,
        show_navigation=True
    )


# ----------- Final Excel Generator Routes -----------
@app.route('/process_final_excel', methods=['POST'])
@login_required
def process_final_excel():
    """Process matched Excel files and generate individual session files"""
    try:
        files = request.files.getlist('excel_files')
        output_format = request.form.get('output_format', 'xlsx')
        
        if not files or not any(f.filename for f in files):
            flash('Please select at least one file to process.', 'error')
            return redirect(url_for('index'))
        
        # Generate unique batch ID for this processing session
        batch_id = secrets.token_hex(8)
        processed_files = []
        
        for file in files:
            if not file.filename:
                continue
            
            try:
                # Read Excel file
                xls = pd.ExcelFile(file)
                sheet_name = "Matched" if "Matched" in xls.sheet_names else xls.sheet_names[0]
                df = pd.read_excel(xls, sheet_name=sheet_name)
                
                # Find email column (matching original script logic)
                email_col = None
                for col in df.columns:
                    if re.search(r'email', str(col), re.IGNORECASE):
                        email_col = col
                        break
                # Try alternative email column names
                if not email_col:
                    for col in df.columns:
                        if re.search(r'email_id|e-mail|e mail', str(col), re.IGNORECASE):
                            email_col = col
                            break
                
                if not email_col:
                    flash(f'No email column found in {file.filename}. Skipping.', 'warning')
                    continue
                
                # Find session columns (matching original script logic)
                session_cols = [c for c in df.columns if re.search(r'\bSession\b', str(c), re.IGNORECASE)]
                if not session_cols:
                    session_cols = [c for c in df.columns if 'Session' in str(c)]
                
                if not session_cols:
                    flash(f'No session columns found in {file.filename}. Skipping.', 'warning')
                    continue
                
                base_name = os.path.splitext(os.path.basename(secure_filename(file.filename)))[0]
                
                # Process each session column
                for col in session_cols:
                    # Normalize attendance values
                    def normalize_att(val):
                        if pd.isna(val):
                            return "absent"
                        s = str(val).strip().lower()
                        if 'n/a' in s or s == 'na':
                            return "absent"
                        if "present" in s:
                            return "present"
                        if "absent" in s:
                            return "absent"
                        if "leave" in s or "left" in s:
                            return "leave"
                        if re.search(r'\d', s):
                            return "present"
                        return "absent"
                    
                    # Create output dataframe
                    out_df = pd.DataFrame({
                        "email_id": df[email_col].astype(str).str.strip(),
                        "attendance(absent/present/leave)": df[col].apply(normalize_att)
                    })
                    
                    # Remove empty email rows
                    out_df = out_df[out_df['email_id'].str.len() > 0].reset_index(drop=True)
                    
                    # Get app-specific naming for App3 (Session Report Generator)
                    app_name_display = get_app_setting('app3_name', 'Session_Report_Generator')
                    app_name_for_file = app_name_display.replace(' ', '_').replace('-', '_')
                    
                    # Get original filename (base_name already has original filename)
                    # base_name is like "abc" if original file was "abc.xlsx"
                    
                    # Get custom column mappings if configured
                    app_format = get_app_output_format('app3')
                    custom_columns = None
                    try:
                        if app_format and app_format['custom_columns_json']:
                            import json
                            custom_columns = json.loads(app_format['custom_columns_json'])
                    except (KeyError, TypeError, json.JSONDecodeError) as e:
                        print(f"Warning: Could not parse custom columns JSON for App3: {e}")
                    
                    # Apply custom column mappings if provided
                    if custom_columns and isinstance(custom_columns, dict):
                        out_df = out_df.rename(columns=custom_columns)
                    
                    # Sanitize session label for filename
                    sess_label_clean = str(col)
                    sess_label_clean = sess_label_clean.replace(':', '_')
                    sess_label_clean = re.sub(r'[\\/*?:"<>|]', '_', sess_label_clean)
                    
                    # Generate filename: AppName_OriginalFileName_Session.ext
                    out_filename = f"{app_name_for_file}_{base_name}_{sess_label_clean}.{output_format}"
                    
                    # Save to temp directory
                    unique_filename = f"{batch_id}_{out_filename}"
                    file_path = os.path.join(TEMP_DIR, unique_filename)
                    
                    if output_format == 'xlsx':
                        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                            out_df.to_excel(writer, sheet_name="Sheet2", index=False)
                    else:
                        out_df.to_csv(file_path, index=False)
                    
                    # Register file in database for Processed Files page
                    user_email = session.get('user_id')
                    # Set eligible for deletion after 2 hours
                    eligible_time = (datetime.now() + timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
                    register_processed_file(
                        file_path=file_path,
                        file_name=out_filename,
                        user_email=user_email,
                        processing_type='final_excel',
                        eligible_for_deletion_at=eligible_time
                    )
                    
                    # Track processed file
                    processed_files.append({
                        'filename': out_filename,
                        'path': file_path,
                        'unique_filename': unique_filename,
                        'source_file': file.filename,
                        'session': str(col),
                        'rows': len(out_df)
                    })
            
            except Exception as e:
                flash(f'Error processing {file.filename}: {str(e)}', 'warning')
                continue
        
        if not processed_files:
            flash('No files were processed. Please check your input files.', 'error')
            return redirect(url_for('index'))
        
        # Store in session for the results page
        session['final_excel_batch_id'] = batch_id
        session['final_excel_files'] = processed_files
        session['final_excel_format'] = output_format
        
        return redirect(url_for('final_excel_results'))
        
    except Exception as e:
        flash(f'Error processing files: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/final_excel_results')
@login_required
def final_excel_results():
    """Show processed files from Final Excel Generator"""
    batch_id = session.get('final_excel_batch_id')
    processed_files = session.get('final_excel_files', [])
    output_format = session.get('final_excel_format', 'xlsx')
    
    if not batch_id or not processed_files:
        flash('No processed files found. Please process files first.', 'warning')
        return redirect(url_for('index'))
    
    return render_template(
        'final_excel_results.html',
        batch_id=batch_id,
        processed_files=processed_files,
        output_format=output_format,
        show_navigation=True
    )

@app.route('/final_excel_download/<batch_id>/<filename>')
@login_required
def final_excel_download_file(batch_id, filename):
    """Download a single processed file from Final Excel Generator"""
    # Verify batch ID matches session
    if session.get('final_excel_batch_id') != batch_id:
        flash('Invalid download request.', 'error')
        return redirect(url_for('index'))
    
    processed_files = session.get('final_excel_files', [])
    
    # Find the file
    for f in processed_files:
        if f['unique_filename'] == filename:
            if os.path.exists(f['path']):
                return send_file(f['path'], as_attachment=True, download_name=f['filename'])
    
    flash('File not found.', 'error')
    return redirect(url_for('final_excel_results'))

@app.route('/final_excel_download_all/<batch_id>')
@login_required
def final_excel_download_all(batch_id):
    """Download all processed files as ZIP from Final Excel Generator"""
    # Verify batch ID matches session
    if session.get('final_excel_batch_id') != batch_id:
        flash('Invalid download request.', 'error')
        return redirect(url_for('index'))
    
    processed_files = session.get('final_excel_files', [])
    
    if not processed_files:
        flash('No files to download.', 'error')
        return redirect(url_for('index'))
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in processed_files:
            if os.path.exists(f['path']):
                zipf.write(f['path'], f['filename'])
    
    zip_buffer.seek(0)
    
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=f'Final_Excel_Generator_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip',
        mimetype='application/zip'
    )

@app.route('/final_excel_cleanup/<batch_id>')
@login_required
def final_excel_cleanup(batch_id):
    """Clean up processed files and return to home"""
    # Verify batch ID matches session
    if session.get('final_excel_batch_id') == batch_id:
        processed_files = session.get('final_excel_files', [])
        
        # Delete temp files
        for f in processed_files:
            try:
                if os.path.exists(f['path']):
                    os.remove(f['path'])
            except:
                pass
        
        # Clear session
        session.pop('final_excel_batch_id', None)
        session.pop('final_excel_files', None)
        session.pop('final_excel_format', None)
    
    flash('Processing session cleared.', 'success')
    return redirect(url_for('index'))

@app.route('/final_excel_delete/<batch_id>/<filename>', methods=['DELETE'])
@login_required
def final_excel_delete_file(batch_id, filename):
    """Delete a single processed file from Final Excel Generator"""
    # Verify batch ID matches session
    if session.get('final_excel_batch_id') != batch_id:
        return jsonify({'success': False, 'error': 'Invalid request'})
    
    processed_files = session.get('final_excel_files', [])
    
    # Find and delete the file
    for i, f in enumerate(processed_files):
        if f['unique_filename'] == filename:
            try:
                if os.path.exists(f['path']):
                    os.remove(f['path'])
            except:
                pass
            
            # Remove from session
            processed_files.pop(i)
            session['final_excel_files'] = processed_files
            session.modified = True
            
            return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'File not found'})

@app.route('/final_excel_rename/<batch_id>/<filename>', methods=['POST'])
@login_required
def final_excel_rename_file(batch_id, filename):
    """Rename a processed file from Final Excel Generator"""
    # Verify batch ID matches session
    if session.get('final_excel_batch_id') != batch_id:
        return jsonify({'success': False, 'error': 'Invalid request'})
    
    data = request.get_json()
    new_name = data.get('new_name', '').strip()
    
    if not new_name:
        return jsonify({'success': False, 'error': 'Invalid filename'})
    
    # Sanitize new filename
    new_name = secure_filename(new_name)
    if not new_name:
        return jsonify({'success': False, 'error': 'Invalid filename'})
    
    processed_files = session.get('final_excel_files', [])
    
    # Find and rename the file
    for f in processed_files:
        if f['unique_filename'] == filename:
            f['filename'] = new_name
            session['final_excel_files'] = processed_files
            session.modified = True
            return jsonify({'success': True, 'new_name': new_name})
    
    return jsonify({'success': False, 'error': 'File not found'})

# ----------- Dashboard Route -----------
@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard showing usage statistics and analytics"""
    user_email = session.get('user_id')
    user_role = session.get('role')
    
    # Refresh permissions from database (check_session_validity already does this, but double-check here)
    user = get_user(user_email)
    user_dict = None
    if user:
        user_dict = dict(user) if hasattr(user, 'keys') else user
        # Update session with latest permissions
        session['can_view_dashboard'] = bool(user_dict.get('can_view_dashboard', 0))
        user_role = user_dict.get('role', user_role)  # Update role from DB
    
    # Check if user has permission (superadmin and subsuperadmin always have permission)
    if user_role not in ['superadmin', 'subsuperadmin']:
        if not user_dict or not user_dict.get('can_view_dashboard'):
            flash('Access denied. You do not have permission to view the dashboard.', 'error')
            return redirect(url_for('index'))
    
    # Get dashboard stats
    # Superadmin and subsuperadmin see all stats, regular users see only their own
    stats = get_dashboard_stats(user_email if user_role not in ['superadmin', 'subsuperadmin'] else None)
    
    # Get user usage summary (only for superadmin and subsuperadmin)
    user_summary = None
    if user_role in ['superadmin', 'subsuperadmin']:
        user_summary = get_user_usage_summary()
    
    # Get last login info for current user
    last_login_info = get_last_login(user_email)
    
    return render_template(
        'dashboard.html',
        stats=stats,
        user_summary=user_summary,
        last_login_info=last_login_info,
        is_superadmin=(user_role in ['superadmin', 'subsuperadmin']),
        show_navigation=True
    )

# ----------- Activity Logs Management Routes -----------
@app.route('/admin/activity_logs')
@superadmin_required
def activity_logs():
    """View activity logs - Superadmin only"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    user_filter = request.args.get('user', '')
    action_filter = request.args.get('action', '')
    
    logs = get_activity_logs(
        user_email=user_filter if user_filter else None,
        action_type=action_filter if action_filter else None,
        limit=per_page,
        offset=offset
    )
    
    total_count = get_activity_log_count(
        user_email=user_filter if user_filter else None,
        action_type=action_filter if action_filter else None
    )
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template(
        'activity_logs.html',
        logs=logs,
        page=page,
        total_pages=total_pages,
        user_filter=user_filter,
        action_filter=action_filter,
        show_navigation=True
    )

@app.route('/admin/delete_logs', methods=['POST'])
@superadmin_required
def delete_logs():
    """Delete activity logs - Superadmin only"""
    try:
        action = request.form.get('action')
        
        if action == 'delete_all':
            deleted = clear_all_activity_logs()
            flash(f'Deleted all {deleted} activity logs.', 'success')
        elif action == 'delete_old':
            days = request.form.get('days', 30, type=int)
            deleted = delete_activity_logs(days_old=days)
            flash(f'Deleted {deleted} activity logs older than {days} days.', 'success')
        else:
            flash('Invalid action specified.', 'error')
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'log_deletion', f'Deleted activity logs: {action}', ip_address)
        
    except Exception as e:
        flash(f'Error deleting logs: {str(e)}', 'error')
    
    return redirect(url_for('activity_logs'))

@app.route('/admin/delete_login_history', methods=['POST'])
@superadmin_required
def delete_login_history():
    """Delete login history from dashboard - Superadmin only"""
    try:
        action = request.form.get('action')
        
        if action == 'delete_all':
            # Delete all login history
            from database import get_db_connection
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM login_history')
                deleted_count = cursor.rowcount
                cursor.close()
                flash(f'Deleted all {deleted_count} login history records.', 'success')
            finally:
                conn.close()
        elif action == 'delete_old':
            days = request.form.get('days', 30, type=int)
            # Delete old login history
            from database import get_db_connection
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM login_history 
                    WHERE datetime(login_time) <= datetime('now', '-' || ? || ' days')
                ''', (days,))
                deleted_count = cursor.rowcount
                cursor.close()
                flash(f'Deleted {deleted_count} login records older than {days} days.', 'success')
            finally:
                conn.close()
        else:
            flash('Invalid action specified.', 'error')
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'login_history_deletion', f'Deleted login history: {action}', ip_address)
        
    except Exception as e:
        flash(f'Error deleting login history: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

# ----------- Settings Management Routes -----------
@app.route('/admin/settings')
@superadmin_required
def settings_management():
    """Settings management - Superadmin only"""
    app_settings = get_all_app_settings()
    output_formats = get_all_output_format_settings()
    app_output_formats = get_all_app_output_formats()
    
    # Get app names for display
    app_names = {
        'app1': get_app_setting('app1_name', 'Zoom Attendance Analyzer'),
        'app2': get_app_setting('app2_name', 'Intelligent Record Matcher'),
        'app3': get_app_setting('app3_name', 'Session Report Generator'),
    }
    
    return render_template(
        'settings_management.html',
        app_settings=app_settings,
        output_formats=output_formats,
        app_output_formats=app_output_formats,
        app_names=app_names,
        show_navigation=True
    )

@app.route('/admin/settings/update', methods=['POST'])
@superadmin_required
def update_settings():
    """Update app settings - Superadmin only"""
    try:
        setting_key = request.form.get('setting_key')
        setting_value = request.form.get('setting_value')
        
        if not setting_key:
            flash('Setting key is required.', 'error')
            return redirect(url_for('settings_management'))
        
        set_app_setting(setting_key, setting_value, updated_by=session.get('user_id'))
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'settings_update', f'Updated setting: {setting_key} = {setting_value}', ip_address)
        
        flash(f'Setting "{setting_key}" updated successfully.', 'success')
        
    except Exception as e:
        flash(f'Error updating setting: {str(e)}', 'error')
    
    return redirect(url_for('settings_management'))

@app.route('/admin/settings/create', methods=['POST'])
@superadmin_required
def create_setting():
    """Create new app setting - Superadmin only"""
    try:
        setting_key = request.form.get('setting_key')
        setting_value = request.form.get('setting_value')
        setting_type = request.form.get('setting_type', 'string')
        description = request.form.get('description', '')
        
        if not setting_key:
            flash('Setting key is required.', 'error')
            return redirect(url_for('settings_management'))
        
        success = create_app_setting(setting_key, setting_value, setting_type, description, updated_by=session.get('user_id'))
        
        if success:
            # Log this action
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
            log_activity(session.get('user_id'), 'settings_create', f'Created setting: {setting_key}', ip_address)
            
            flash(f'Setting "{setting_key}" created successfully.', 'success')
        else:
            flash(f'Setting "{setting_key}" already exists.', 'error')
        
    except Exception as e:
        flash(f'Error creating setting: {str(e)}', 'error')
    
    return redirect(url_for('settings_management'))

@app.route('/admin/settings/delete/<setting_key>', methods=['POST'])
@superadmin_required
def delete_setting(setting_key):
    """Delete app setting - Superadmin only"""
    try:
        delete_app_setting(setting_key)
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'settings_delete', f'Deleted setting: {setting_key}', ip_address)
        
        flash(f'Setting "{setting_key}" deleted successfully.', 'success')
        
    except Exception as e:
        flash(f'Error deleting setting: {str(e)}', 'error')
    
    return redirect(url_for('settings_management'))

@app.route('/admin/output_formats/update', methods=['POST'])
@superadmin_required
def update_output_format():
    """Update output format settings - Superadmin only"""
    try:
        user_role = request.form.get('user_role')
        file_format = request.form.get('file_format')
        date_format = request.form.get('date_format')
        time_format = request.form.get('time_format')
        include_header = request.form.get('include_header') == '1'
        custom_header_json = request.form.get('custom_header_json')
        column_order_json = request.form.get('column_order_json')
        
        if not user_role:
            flash('User role is required.', 'error')
            return redirect(url_for('settings_management'))
        
        set_output_format_settings(
            user_role=user_role,
            file_format=file_format,
            date_format=date_format,
            time_format=time_format,
            include_header=include_header,
            custom_header_json=custom_header_json,
            column_order_json=column_order_json,
            updated_by=session.get('user_id')
        )
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'format_update', f'Updated output format for role: {user_role}', ip_address)
        
        flash(f'Output format for "{user_role}" updated successfully.', 'success')
        
    except Exception as e:
        flash(f'Error updating output format: {str(e)}', 'error')
    
    return redirect(url_for('settings_management'))

@app.route('/admin/app_formats/update', methods=['POST'])
@superadmin_required
def update_app_format():
    """Update app-specific output format settings - Superadmin only"""
    try:
        app_name = request.form.get('app_name')
        file_format = request.form.get('file_format')
        date_format = request.form.get('date_format')
        time_format = request.form.get('time_format')
        include_header = request.form.get('include_header') == '1'
        header_title = request.form.get('header_title')
        header_subtitle = request.form.get('header_subtitle')
        include_timestamp = request.form.get('include_timestamp') == '1'
        include_user_info = request.form.get('include_user_info') == '1'
        custom_columns_json = request.form.get('custom_columns_json')
        
        if not app_name:
            flash('App name is required.', 'error')
            return redirect(url_for('settings_management'))
        
        set_app_output_format(
            app_name=app_name,
            file_format=file_format,
            date_format=date_format,
            time_format=time_format,
            include_header=include_header,
            header_title=header_title,
            header_subtitle=header_subtitle,
            include_timestamp=include_timestamp,
            include_user_info=include_user_info,
            custom_columns_json=custom_columns_json
        )
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'app_format_update', f'Updated output format for app: {app_name}', ip_address)
        
        # Get app display name
        app_display = get_app_setting(f'{app_name}_name', app_name)
        flash(f'Output format for "{app_display}" updated successfully.', 'success')
        
    except Exception as e:
        flash(f'Error updating app format: {str(e)}', 'error')
    
    return redirect(url_for('settings_management'))

# ----------- File Management Routes -----------
@app.route('/admin/files')
@superadmin_required
def file_management():
    """File management - Superadmin only"""
    all_files = get_processed_files()
    
    # Get file system stats
    import os
    total_size = 0
    for file in all_files:
        file_path = file['file_path']
        if os.path.exists(file_path):
            total_size += os.path.getsize(file_path)
    
    total_size_mb = total_size / (1024 * 1024)
    
    return render_template(
        'file_management.html',
        files=all_files,
        total_size_mb=total_size_mb,
        show_navigation=True
    )

@app.route('/admin/files/delete/<int:file_id>', methods=['POST'])
@superadmin_required
def delete_file_by_id(file_id):
    """Delete a file - Superadmin only"""
    try:
        # Get file info
        files = get_processed_files()
        file_to_delete = None
        for f in files:
            if f['id'] == file_id:
                file_to_delete = f
                break
        
        if not file_to_delete:
            flash('File not found in database.', 'error')
            return redirect(url_for('file_management'))
        
        # Delete physical file
        import os
        file_path = file_to_delete['file_path']
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Mark as manually deleted in database
        mark_file_manually_deleted(file_path)
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'file_deletion', f'Deleted file: {file_to_delete["file_name"]}', ip_address)
        
        flash(f'File "{file_to_delete["file_name"]}" deleted successfully.', 'success')
        
    except Exception as e:
        flash(f'Error deleting file: {str(e)}', 'error')
    
    return redirect(url_for('file_management'))

@app.route('/admin/files/delete_old', methods=['POST'])
@superadmin_required
def delete_old_files():
    """Delete old files - Superadmin only"""
    try:
        days_old = request.form.get('days_old', 30, type=int)
        deleted_count = 0
        
        # Get all files
        all_files = get_processed_files(include_deleted=False)
        
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        import os
        for file in all_files:
            created_at = datetime.strptime(file['created_at'], '%Y-%m-%d %H:%M:%S')
            if created_at < cutoff_date:
                # Delete physical file
                file_path = file['file_path']
                if os.path.exists(file_path):
                    os.remove(file_path)
                # Mark as deleted
                mark_file_manually_deleted(file_path)
                deleted_count += 1
        
        # Log this action
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        log_activity(session.get('user_id'), 'bulk_file_deletion', f'Deleted {deleted_count} files older than {days_old} days', ip_address)
        
        flash(f'Deleted {deleted_count} files older than {days_old} days.', 'success')
        
    except Exception as e:
        flash(f'Error deleting old files: {str(e)}', 'error')
    
    return redirect(url_for('file_management'))

# ----------- Authentication Routes -----------
@app.route('/logout')
def logout():
    """Logout route to clear session"""
    session.clear()
    flash('You have been logged out successfully.')
    return redirect(url_for('index'))

# ============ Global Error Handlers ============
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    flash('Page not found.', 'error')
    return redirect(url_for('index')), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    flash('An internal error occurred. Please try again or contact support.', 'error')
    return redirect(url_for('index')), 500

@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 errors"""
    flash('Access denied. You do not have permission to access this resource.', 'error')
    return redirect(url_for('index')), 403

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler for unhandled errors"""
    import traceback
    error_trace = traceback.format_exc()
    print(f"Unhandled exception: {error_trace}")
    flash('An unexpected error occurred. Please try again.', 'error')
    return redirect(url_for('index')), 500

if __name__ == '__main__':
    # Initialize the database
    init_db()
    print("Starting Attendance Tools Suite...")
    print("Open your web browser and go to: http://localhost:5000")
    print("\n⚠️  NOTE: This is the development server. For production, use a WSGI server.")
    print("   For PythonAnywhere, use the wsgi.py file instead.\n")
    
    # IMPORTANT: debug=False for production security
    # Debug mode should ONLY be enabled for local development
    # Enabling debug in production exposes security vulnerabilities:
    # - Interactive debugger allows code execution
    # - Detailed error pages reveal sensitive information
    # - Auto-reload impacts performance
    import os
    import warnings
    import logging
    import sys
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Suppress the Werkzeug development server warning for local testing
    # This warning is correct - don't use app.run() in production!
    # For production deployment, use: gunicorn, waitress, or wsgi.py (PythonAnywhere)
    
    # Method 1: Suppress Werkzeug logger warnings
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    
    # Method 2: Suppress Python warnings
    warnings.filterwarnings("ignore", message=".*development server.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="werkzeug")
    
    # Method 3: Suppress Flask CLI banner (if available)
    try:
        import flask.cli
        flask.cli.show_server_banner = lambda *args: None
    except (AttributeError, ImportError):
        pass
    
    app.run(debug=debug_mode, host='0.0.0.0')