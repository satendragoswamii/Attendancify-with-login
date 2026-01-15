# 🎓 Attendancify – Professional Attendance Management System

<div align="center">

![Attendancify Banner](https://img.shields.io/badge/Attendancify-Intelligent_Attendance_Automation-6366f1?style=for-the-badge)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3.2-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?style=flat&logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Automated, Accurate, and Intelligent Attendance Management for Modern Education**

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Demo](#-live-demo) • [Documentation](#-documentation)

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-features)
- [Tech Stack](#-tech-stack)
- [Installation](#-installation)
- [Default Credentials](#-default-credentials)
- [Usage Guide](#-usage-guide)
- [Tools Overview](#-tools-overview)
- [File Formats](#-file-formats)
- [Deployment](#-deployment)
- [Screenshots](#-screenshots)
- [Contributing](#-contributing)
- [License](#-license)
- [Support](#-support)
- [Developer](#-developer)

---

## 🌟 Overview

**Attendancify** is a comprehensive web-based attendance management system designed specifically for educators, training coordinators, and organizations conducting online sessions via Zoom or similar platforms. It automates the tedious process of attendance tracking by intelligently processing session logs and generating accurate, detailed reports.

### Why Attendancify?

- ⏱️ **Save Time**: Automate hours of manual attendance tracking
- 🎯 **Precision**: Second-level accuracy in attendance calculation
- 🤖 **Smart Matching**: AI-powered fuzzy name matching handles variations
- 📊 **Comprehensive Reports**: Detailed Excel reports with statistics
- 🔐 **Secure**: Role-based access control with user management
- 🎨 **Modern UI**: Beautiful, responsive interface with dark/light themes

---

## ✨ Features

### 🎯 Core Functionality

- **🔄 Automatic Attendance Generation**
  - Process Zoom CSV logs instantly
  - Calculate attendance based on session duration
  - Customizable time thresholds per session
  - Support for multiple sessions and batch processing

- **⚡ Second-Level Precision**
  - Track participant presence down to the second
  - Eliminate manual calculation errors
  - Configurable minimum time requirements

- **🔍 Intelligent Name Matching**
  - Fuzzy matching algorithm using RapidFuzz
  - Handles name variations, nicknames, spelling differences
  - Cross-reference with master student lists
  - Identify absentees automatically

- **📈 Comprehensive Reporting**
  - Detailed Excel reports with multiple sheets
  - Statistics: total attendees, present/absent counts
  - Session-wise breakdowns
  - Timestamps and duration tracking

### 🔐 Advanced Features

- **User Authentication & Authorization**
  - Secure login system with password hashing
  - Role-based access (Superadmin, Admin, User)
  - Forced password change on first login
  - Session management with token validation

- **User Management**
  - Create and manage user accounts
  - Set account expiration dates
  - View user passwords (superadmin only)
  - Assign roles and permissions

- **Modern UI/UX**
  - Responsive design (mobile, tablet, desktop)
  - Dark/Light theme toggle
  - Animated particle background
  - Smooth transitions and animations
  - Professional gradient designs

---

## 🛠️ Tech Stack

| Technology | Purpose | Version |
|------------|---------|----------|
| **Python** | Backend Language | 3.9+ |
| **Flask** | Web Framework | 2.3.2 |
| **Pandas** | Data Processing | 1.5.3+ |
| **OpenPyXL** | Excel Handling | 3.1.2 |
| **RapidFuzz** | Fuzzy Matching | 3.4.0 |
| **Bootstrap** | UI Framework | 5.3.0 |
| **Font Awesome** | Icons | 6.0.0 |

---

## 🚀 Installation

### Prerequisites

- **Python 3.9 or higher** ([Download](https://www.python.org/downloads/))
- **pip** package manager
- **Git** ([Download](https://git-scm.com/downloads/))

### Step-by-Step Setup

#### 1️⃣ Clone the Repository

```bash
git clone https://github.com/satendravoice/Attendancify-with-login.git
cd Attendancify-with-login
```

#### 2️⃣ Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4️⃣ Run the Application

```bash
python comprehensive_app.py
```

#### 5️⃣ Access the Application

Open your browser and navigate to:
```
http://localhost:5000
```

---

## 🔑 Default Credentials

### Superadmin Account

```
Email: superadmin@attendancify.com
Password: admin
```

> ⚠️ **Important**: You will be **required to change the password** upon first login for security.

### User Roles

| Role | Permissions |
|------|-------------|
| **Superadmin** | Full access: manage users, view passwords, process attendance |
| **Admin** | Create users, manage attendance, process files |
| **User** | Process attendance files only (limited access) |

---

## 📖 Usage Guide

### 🎯 Tool 1: Attendance Generator

**Purpose**: Process Zoom attendance logs and generate detailed reports

#### Steps:

1. **Login** to your account
2. Click on **"Attendance Generator"** tool
3. **Upload** Zoom CSV file(s)
   - Single file mode: Upload one CSV
   - Multiple files mode: Upload multiple CSVs for batch processing
4. **Configure Sessions**:
   - Set session start/end times
   - Define minimum attendance time (in minutes)
   - Add multiple sessions if needed
5. Click **"Process Attendance"**
6. **Download** automatically starts with success message
7. Review the Excel report with attendance data

#### Output:
- Excel file with attendance status (P/A)
- Session-wise attendance breakdown
- Statistics and summary

---

### 📊 Tool 2: Raw Excel Generator

**Purpose**: Extract and standardize attendance data from Excel files

#### Steps:

1. Navigate to **"Raw Excel Generator"**
2. **Upload** Excel files containing attendance data
3. System automatically extracts and standardizes data
4. **Download** clean, structured Excel output

#### Use Case:
- Convert mixed-format Excel files to standard format
- Extract attendance columns from complex spreadsheets
- Prepare data for matching tool

---

### 🔄 Tool 3: Attendance Matching

**Purpose**: Match raw attendance data with master student lists

#### Steps:

1. Go to **"Attendance Matching"** tool
2. **Upload Master List** (Excel file with enrolled students)
3. **Upload Raw Attendance File** (processed attendance data)
4. System uses fuzzy matching to cross-reference
5. **Download** matched report with:
   - Matched students with attendance status
   - Unmatched entries (for review)
   - Summary sheet

#### Benefits:
- Identify absent students from enrolled list
- Handle name variations automatically
- Generate comprehensive class reports

---

## 📁 File Formats

### Zoom CSV Format (Required)

```csv
Name (Original Name),User Name,User Email,Join Time,Leave Time,Duration (Minutes)
John Doe,jdoe,john@example.com,12/01/2024 10:00:00,12/01/2024 11:30:00,90
```

**Required Columns:**
- `Name (Original Name)` or `User Name`: Participant name
- `User Email`: Email address
- `Join Time`: Session entry timestamp
- `Leave Time`: Session exit timestamp
- `Duration (Minutes)`: Time spent in session

### Master List Format (Excel)

```
| Email              | Participant Name | Student ID |
|--------------------|------------------|------------|
| john@example.com   | John Doe         | 12345      |
| jane@example.com   | Jane Smith       | 12346      |
```

**Required Columns:**
- `Email` or `Email_id`: Student email
- `Participant Name` or `Name`: Student full name

---

## 🌐 Deployment

### Deploy on PythonAnywhere (Free)

#### 1. Create Account
- Sign up at [PythonAnywhere](https://www.pythonanywhere.com/)
- Choose free tier (sufficient for small to medium use)

#### 2. Upload Code
```bash
# In PythonAnywhere Bash console
git clone https://github.com/satendravoice/Attendancify-with-login.git
cd Attendancify-with-login
pip install --user -r requirements.txt
```

#### 3. Configure WSGI
- Go to **Web** tab
- Add new web app (Flask, Python 3.9+)
- Edit WSGI configuration file:
```python
import sys
path = '/home/yourusername/Attendancify-with-login'
if path not in sys.path:
    sys.path.append(path)

from comprehensive_app import app as application
```

#### 4. Set Static Files
- **URL**: `/static/`
- **Directory**: `/home/yourusername/Attendancify-with-login/static/`

#### 5. Reload Web App
- Click **Reload** button
- Access at: `https://yourusername.pythonanywhere.com`

### Deploy on Other Platforms

<details>
<summary><b>Heroku</b></summary>

1. Create `Procfile`:
```
web: gunicorn comprehensive_app:app
```

2. Add `gunicorn` to requirements.txt:
```bash
echo "gunicorn" >> requirements.txt
```

3. Deploy:
```bash
heroku create your-app-name
git push heroku main
```
</details>

<details>
<summary><b>AWS/Azure/Google Cloud</b></summary>

Follow standard Flask deployment guides for your chosen platform.
</details>

---

## 🎨 Screenshots

### Login Page
*Modern, secure login with gradient design and particle animations*

### Dashboard
*Three powerful tools in a clean, intuitive interface*

### Attendance Processing
*Simple upload, configure, and download workflow*

> *Screenshots will be added soon*

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

### Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/Attendancify-with-login.git
   ```
3. Create a **feature branch**:
   ```bash
   git checkout -b feature/AmazingFeature
   ```
4. Make your changes and **commit**:
   ```bash
   git commit -m 'Add some AmazingFeature'
   ```
5. **Push** to your fork:
   ```bash
   git push origin feature/AmazingFeature
   ```
6. Open a **Pull Request**

### Contribution Guidelines

- Write clear, concise commit messages
- Follow existing code style and conventions
- Test your changes thoroughly
- Update documentation if needed
- Add comments for complex logic

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

### MIT License Summary

✅ Commercial use  
✅ Modification  
✅ Distribution  
✅ Private use  

---

## 💬 Support

### Need Help?

- 📖 **Documentation**: Check [PASSWORD_MANAGEMENT_SYSTEM.md](PASSWORD_MANAGEMENT_SYSTEM.md) for detailed user management guide
- 🐛 **Bug Reports**: [Open an issue](https://github.com/satendravoice/Attendancify-with-login/issues)
- 💡 **Feature Requests**: [Submit a request](https://github.com/satendravoice/Attendancify-with-login/issues)
- 📧 **Contact**: Reach out via Instagram (below)

### Community

- ⭐ **Star** this repo if you find it helpful!
- 🍴 **Fork** and contribute
- 📢 **Share** with educators and administrators

---

## 👨‍💻 Developer

<div align="center">

**Developed with ❤️ by**

### Satendra Goswami

[![Instagram](https://img.shields.io/badge/Instagram-@satendragoswamii-E4405F?style=for-the-badge&logo=instagram&logoColor=white)](https://www.instagram.com/satendragoswamii/)
[![GitHub](https://img.shields.io/badge/GitHub-satendravoice-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/satendravoice)

*Professional Python Developer | AI Enthusiast | EdTech Innovator*

</div>

---

## 🙏 Acknowledgments

- Built with **Flask** for robust backend
- **Pandas** for efficient data processing
- **RapidFuzz** for intelligent name matching
- **Bootstrap 5** for responsive, modern UI
- Inspired by the need for accurate remote attendance tracking in modern education

---

## ⚠️ Important Notes

- **AI-Based Tool**: While highly accurate, please verify critical attendance data
- **Security**: Always change default passwords immediately
- **Backup**: Keep backup copies of original attendance files
- **Privacy**: Handle student data responsibly and comply with data protection regulations

---

<div align="center">

### 🌟 If this project helped you, please give it a star! 🌟

**Attendancify** © 2025 | Made with 💙 for Educators Worldwide

</div>