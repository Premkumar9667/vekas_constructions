╔══════════════════════════════════════════════════════════════╗
║     VEKAS Construction Project Portal — Setup Guide          ║
╚══════════════════════════════════════════════════════════════╝

PREREQUISITES
─────────────
• Python 3.9+
• MySQL 8.0+ (or MariaDB 10.5+)
• pip

STEP 1 — Install Python dependencies
──────────────────────────────────────
Open a terminal in this folder and run:

    pip install -r requirements.txt

STEP 2 — Set up MySQL database
────────────────────────────────
Open MySQL Workbench or the MySQL CLI, then run:

    mysql -u root -p < schema.sql

This creates the `vekas_construction` database and all tables.

STEP 3 — Configure database credentials
─────────────────────────────────────────
Open  config.py  and set your MySQL password:

    MYSQL_PASSWORD = 'your_mysql_password_here'

(You can also use environment variables — see config.py for details.)

STEP 4 — Run the app
──────────────────────
    python app.py

Open your browser at:  http://localhost:5000

STEP 5 — Register your account
────────────────────────────────
Click "Sign Up" on the login page and create your account.

══════════════════════════════════════════════════════════════
FOLDER STRUCTURE
══════════════════════════════════════════════════════════════

vekas_construction/
├── app.py                  ← Main Flask app (all routes & backend)
├── config.py               ← DB & app configuration
├── requirements.txt        ← Python dependencies
├── schema.sql              ← MySQL database schema + seed
├── README.txt              ← This file
├── static/
│   └── uploads/            ← Uploaded project files (auto-created)
│       └── <project_id>/   ← Files organized by project
└── templates/
    ├── login.html          ← Sign In / Sign Up page
    ├── dashboard.html      ← Projects overview & creation
    ├── project_detail.html ← Per-project detail (zip2 UI)
    ├── project_files.html  ← File management page
    └── _file_card.html     ← Reusable file card partial

══════════════════════════════════════════════════════════════
ALL BUTTONS & CONNECTIONS
══════════════════════════════════════════════════════════════

LOGIN PAGE  (/login)
 ✓ Sign In button           → POST /login (signin action)
 ✓ Sign Up button           → POST /login (signup action)
 ✓ Tab toggle               → JS switchTab()
 ✓ Show/hide password       → JS togglePwd()
 ✓ Password strength meter  → JS live indicator
 ✓ Forgot password link     → Placeholder (extend as needed)

DASHBOARD  (/dashboard)
 ✓ Create Project button    → Opens modal → POST /api/project/create → redirect to project detail
 ✓ Project card "Open"      → GET /project/<id>
 ✓ Project card "View Files"→ GET /project/<id>/files
 ✓ 3-dot menu "Edit"        → Opens edit modal → POST /project/<id>/update
 ✓ 3-dot menu "Delete"      → POST /project/<id>/delete
 ✓ Search input             → JS client-side filter
 ✓ Status filter dropdown   → JS client-side filter
 ✓ User avatar menu         → Profile / Settings / Sign Out
 ✓ Sign Out                 → GET /logout

PROJECT DETAIL  (/project/<id>)
 ✓ Upload Files button      → Opens upload modal
 ✓ Drag & drop zone         → Opens upload modal with files pre-selected
 ✓ Multi-file upload        → XHR POST /project/<id>/upload with progress bar
 ✓ Drawing / Output tabs    → JS switchFileTab()
 ✓ Download file button     → GET /project/<id>/download/<file_id>
 ✓ Delete file button       → POST /project/<id>/file/<file_id>/delete
 ✓ Save Notes button        → POST /project/<id>/notes (AJAX)
 ✓ Edit Status modal        → POST /project/<id>/update
 ✓ Delete Project           → POST /project/<id>/delete
 ✓ Show more description    → JS toggle
 ✓ Sidebar navigation links → All pages connected
 ✓ Back to Dashboard        → GET /dashboard

FILE MANAGEMENT  (/project/<id>/files)
 ✓ Drawing / Output tabs    → URL ?folder=Drawing / ?folder=Output
 ✓ Multi-file Upload button → Opens upload modal → XHR POST /project/<id>/upload
 ✓ Drag & drop to upload    → handleUploadDrop()
 ✓ Download button per file → GET /project/<id>/download/<file_id>
 ✓ Delete button per file   → POST /project/<id>/file/<file_id>/delete
 ✓ Search files             → JS client-side filter
 ✓ Edit notes               → POST /project/<id>/notes (AJAX inline edit)
 ✓ Image files              → Show preview thumbnail
 ✓ Document files           → Show icon with type badge

JSON API ENDPOINTS (for AJAX/future integrations)
 GET  /api/projects                  → list all projects
 GET  /api/project/<id>/files?folder → list files in folder
 GET  /api/project/<id>/storage      → storage usage stats

══════════════════════════════════════════════════════════════
MYSQL TABLES
══════════════════════════════════════════════════════════════
 users            — accounts (name, email, password_hash, role)
 projects         — project records (name, client, status, priority, dates)
 files            — uploaded files (per project, per folder)
 project_notes    — per-project notes (editable)
 project_members  — team member assignments per project
 activity_log     — audit trail (uploads, creates, deletes, edits)

══════════════════════════════════════════════════════════════
CUSTOMISATION
══════════════════════════════════════════════════════════════
• Change MYSQL_PASSWORD in config.py
• Change SECRET_KEY in config.py for production
• Adjust PROJECT_STORAGE_LIMIT (default 1 GB per project)
• Adjust MAX_CONTENT_LENGTH (default 100 MB per upload)
• Add ALLOWED_EXTENSIONS in config.py as needed

For production deployment:
• Use gunicorn or uWSGI instead of app.run(debug=True)
• Set environment variables for all secrets
• Configure a reverse proxy (nginx / Apache)
