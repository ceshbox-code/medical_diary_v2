CREATE TABLE IF NOT EXISTS drugs (
    id BIGSERIAL PRIMARY KEY,
    reg_number VARCHAR(50) UNIQUE NOT NULL,
    trade_name VARCHAR(255) NOT NULL,
    inn VARCHAR(255),
    dosage_form VARCHAR(255),
    dosage_value VARCHAR(255),
    manufacturer VARCHAR(500),
    holder VARCHAR(500),
    status VARCHAR(50),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS drug_gtins (
    id BIGSERIAL PRIMARY KEY,
    gtin VARCHAR(14) NOT NULL,
    drug_id BIGINT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
    package_desc VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(gtin, drug_id)
);

CREATE INDEX IF NOT EXISTS idx_drug_gtins_gtin ON drug_gtins(gtin);
CREATE INDEX IF NOT EXISTS idx_drugs_reg_number ON drugs(reg_number);

CREATE TABLE IF NOT EXISTS drug_import_runs (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL,
    records_seen BIGINT NOT NULL DEFAULT 0,
    records_loaded BIGINT NOT NULL DEFAULT 0,
    records_skipped BIGINT NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_drug_import_runs_source_started
    ON drug_import_runs(source, started_at DESC);


-- Очередь строк МДЛП, для которых на момент импорта ещё нет записи ГРЛС.
-- Нужна для идемпотентной синхронизации при разном порядке публикации источников.
CREATE TABLE IF NOT EXISTS drug_gtin_pending (
    id BIGSERIAL PRIMARY KEY,
    gtin VARCHAR(14) NOT NULL,
    reg_number VARCHAR(50) NOT NULL,
    package_desc VARCHAR(500),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(gtin, reg_number)
);

CREATE INDEX IF NOT EXISTS idx_drug_gtin_pending_reg
    ON drug_gtin_pending(reg_number);


-- HTTP validators последней успешно импортированной выгрузки.
-- Позволяют MDЛП/ГРЛС не скачивать и не разбирать неизменившийся файл.
CREATE TABLE IF NOT EXISTS drug_source_state (
    source VARCHAR(32) PRIMARY KEY,
    url TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
