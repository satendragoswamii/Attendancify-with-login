import sqlite3

def check_and_fix_superadmin():
    # Connect to the database
    conn = sqlite3.connect('attendancify.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check if superadmin exists and get current role
        cursor.execute("SELECT * FROM users WHERE email = ?", ('superadmin@attendancify.com',))
        user = cursor.fetchone()
        
        if not user:
            print("Superadmin user not found. Creating one...")
            # Create superadmin if doesn't exist
            password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            cursor.execute("""
                INSERT INTO users (email, password_hash, role, must_change_password, password_plain)
                VALUES (?, ?, 'superadmin', 0, ?)
            """, ('superadmin@attendancify.com', password_hash, 'admin123'))
            conn.commit()
            print("Superadmin created with email: superadmin@attendancify.com and password: admin123")
        else:
            print(f"Current superadmin role: {user['role'] if 'role' in user.keys() else 'No role field'}")
            
            # Update role to superadmin if it's not already
            if 'role' not in user.keys() or user['role'] != 'superadmin':
                print("Updating role to 'superadmin'...")
                cursor.execute("""
                    UPDATE users 
                    SET role = 'superadmin' 
                    WHERE email = 'superadmin@attendancify.com'
                """)
                conn.commit()
                print("Superadmin role has been updated.")
                
        # Verify the update
        cursor.execute("SELECT role FROM users WHERE email = ?", ('superadmin@attendancify.com',))
        updated_user = cursor.fetchone()
        print(f"Final superadmin role: {updated_user['role']}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import hashlib
    check_and_fix_superadmin()
