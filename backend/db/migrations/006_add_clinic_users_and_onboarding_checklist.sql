-- Migration: Add clinic users and onboarding checklist tables
-- Created: 2026-06-15

-- Create clinic_users table
CREATE TABLE IF NOT EXISTS clinic_users (
    id SERIAL PRIMARY KEY,
    clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'staff',
    is_active BOOLEAN DEFAULT true,
    reset_token VARCHAR(255) DEFAULT '',
    reset_token_expires TIMESTAMP NULL,
    last_login_at TIMESTAMP NULL,
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_clinic_users_clinic ON clinic_users(clinic_id);
CREATE INDEX idx_clinic_users_email ON clinic_users(email);

-- Create onboarding_checklists table
CREATE TABLE IF NOT EXISTS onboarding_checklists (
    id SERIAL PRIMARY KEY,
    clinic_id INTEGER UNIQUE NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,

    clinic_info_completed BOOLEAN DEFAULT false,
    clinic_info_data TEXT DEFAULT '{}',

    branding_completed BOOLEAN DEFAULT false,
    branding_data TEXT DEFAULT '{}',

    email_config_completed BOOLEAN DEFAULT false,
    email_config_data TEXT DEFAULT '{}',
    email_config_tested BOOLEAN DEFAULT false,

    sms_config_completed BOOLEAN DEFAULT false,
    sms_config_data TEXT DEFAULT '{}',
    sms_config_tested BOOLEAN DEFAULT false,

    emr_integration_completed BOOLEAN DEFAULT false,
    emr_integration_data TEXT DEFAULT '{}',

    staff_training_completed BOOLEAN DEFAULT false,
    staff_training_date TIMESTAMP NULL,

    go_live_date TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_onboarding_checklist_clinic ON onboarding_checklists(clinic_id);
