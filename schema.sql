-- ============================================================
-- VEKAS Construction Project Portal - MySQL Database Schema
-- ============================================================
-- Run this file first: mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS vekas_construction CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE vekas_construction;

-- ------------------------------------------------------------
-- USERS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','manager','viewer') DEFAULT 'manager',
    avatar        VARCHAR(255) DEFAULT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- PROJECTS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_code VARCHAR(50) UNIQUE DEFAULT NULL,
    project_prefix VARCHAR(20) DEFAULT NULL,
    project_year SMALLINT DEFAULT NULL,
    project_sequence INT DEFAULT NULL,
    name        VARCHAR(255) NOT NULL,
    client_name VARCHAR(255) DEFAULT NULL,
    company_name VARCHAR(255) DEFAULT NULL,
    customer_name VARCHAR(255) DEFAULT NULL,
    job_position VARCHAR(100) DEFAULT NULL,
    contact_number VARCHAR(50) DEFAULT NULL,
    whatsapp_number VARCHAR(50) DEFAULT NULL,
    email_id VARCHAR(255) DEFAULT NULL,
    address TEXT DEFAULT NULL,
    city VARCHAR(120) DEFAULT NULL,
    district VARCHAR(120) DEFAULT NULL,
    state VARCHAR(120) DEFAULT NULL,
    country VARCHAR(120) DEFAULT 'India',
    project_type VARCHAR(100) DEFAULT NULL,
    project_location TEXT DEFAULT NULL,
    building_area_details JSON DEFAULT NULL,
    total_builtup_area DECIMAL(12,2) DEFAULT 0,
    description TEXT,
    status      ENUM('Planning','In Progress','Review','Completed','Delayed') DEFAULT 'Planning',
    priority    ENUM('Low','Medium','High') DEFAULT 'Medium',
    start_date  DATE DEFAULT NULL,
    end_date    DATE DEFAULT NULL,
    created_by  INT DEFAULT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE KEY uq_projects_company_name (company_name),
    UNIQUE KEY uq_projects_contact_number (contact_number),
    INDEX idx_status (status),
    INDEX idx_created_by (created_by)
);

-- ------------------------------------------------------------
-- FILES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS files (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    project_id    INT NOT NULL,
    folder_type   ENUM('Drawing','Output','Document','Blueprint') DEFAULT 'Drawing',
    filename      VARCHAR(255) NOT NULL,   -- stored UUID name on disk
    original_name VARCHAR(255) NOT NULL,   -- user-visible original name
    file_size     BIGINT DEFAULT 0,
    file_type     VARCHAR(50) DEFAULT NULL,
    uploaded_by   INT DEFAULT NULL,
    uploaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_project_folder (project_id, folder_type)
);

-- ------------------------------------------------------------
-- PROJECT NOTES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_notes (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_id  INT NOT NULL,
    note        TEXT,
    updated_by  INT DEFAULT NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
);

-- ------------------------------------------------------------
-- PROJECT MEMBERS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_members (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_id  INT NOT NULL,
    user_id     INT NOT NULL,
    role        VARCHAR(100) DEFAULT 'Member',
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uq_project_user (project_id, user_id)
);

-- ------------------------------------------------------------
-- ACTIVITY LOG
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_log (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_id  INT DEFAULT NULL,
    user_id     INT DEFAULT NULL,
    action      VARCHAR(255) NOT NULL,
    details     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_project_activity (project_id),
    INDEX idx_created (created_at)
);

-- ------------------------------------------------------------
-- LOGIN SESSIONS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS login_sessions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    user_id          INT NOT NULL,
    login_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_at        TIMESTAMP NULL DEFAULT NULL,
    duration_seconds INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_login_user (user_id),
    INDEX idx_login_at (login_at)
);

-- ------------------------------------------------------------
-- SEED: Demo Admin User  (password: Admin@1234)
-- ------------------------------------------------------------
INSERT IGNORE INTO users (name, email, password_hash, role)
VALUES (
    'Senthil Rajamarthandan',
    'digidaratechnologies@gmail.com',
    'pbkdf2:sha256:600000$rNbRpGLz$6a3e8a1e2f3d4c5b6a7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9',
    'admin'
);

INSERT INTO users (name, email, password_hash, role)
VALUES (
    'VEKAS Admin',
    'vekas@gmail.com',
    'pbkdf2:sha256:600000$d0cfdb3b39e90bb1$51a4ada1e69e75e3317e5049b59e57d865921a79a3995980bf82ed2187ee0476',
    'admin'
)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    password_hash = VALUES(password_hash),
    role = VALUES(role);

-- NOTE: The demo password hash above is a placeholder.
-- The app will let you register a real account on first run.
-- Or run this from Python to generate a real hash:
--   from werkzeug.security import generate_password_hash
--   print(generate_password_hash('YourPassword'))
