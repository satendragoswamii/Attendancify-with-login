import sqlite3
import hashlib

def reset_superadmin():
    # Connect to the database
    conn = sqlite3.connect('attendancify.db')
    cursor = conn.cursor()
    
    try:
        # Delete existing superadmin if exists
        cursor.execute("DELETE FROM users WHERE email = 'superadmin@attendancify.com'")
        
        # Create new superadmin
        password = 'admin123'
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, must_change_password, password_plain)
            VALUES (?, ?, 'superadmin', 0, ?)
        """, ('superadmin@attendancify.com', password_hash, password))
        
        conn.commit()
        print("\n=== SUPERADMIN ACCOUNT RESET ===")
        print("Email: superadmin@attendancify.com")
        print("Password: admin123")
        print("==============================\n")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    reset_superadmin()
