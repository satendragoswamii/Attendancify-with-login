import sqlite3
import os
from datetime import datetime

# ============================================================================
# CRITICAL FIX: Use absolute path to prevent "unable to open database file" errors
# This ensures the database is found regardless of current working directory
# ============================================================================
DATABASE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'attendancify.db'))

def get_db_connection():
    """
    CRITICAL: Centralized database connection helper to prevent connection leaks.
    
    This function is the ONLY way to get a database connection throughout the app.
    
    Key fixes:
    1. Uses absolute path to prevent path resolution errors
    2. timeout=30.0 prevents hanging connections
    3. check_same_thread=False allows Flask's multi-threaded environment
    4. isolation_level=None enables autocommit mode (safer for concurrent access)
    5. Returns a connection that MUST be closed by caller using try/finally
    
    IMPORTANT: Every caller MUST close the connection in a finally block:
        conn = get_db_connection()
        try:
            # Use connection
        finally:
            conn.close()
    """
    try:
        conn = sqlite3.connect(
            DATABASE,
            timeout=30.0,  # Wait up to 30 seconds if database is locked
            check_same_thread=False,  # Required for Flask multi-threading
            isolation_level=None  # Autocommit mode for safer concurrent access
        )
        # Row factory allows dict-like access to query results
        conn.row_factory = sqlite3.Row
        # Disable foreign keys to prevent cascade issues (as per original design)
        conn.execute('PRAGMA foreign_keys=OFF')
        # Enable WAL mode for better concurrency (safe for production)
        conn.execute('PRAGMA journal_mode=WAL')
        return conn
    except sqlite3.Error as e:
        print(f"CRITICAL DATABASE ERROR: Failed to connect to {DATABASE}: {e}")
        raise

def get_db():
    """
    DEPRECATED: Use get_db_connection() instead.
    Kept for backward compatibility only.
    """
    return get_db_connection()

def init_db():
    """Initialize the database with required tables"""
    # CRITICAL FIX: Use centralized connection with proper cleanup
    conn = get_db_connection()
    try:
        # Create file processing logs table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS file_processing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                file_name TEXT NOT NULL,
                processing_type TEXT NOT NULL,
                file_size INTEGER,
                processing_time REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
            )
        ''')
        
        # Create users table for persistent storage
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                must_change_password BOOLEAN DEFAULT 1,
                password_plain TEXT,
                first_name TEXT,
                last_name TEXT,
                can_use_batch_matching BOOLEAN DEFAULT 0,
                created_by TEXT,
                can_manage_roles BOOLEAN DEFAULT 0,
                can_manage_batch_matching BOOLEAN DEFAULT 0
            )
        ''')

        # Ensure new columns exist for older databases
        try:
            conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_use_batch_matching BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN created_by TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_manage_roles BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_manage_batch_matching BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_manage_batches BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_access_processed_files BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN can_view_dashboard BOOLEAN DEFAULT 0")
        except Exception:
            pass
        try:
            # NEW: Add hidden column for hide user feature
            conn.execute("ALTER TABLE users ADD COLUMN hidden BOOLEAN DEFAULT 0")
        except Exception:
            pass

        # Create login_history table for tracking user logins and IP addresses
        conn.execute('''
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                ip_address TEXT,
                login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                logout_time DATETIME,
                session_duration INTEGER,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
            )
        ''')
        
        # Create index for faster queries
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_login_history_user_email ON login_history(user_email)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_login_history_login_time ON login_history(login_time)')
        except Exception:
            pass

        # Batches for Smart Matcher master data
        conn.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_by TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(email) ON DELETE SET NULL
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS batch_students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
            )
        ''')

        # Create processed_files table for tracking processed files
        conn.execute('''
            CREATE TABLE IF NOT EXISTS processed_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                processing_type TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                eligible_for_deletion_at DATETIME,
                manually_deleted BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
            )
        ''')

        # Create processed_files_permissions table for access control
        conn.execute('''
            CREATE TABLE IF NOT EXISTS processed_files_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                user_email TEXT NOT NULL,
                granted_by TEXT NOT NULL,
                granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES processed_files(id) ON DELETE CASCADE,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE,
                FOREIGN KEY (granted_by) REFERENCES users(email) ON DELETE CASCADE,
                UNIQUE(file_id, user_email)
            )
        ''')
        
        # Create excluded_participants table for filtering attendance
        conn.execute('''
            CREATE TABLE IF NOT EXISTS excluded_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT NOT NULL,
                identifier_type TEXT NOT NULL DEFAULT 'name',
                added_by TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(identifier, identifier_type)
            )
        ''')

        # Create app_settings table for superadmin configuration
        conn.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT NOT NULL UNIQUE,
                setting_value TEXT,
                setting_type TEXT DEFAULT 'string',
                description TEXT,
                updated_by TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create output_format_settings table for user-specific file format configurations
        conn.execute('''
            CREATE TABLE IF NOT EXISTS output_format_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_role TEXT NOT NULL UNIQUE,
                file_format TEXT DEFAULT 'xlsx',
                date_format TEXT DEFAULT '%Y-%m-%d',
                time_format TEXT DEFAULT '%H:%M:%S',
                include_header BOOLEAN DEFAULT 1,
                custom_header_json TEXT,
                column_order_json TEXT,
                created_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create activity_logs table for comprehensive logging
        conn.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_description TEXT,
                ip_address TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
            )
        ''')

        # Create index for faster log queries
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_logs_user_email ON activity_logs(user_email)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_activity_logs_action_type ON activity_logs(action_type)')
        except Exception:
            pass

        # Insert default app settings if not exists
        default_settings = [
            ('max_upload_size_mb', '50', 'integer', 'Maximum file upload size in MB'),
            ('session_timeout_minutes', '60', 'integer', 'Session timeout in minutes'),
            ('auto_delete_files_after_hours', '24', 'integer', 'Auto delete processed files after hours'),
            ('enable_file_auto_deletion', '1', 'boolean', 'Enable automatic file deletion'),
            ('max_concurrent_uploads', '5', 'integer', 'Maximum concurrent file uploads'),
            ('enable_user_registration', '0', 'boolean', 'Allow user self-registration'),
            ('app1_name', 'Zoom Attendance Analyzer', 'string', 'Custom name for Attendance Generator app'),
            ('app2_name', 'Intelligent Record Matcher', 'string', 'Custom name for Smart Matcher app'),
            ('app3_name', 'Session Report Generator', 'string', 'Custom name for Final Excel Generator app'),
        ]
        
        for key, value, stype, desc in default_settings:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO app_settings (setting_key, setting_value, setting_type, description)
                    VALUES (?, ?, ?, ?)
                ''', (key, value, stype, desc))
            except Exception:
                pass

        # Insert default output format settings for each role
        default_formats = [
            ('user', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1),
            ('admin', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1),
            ('superadmin', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1),
            ('subsuperadmin', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1),
        ]
        
        for role, fmt, date_fmt, time_fmt, header in default_formats:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO output_format_settings 
                    (user_role, file_format, date_format, time_format, include_header)
                    VALUES (?, ?, ?, ?, ?)
                ''', (role, fmt, date_fmt, time_fmt, header))
            except Exception:
                pass

        # Create app-specific output format settings table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS app_output_formats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL UNIQUE,
                file_format TEXT DEFAULT 'xlsx',
                date_format TEXT DEFAULT '%Y-%m-%d',
                time_format TEXT DEFAULT '%H:%M:%S',
                include_header BOOLEAN DEFAULT 1,
                header_title TEXT,
                header_subtitle TEXT,
                include_timestamp BOOLEAN DEFAULT 1,
                include_user_info BOOLEAN DEFAULT 1,
                custom_columns_json TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Insert default app-specific formats
        default_app_formats = [
            ('app1', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1, 'Zoom Attendance Report', 'Generated from Zoom Meeting Data', 1, 1),
            ('app2', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1, 'Matched Records Report', 'Intelligent Record Matching Results', 1, 1),
            ('app3', 'xlsx', '%Y-%m-%d', '%H:%M:%S', 1, 'Session Report', 'Individual Session Analysis', 1, 1),
        ]
        
        for app, fmt, date_fmt, time_fmt, header, title, subtitle, timestamp, user_info in default_app_formats:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO app_output_formats 
                    (app_name, file_format, date_format, time_format, include_header, 
                     header_title, header_subtitle, include_timestamp, include_user_info)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (app, fmt, date_fmt, time_fmt, header, title, subtitle, timestamp, user_info))
            except Exception:
                pass

    finally:
        # CRITICAL: Always close connection to prevent file descriptor leaks
        conn.close()

def log_file_processing(user_email, file_name, processing_type, file_size=None, processing_time=None):
    """Log a file processing event"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO file_processing_logs 
            (user_email, file_name, processing_type, file_size, processing_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_email, file_name, processing_type, file_size, processing_time))
    finally:
        conn.close()

def get_user_processing_stats(user_email=None):
    """Get file processing statistics for a user or all users - Optimized"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Create index if it doesn't exist
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_processing_logs_user_email ON file_processing_logs(user_email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_processing_logs_timestamp ON file_processing_logs(timestamp)')
        except Exception:
            pass
        
        if user_email:
            cursor.execute('''
                SELECT * FROM file_processing_logs 
                WHERE user_email = ?
                ORDER BY timestamp DESC
            ''', (user_email,))
        else:
            cursor.execute('''
                SELECT * FROM file_processing_logs 
                ORDER BY timestamp DESC
            ''')
        
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_processing_summary():
    """Get a summary of processing statistics by user"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                user_email,
                COUNT(*) as total_files_processed,
                SUM(file_size) as total_file_size,
                AVG(processing_time) as avg_processing_time,
                MIN(timestamp) as first_processing,
                MAX(timestamp) as last_processing
            FROM file_processing_logs
            GROUP BY user_email
            ORDER BY total_files_processed DESC
        ''')
        
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def create_user(email, password_hash, role, expires_at=None, must_change_password=True, password_plain=None, first_name=None, last_name=None, can_use_batch_matching=False, created_by=None, can_manage_roles=False, can_manage_batch_matching=False, can_manage_batches=False, can_access_processed_files=False, can_view_dashboard=False):
    """Create a new user in the database"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO users (email, password_hash, role, expires_at, must_change_password, password_plain, first_name, last_name, can_use_batch_matching, created_by, can_manage_roles, can_manage_batch_matching, can_manage_batches, can_access_processed_files, can_view_dashboard)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (email, password_hash, role, expires_at, must_change_password, password_plain, first_name, last_name, int(bool(can_use_batch_matching)), created_by, int(bool(can_manage_roles)), int(bool(can_manage_batch_matching)), int(bool(can_manage_batches)), int(bool(can_access_processed_files)), int(bool(can_view_dashboard))))
    finally:
        conn.close()

def get_user(email):
    """Get user data from database"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def update_user(email, **kwargs):
    """Update user data in database"""
    if not kwargs:
        return
    
    conn = get_db_connection()
    try:
        set_clause = ', '.join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [email]
        
        conn.execute(f'UPDATE users SET {set_clause} WHERE email = ?', values)
    finally:
        conn.close()

def delete_user(email):
    """Delete user from database"""
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM users WHERE email = ?', (email,))
    finally:
        conn.close()

def get_all_users(include_hidden=False):
    """Get all users from database, optionally excluding hidden users"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if include_hidden:
            cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
        else:
            # Exclude hidden users from regular views
            cursor.execute('SELECT * FROM users WHERE hidden = 0 OR hidden IS NULL ORDER BY created_at DESC')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def search_users(query, limit=10):
    """Search users by partial email, first name, or last name (case-insensitive)."""
    pattern = f"%{query.strip()}%"
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT email, first_name, last_name, role
            FROM users
            WHERE LOWER(email) LIKE LOWER(?)
               OR LOWER(COALESCE(first_name, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(last_name, '')) LIKE LOWER(?)
            ORDER BY created_at DESC
            LIMIT ?
        ''', (pattern, pattern, pattern, limit))
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()


# -------- Batch & Batch Student Helpers (for Smart Matcher) --------

def create_batch(name, description, created_by):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO batches (name, description, created_by) VALUES (?, ?, ?)', (name, description, created_by))
        last_id = cursor.lastrowid
        cursor.close()  # CRITICAL: Close cursor before returning
        return last_id
    finally:
        conn.close()


def update_batch(batch_id, name=None, description=None):
    updates = {}
    if name is not None:
        updates['name'] = name
    if description is not None:
        updates['description'] = description
    if not updates:
        return
    conn = get_db_connection()
    try:
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [batch_id]
        conn.execute(f'UPDATE batches SET {set_clause} WHERE id = ?', values)
    finally:
        conn.close()


def delete_batch(batch_id):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM batches WHERE id = ?', (batch_id,))
    finally:
        conn.close()


def get_batches():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # CHANGED: Sort batches alphabetically by name (A-Z) for easier finding
        cursor.execute('SELECT * FROM batches ORDER BY name ASC')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()


def get_batch(batch_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM batches WHERE id = ?', (batch_id,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()


def add_student_to_batch(batch_id, name, email):
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO batch_students (batch_id, name, email) VALUES (?, ?, ?)', (batch_id, name, email))
    finally:
        conn.close()


def update_batch_student(student_id, name=None, email=None):
    updates = {}
    if name is not None:
        updates['name'] = name
    if email is not None:
        updates['email'] = email
    if not updates:
        return
    conn = get_db_connection()
    try:
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [student_id]
        conn.execute(f'UPDATE batch_students SET {set_clause} WHERE id = ?', values)
    finally:
        conn.close()


def delete_batch_student(student_id):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM batch_students WHERE id = ?', (student_id,))
    finally:
        conn.close()


def get_batch_students(batch_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM batch_students WHERE batch_id = ? ORDER BY name ASC', (batch_id,))
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()


def get_all_batch_students_with_batches():
    """Return all students joined with their batches, for full export."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.id AS batch_id, b.name AS batch_name, s.id AS student_id,
                   s.name AS student_name, s.email AS student_email
            FROM batch_students s
            JOIN batches b ON s.batch_id = b.id
            ORDER BY b.name ASC, s.name ASC
        ''')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def ensure_superadmin_exists():
    """Ensure superadmin user exists, create if not"""
    existing = get_user('superadmin@attendancify.com')
    if not existing:
        import hashlib
        password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        create_user(
            email='superadmin@attendancify.com',
            password_hash=password_hash,
            role='superadmin',
            expires_at=None,
            must_change_password=False,
            password_plain='admin123',
            first_name='Super',
            last_name='Admin',
            can_manage_roles=True,
            can_manage_batch_matching=True
        )
        return True
    return False

# -------- Processed Files Management --------

def register_processed_file(file_path, file_name, user_email, processing_type, eligible_for_deletion_at=None):
    """Register a processed file in the database"""
    conn = get_db_connection()
    try:
        try:
            conn.execute('''
                INSERT OR REPLACE INTO processed_files 
                (file_path, file_name, user_email, processing_type, eligible_for_deletion_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (file_path, file_name, user_email, processing_type, eligible_for_deletion_at))
            return True
        except Exception as e:
            print(f"Error registering processed file: {e}")
            return False
    finally:
        conn.close()

def get_processed_files(user_email=None, processing_type=None, include_deleted=False):
    """Get processed files, optionally filtered by user and type - Optimized"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Create index if it doesn't exist (for faster queries)
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processed_files_user_email ON processed_files(user_email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processed_files_processing_type ON processed_files(processing_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processed_files_created_at ON processed_files(created_at)')
        except Exception:
            pass
        
        query = 'SELECT * FROM processed_files WHERE 1=1'
        params = []
        
        if not include_deleted:
            query += ' AND manually_deleted = 0'
        
        if user_email:
            query += ' AND user_email = ?'
            params.append(user_email)
        
        if processing_type:
            query += ' AND processing_type = ?'
            params.append(processing_type)
        
        query += ' ORDER BY created_at DESC'
        
        cursor.execute(query, params)
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_processed_file_by_path(file_path):
    """Get a processed file by its path"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM processed_files WHERE file_path = ?', (file_path,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def mark_file_eligible_for_deletion(file_path, eligible_at):
    """Mark a file as eligible for deletion at a specific time"""
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE processed_files 
            SET eligible_for_deletion_at = ?
            WHERE file_path = ?
        ''', (eligible_at, file_path))
    finally:
        conn.close()

def mark_file_manually_deleted(file_path):
    """Mark a file as manually deleted"""
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE processed_files 
            SET manually_deleted = 1
            WHERE file_path = ?
        ''', (file_path,))
    finally:
        conn.close()

def update_processed_file_name(file_id, new_name):
    """Update the display name of a processed file"""
    conn = get_db_connection()
    try:
        try:
            conn.execute('''
                UPDATE processed_files 
                SET file_name = ?
                WHERE id = ?
            ''', (new_name, file_id))
            return True
        except Exception as e:
            print(f"Error updating file name: {e}")
            return False
    finally:
        conn.close()

def get_files_eligible_for_auto_deletion():
    """Get files that are eligible for automatic deletion (15 minutes after eligibility time)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Files eligible for deletion are those where eligible_for_deletion_at is not null
        # and was 15+ minutes ago, and not manually deleted
        # Using datetime comparison with proper format
        cursor.execute('''
            SELECT * FROM processed_files 
            WHERE eligible_for_deletion_at IS NOT NULL
            AND datetime(eligible_for_deletion_at) <= datetime('now', '-15 minutes')
            AND manually_deleted = 0
        ''')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def permanently_delete_old_records(days_old=30):
    """Permanently remove database records for files that were deleted more than X days ago"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Delete records that were marked as deleted more than X days ago
        # Also delete associated permissions
        deleted_count = 0
        try:
            # First, get file IDs that will be deleted
            cursor.execute('''
                SELECT id FROM processed_files 
                WHERE manually_deleted = 1
                AND datetime(created_at) <= datetime('now', '-' || ? || ' days')
            ''', (days_old,))
            file_ids = [row[0] for row in cursor.fetchall()]
            
            if file_ids:
                # Delete associated permissions first
                placeholders = ','.join('?' * len(file_ids))
                cursor.execute(f'''
                    DELETE FROM processed_files_permissions 
                    WHERE file_id IN ({placeholders})
                ''', file_ids)
                
                # Then delete the file records
                cursor.execute(f'''
                    DELETE FROM processed_files 
                    WHERE id IN ({placeholders})
                ''', file_ids)
                
                deleted_count = len(file_ids)
        except Exception as e:
            print(f"Error permanently deleting old records: {e}")
        finally:
            cursor.close()  # CRITICAL: Close cursor
        
        return deleted_count
    finally:
        conn.close()

def grant_file_access(file_id, user_email, granted_by):
    """Grant a user access to a processed file"""
    conn = get_db_connection()
    try:
        try:
            conn.execute('''
                INSERT OR REPLACE INTO processed_files_permissions 
                (file_id, user_email, granted_by)
                VALUES (?, ?, ?)
            ''', (file_id, user_email, granted_by))
            return True
        except Exception as e:
            print(f"Error granting file access: {e}")
            return False
    finally:
        conn.close()

def revoke_file_access(file_id, user_email):
    """Revoke a user's access to a processed file"""
    conn = get_db_connection()
    try:
        conn.execute('''
            DELETE FROM processed_files_permissions 
            WHERE file_id = ? AND user_email = ?
        ''', (file_id, user_email))
    finally:
        conn.close()

def get_file_permissions(file_id):
    """Get all permissions for a file"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM processed_files_permissions 
            WHERE file_id = ?
        ''', (file_id,))
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def can_user_access_file(file_id, user_email):
    """Check if a user can access a file (owner, superadmin, or has permission)"""
    file = None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM processed_files WHERE id = ?', (file_id,))
        file = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor
    finally:
        conn.close()
    
    if not file:
        return False
    
    # Owner can always access
    if file['user_email'] == user_email:
        return True
    
    # Check if user is superadmin
    user = get_user(user_email)
    if user and user.get('role') == 'superadmin':
        return True
    
    # Check if user has explicit permission
    permissions = get_file_permissions(file_id)
    for perm in permissions:
        if perm['user_email'] == user_email:
            return True
    
    return False

# -------- Login History & Dashboard Functions --------

def log_user_login(user_email, ip_address):
    """Log a user login with IP address"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO login_history (user_email, ip_address, login_time)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_email, ip_address))
    finally:
        conn.close()

def get_last_login(user_email):
    """Get the last login time and IP for a user"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT login_time, ip_address 
            FROM login_history 
            WHERE user_email = ? 
            ORDER BY login_time DESC 
            LIMIT 1
        ''', (user_email,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_user_login_history(user_email=None, limit=50):
    """Get login history for a user or all users"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if user_email:
            cursor.execute('''
                SELECT * FROM login_history 
                WHERE user_email = ? 
                ORDER BY login_time DESC 
                LIMIT ?
            ''', (user_email, limit))
        else:
            cursor.execute('''
                SELECT * FROM login_history 
                ORDER BY login_time DESC 
                LIMIT ?
            ''', (limit,))
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_dashboard_stats(user_email=None):
    """Get dashboard statistics for a user or all users - Optimized with indexes"""
    conn = get_db_connection()
    try:
        stats = {}
        
        # Time saved calculation constants (in minutes)
        TIME_SAVED_ATTENDANCE = 7  # Manual attendance creation
        TIME_SAVED_PA_STATUS = 7   # Manual P/A status marking
        TIME_SAVED_MATCHING = 8     # Manual matching
        TOTAL_TIME_SAVED_PER_OPERATION = TIME_SAVED_ATTENDANCE + TIME_SAVED_PA_STATUS + TIME_SAVED_MATCHING
        
        cursor = conn.cursor()
        
        # Get processing stats - Filter out hidden users' activity
        if user_email:
            cursor.execute('''
                SELECT 
                    processing_type,
                    COUNT(*) as count,
                    SUM(file_size) as total_size,
                    AVG(processing_time) as avg_time
                FROM file_processing_logs 
                WHERE user_email = ?
                GROUP BY processing_type
            ''', (user_email,))
            processing_stats = cursor.fetchall()
            
            cursor.execute('''
                SELECT COUNT(*) as total_files
                FROM file_processing_logs 
                WHERE user_email = ?
            ''', (user_email,))
            total_files = cursor.fetchone()['total_files']
        else:
            # Exclude activity from hidden users
            cursor.execute('''
                SELECT 
                    processing_type,
                    COUNT(*) as count,
                    SUM(file_size) as total_size,
                    AVG(processing_time) as avg_time
                FROM file_processing_logs fpl
                WHERE user_email NOT IN (
                    SELECT email FROM users WHERE hidden = 1
                )
                GROUP BY processing_type
            ''')
            processing_stats = cursor.fetchall()
            
            # Exclude activity from hidden users
            cursor.execute('''
                SELECT COUNT(*) as total_files 
                FROM file_processing_logs 
                WHERE user_email NOT IN (
                    SELECT email FROM users WHERE hidden = 1
                )
            ''')
            total_files = cursor.fetchone()['total_files']
        
        # Calculate time saved
        # Attendance Generator saves: 7 min (attendance) + 7 min (P/A status) = 14 minutes
        # Smart Matcher saves: 8 minutes (matching)
        total_time_saved = 0
        for stat in processing_stats:
            if stat['processing_type'] == 'attendance_generation':
                # Attendance Generator: saves 14 minutes (7+7)
                total_time_saved += stat['count'] * (TIME_SAVED_ATTENDANCE + TIME_SAVED_PA_STATUS)
            elif stat['processing_type'] == 'attendance_matching':
                # Smart Matcher: saves 8 minutes
                total_time_saved += stat['count'] * TIME_SAVED_MATCHING
        
        stats['total_files_processed'] = total_files
        stats['processing_stats'] = [dict(s) for s in processing_stats]
        stats['total_time_saved_minutes'] = total_time_saved
        stats['total_time_saved_hours'] = round(total_time_saved / 60, 2)
        stats['total_time_saved_days'] = round(total_time_saved / (60 * 24), 2)
        
        # Get user activity stats
        if user_email:
            cursor.execute('''
                SELECT COUNT(*) as login_count,
                       MAX(login_time) as last_login,
                       MIN(login_time) as first_login
                FROM login_history 
                WHERE user_email = ?
            ''', (user_email,))
        else:
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT user_email) as total_users,
                    COUNT(*) as total_logins,
                    MAX(login_time) as last_login
                FROM login_history
            ''')
        
        activity_stats = cursor.fetchone()
        stats['activity'] = dict(activity_stats)
        
        # Get recent activity - Exclude deleted and hidden users
        if user_email:
            cursor.execute('''
                SELECT * FROM login_history 
                WHERE user_email = ? 
                ORDER BY login_time DESC 
                LIMIT 10
            ''', (user_email,))
        else:
            # Only show logins from existing, non-hidden users
            cursor.execute('''
                SELECT lh.*, u.first_name, u.last_name 
                FROM login_history lh
                INNER JOIN users u ON lh.user_email = u.email
                WHERE (u.hidden = 0 OR u.hidden IS NULL)
                ORDER BY lh.login_time DESC 
                LIMIT 20
            ''')
        
        stats['recent_logins'] = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()  # CRITICAL: Close cursor before returning
        return stats
    finally:
        conn.close()

def get_user_usage_summary():
    """Get usage summary for all users - Optimized query (excludes hidden users)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Exclude superadmin and hidden users from usage summary
        cursor.execute('''
            SELECT 
                u.email,
                u.first_name,
                u.last_name,
                u.role,
                COUNT(DISTINCT fpl.id) as files_processed,
                MAX(fpl.timestamp) as last_processed,
                MAX(lh.login_time) as last_login,
                MAX(lh.ip_address) as last_ip
            FROM users u
            LEFT JOIN file_processing_logs fpl ON u.email = fpl.user_email
            LEFT JOIN login_history lh ON u.email = lh.user_email
            WHERE u.email != 'superadmin@attendancify.com'
                AND (u.hidden = 0 OR u.hidden IS NULL)
            GROUP BY u.email, u.first_name, u.last_name, u.role
            ORDER BY files_processed DESC, last_login DESC
        ''')
        
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

# ============ Excluded Participants Functions ============

def add_excluded_participant(identifier, identifier_type, added_by):
    """Add a participant to the exclusion list"""
    conn = get_db_connection()
    try:
        try:
            conn.execute('''
                INSERT INTO excluded_participants (identifier, identifier_type, added_by)
                VALUES (?, ?, ?)
            ''', (identifier.strip().lower(), identifier_type, added_by))
            return True
        except sqlite3.IntegrityError:
            return False  # Already exists
        except Exception as e:
            print(f"Error adding excluded participant: {e}")
            return False
    finally:
        conn.close()

def remove_excluded_participant(participant_id):
    """Remove a participant from the exclusion list"""
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM excluded_participants WHERE id = ?', (participant_id,))
    finally:
        conn.close()

def get_excluded_participants():
    """Get all excluded participants"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM excluded_participants 
            ORDER BY identifier_type, identifier
        ''')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_excluded_identifiers():
    """Get excluded identifiers as sets for quick lookup"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT identifier, identifier_type FROM excluded_participants')
        rows = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor
        
        excluded_names = set()
        excluded_emails = set()
        
        for row in rows:
            if row['identifier_type'] == 'name':
                excluded_names.add(row['identifier'].lower())
            else:
                excluded_emails.add(row['identifier'].lower())
        
        return excluded_names, excluded_emails
    finally:
        conn.close()

def bulk_add_excluded_participants(identifiers, identifier_type, added_by):
    """Add multiple participants to the exclusion list"""
    conn = get_db_connection()
    try:
        added = 0
        for identifier in identifiers:
            identifier = identifier.strip()
            if identifier:
                try:
                    conn.execute('''
                        INSERT OR IGNORE INTO excluded_participants (identifier, identifier_type, added_by)
                        VALUES (?, ?, ?)
                    ''', (identifier.lower(), identifier_type, added_by))
                    added += 1
                except Exception:
                    pass
        return added
    finally:
        conn.close()

def update_excluded_participant(participant_id, identifier, identifier_type):
    """Update an excluded participant's identifier"""
    conn = get_db_connection()
    try:
        try:
            # Check if the new identifier already exists (excluding current record)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM excluded_participants 
                WHERE identifier = ? AND identifier_type = ? AND id != ?
            ''', (identifier.strip().lower(), identifier_type, participant_id))
            if cursor.fetchone():
                cursor.close()
                return False  # Duplicate exists
            
            # Update the record
            conn.execute('''
                UPDATE excluded_participants 
                SET identifier = ?, identifier_type = ?
                WHERE id = ?
            ''', (identifier.strip().lower(), identifier_type, participant_id))
            cursor.close()  # CRITICAL: Close cursor
            return True
        except Exception as e:
            print(f"Error updating excluded participant: {e}")
            return False
    finally:
        conn.close()

# ============ App Settings Functions ============

def get_app_setting(key, default=None):
    """Get an app setting value"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM app_settings WHERE setting_key = ?', (key,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor
        
        if result:
            value = result['setting_value']
            setting_type = result['setting_type']
            # Convert value based on type
            if setting_type == 'integer':
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default
            elif setting_type == 'boolean':
                return value in ('1', 'true', 'True', True, 1)
            elif setting_type == 'float':
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default
            return value
        return default
    finally:
        conn.close()

def set_app_setting(key, value, updated_by=None):
    """Set or update an app setting"""
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE app_settings 
            SET setting_value = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE setting_key = ?
        ''', (str(value), updated_by, key))
    finally:
        conn.close()

def get_all_app_settings():
    """Get all app settings"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM app_settings ORDER BY setting_key')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def create_app_setting(key, value, setting_type='string', description='', updated_by=None):
    """Create a new app setting"""
    conn = get_db_connection()
    try:
        try:
            conn.execute('''
                INSERT INTO app_settings (setting_key, setting_value, setting_type, description, updated_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (key, str(value), setting_type, description, updated_by))
            return True
        except sqlite3.IntegrityError:
            return False  # Key already exists
    finally:
        conn.close()

def delete_app_setting(key):
    """Delete an app setting"""
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM app_settings WHERE setting_key = ?', (key,))
    finally:
        conn.close()

# ============ Output Format Settings Functions ============

def get_output_format_settings(user_role):
    """Get output format settings for a user role"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM output_format_settings WHERE user_role = ?', (user_role,))
        result = cursor.fetchone()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def set_output_format_settings(user_role, file_format=None, date_format=None, time_format=None, 
                                include_header=None, custom_header_json=None, column_order_json=None, updated_by=None):
    """Set or update output format settings for a user role"""
    updates = {}
    if file_format is not None:
        updates['file_format'] = file_format
    if date_format is not None:
        updates['date_format'] = date_format
    if time_format is not None:
        updates['time_format'] = time_format
    if include_header is not None:
        updates['include_header'] = int(bool(include_header))
    if custom_header_json is not None:
        updates['custom_header_json'] = custom_header_json
    if column_order_json is not None:
        updates['column_order_json'] = column_order_json
    
    if not updates:
        return False
    
    updates['updated_at'] = datetime.now().isoformat()
    
    conn = get_db_connection()
    try:
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [user_role]
        conn.execute(f'UPDATE output_format_settings SET {set_clause} WHERE user_role = ?', values)
        return True
    finally:
        conn.close()

def get_all_output_format_settings():
    """Get all output format settings"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM output_format_settings ORDER BY user_role')
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

# ============ Activity Log Functions ============

def log_activity(user_email, action_type, action_description='', ip_address=None, metadata_json=None):
    """Log an activity"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO activity_logs (user_email, action_type, action_description, ip_address, metadata_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_email, action_type, action_description, ip_address, metadata_json))
    finally:
        conn.close()

def get_activity_logs(user_email=None, action_type=None, limit=100, offset=0):
    """Get activity logs with optional filters"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        query = 'SELECT * FROM activity_logs WHERE 1=1'
        params = []
        
        if user_email:
            query += ' AND user_email = ?'
            params.append(user_email)
        
        if action_type:
            query += ' AND action_type = ?'
            params.append(action_type)
        
        query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        result = cursor.fetchall()
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def get_activity_log_count(user_email=None, action_type=None):
    """Get total count of activity logs"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        query = 'SELECT COUNT(*) FROM activity_logs WHERE 1=1'
        params = []
        
        if user_email:
            query += ' AND user_email = ?'
            params.append(user_email)
        
        if action_type:
            query += ' AND action_type = ?'
            params.append(action_type)
        
        cursor.execute(query, params)
        result = cursor.fetchone()[0]
        cursor.close()  # CRITICAL: Close cursor before returning
        return result
    finally:
        conn.close()

def delete_activity_logs(days_old=None, user_email=None):
    """Delete activity logs older than specified days or for a specific user"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        if days_old:
            cursor.execute('''
                DELETE FROM activity_logs 
                WHERE datetime(timestamp) <= datetime('now', '-' || ? || ' days')
            ''', (days_old,))
        elif user_email:
            cursor.execute('DELETE FROM activity_logs WHERE user_email = ?', (user_email,))
        else:
            # Delete all logs
            cursor.execute('DELETE FROM activity_logs')
        
        deleted_count = cursor.rowcount
        cursor.close()  # CRITICAL: Close cursor
        return deleted_count
    finally:
        conn.close()

def clear_all_activity_logs():
    """Clear all activity logs"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM activity_logs')
        deleted_count = cursor.rowcount
        cursor.close()  # CRITICAL: Close cursor
        return deleted_count
    finally:
        conn.close()

# ============ App-Specific Output Format Functions ============

def get_app_output_format(app_name):
    """Get output format settings for a specific app (app1, app2, app3)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM app_output_formats WHERE app_name = ?', (app_name,))
        result = cursor.fetchone()
        cursor.close()
        return result
    finally:
        conn.close()

def set_app_output_format(app_name, file_format=None, date_format=None, time_format=None, 
                          include_header=None, header_title=None, header_subtitle=None,
                          include_timestamp=None, include_user_info=None, custom_columns_json=None):
    """Set or update output format settings for a specific app"""
    updates = {}
    if file_format is not None:
        updates['file_format'] = file_format
    if date_format is not None:
        updates['date_format'] = date_format
    if time_format is not None:
        updates['time_format'] = time_format
    if include_header is not None:
        updates['include_header'] = int(bool(include_header))
    if header_title is not None:
        updates['header_title'] = header_title
    if header_subtitle is not None:
        updates['header_subtitle'] = header_subtitle
    if include_timestamp is not None:
        updates['include_timestamp'] = int(bool(include_timestamp))
    if include_user_info is not None:
        updates['include_user_info'] = int(bool(include_user_info))
    if custom_columns_json is not None:
        updates['custom_columns_json'] = custom_columns_json
    
    if not updates:
        return False
    
    updates['updated_at'] = datetime.now().isoformat()
    
    conn = get_db_connection()
    try:
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [app_name]
        conn.execute(f'UPDATE app_output_formats SET {set_clause} WHERE app_name = ?', values)
        return True
    finally:
        conn.close()

def get_all_app_output_formats():
    """Get all app-specific output format settings"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM app_output_formats ORDER BY app_name')
        result = cursor.fetchall()
        cursor.close()
        return result
    finally:
        conn.close()
