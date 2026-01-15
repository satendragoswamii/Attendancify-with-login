# 🎓 Attendancify – Smart Zoom Attendance Calculator

<div align="center">

![Attendancify](https://img.shields.io/badge/Attendancify-Zoom_Attendance_Calculator-6366f1?style=for-the-badge)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3.2-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Calculate accurate attendance from Zoom logs – session-wise, with custom rules**

</div>

---

## 🎯 What is Attendancify?

A free tool for **schools, colleges, universities, and organizations** conducting online Zoom classes who need accurate attendance tracking.

**The Problem:** During a Zoom class, students join late, leave early, disconnect and rejoin. Manually tracking who attended "enough" time is tedious and error-prone.

**The Solution:** Upload your Zoom log → Configure sessions & rules → Get instant attendance report with **Present/Absent** status and shortfall details.

---

## 💡 Example

You have a **120-minute class**:
- Session 1: 50 min (10:00 - 10:50)
- Break: 20 min
- Session 2: 50 min (11:10 - 12:00)

**Your rule:** Student must attend at least **45 minutes per session** to be marked Present.

**Attendancify output:**
| Student | Session 1 | Session 2 | Shortfall |
|---------|-----------|-----------|-----------|
| John | P | P | - |
| Jane | A | P | Session 1: -6 min |

---

## ✨ Key Features

- **Multi-session support** – Configure multiple sessions with breaks
- **Custom attendance rules** – Set minimum required minutes per session
- **Shortfall reports** – See exactly how many minutes absent students missed
- **Smart name matching** – Handles name variations automatically
- **Batch processing** – Process multiple files at once
- **Excel export** – Detailed reports ready to share

---

## 🚀 Quick Start

```bash
git clone https://github.com/satendragoswamii/Attendancify-with-login.git
cd Attendancify-with-login
pip install -r requirements.txt
python comprehensive_app.py
```

Open `http://localhost:5000`

**Login:** `superadmin@attendancify.com` / `admin` (change on first login)

---

## 📖 How to Use

1. Download participant report from Zoom (CSV)
2. Upload to Attendancify
3. Set session times & minimum attendance duration
4. Download your attendance report

---

## 💬 Feedback & Contact

This is a **free passion project**. I'd love your feedback, suggestions, or questions!

📧 **Email:** [satendragoshwamii@gmail.com](mailto:satendragoshwamii@gmail.com)

[![Instagram](https://img.shields.io/badge/Instagram-@satendragoswamii-E4405F?style=flat&logo=instagram&logoColor=white)](https://www.instagram.com/satendragoswamii/)
[![GitHub](https://img.shields.io/badge/GitHub-satendragoswamii-181717?style=flat&logo=github&logoColor=white)](https://github.com/satendragoswamii)

---

## 📄 License

MIT License – free for personal and commercial use.

---

<div align="center">

⭐ **If this helped you, please star the repo!** ⭐

</div>
