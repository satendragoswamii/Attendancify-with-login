# This file contains the WSGI configuration required to serve up your
# web application on PythonAnywhere
# 
# IMPORTANT: Update the path below to match your PythonAnywhere username and project directory
# Example: '/home/yourusername/Attendancify'

import sys
import os

# Add your project directory to the sys.path
# UPDATE THIS PATH to match your PythonAnywhere account
path = '/home/attendancify/attendancify'  # CHANGE THIS!
if path not in sys.path:
    sys.path.append(path)

# Change to the project directory
os.chdir(path)

# Set environment variables for production
os.environ['FLASK_ENV'] = 'production'
os.environ['FLASK_DEBUG'] = 'False'
# IMPORTANT: Set your secret key in PythonAnywhere's Web tab → Environment variables
# Or uncomment and set it here (less secure):
# os.environ['FLASK_SECRET_KEY'] = 'your-secret-key-here'

# Import flask app but need to call it "application" for WSGI to work
from comprehensive_app import app as application

# Initialize database on first load
try:
    from database import init_db
    init_db()
except Exception as e:
    print(f"Database initialization note: {e}")