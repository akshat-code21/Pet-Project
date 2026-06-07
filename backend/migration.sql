BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 001

CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$ BEGIN CREATE TYPE source_type AS ENUM ('sec_13f','website','youtube','rss','twitter','custom'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE content_type AS ENUM ('filing','article','video','newsletter','website_page','custom'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE processing_status AS ENUM ('pending','processing','completed','failed','skipped'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE entity_type AS ENUM ('company','ticker','person','theme','sector','macro_theme'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE sentiment AS ENUM ('bullish','bearish','neutral','mixed'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE conviction_level AS ENUM ('high','medium','low','unknown'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE portfolio_change_type AS ENUM ('new_position','increased','decreased','closed','unchanged'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE report_type AS ENUM ('investor_report','daily_digest','event_report'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE alert_type AS ENUM ('new_filing','new_company_mention','new_thesis','high_conviction','portfolio_change','daily_digest_ready'); EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN CREATE TYPE alert_severity AS ENUM ('low','medium','high','critical'); EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR NOT NULL, 
    full_name VARCHAR, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX idx_users_email ON users (email);

CREATE TABLE investors (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    user_id UUID NOT NULL, 
    name VARCHAR NOT NULL, 
    description VARCHAR, 
    cik_number VARCHAR, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    last_synced_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX idx_investors_user_id ON investors (user_id);

CREATE INDEX idx_investors_cik ON investors (cik_number) WHERE cik_number IS NOT NULL;

CREATE INDEX idx_investors_active ON investors (user_id, is_active);

CREATE TABLE sources (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    investor_id UUID NOT NULL, 
    source_type source_type NOT NULL, 
    url VARCHAR NOT NULL, 
    label VARCHAR, 
    config JSONB DEFAULT '{}' NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    last_checked_at TIMESTAMP WITH TIME ZONE, 
    last_successful_at TIMESTAMP WITH TIME ZONE, 
    check_frequency_hours INTEGER DEFAULT '24' NOT NULL, 
    consecutive_failures INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE CASCADE
);

CREATE INDEX idx_sources_investor_id ON sources (investor_id);

CREATE INDEX idx_sources_type ON sources (source_type);

CREATE INDEX idx_sources_active_check ON sources (is_active, last_checked_at) WHERE is_active = TRUE;

CREATE TABLE content_items (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    source_id UUID NOT NULL, 
    investor_id UUID NOT NULL, 
    content_type content_type NOT NULL, 
    title VARCHAR, 
    url VARCHAR, 
    raw_text TEXT, 
    cleaned_text TEXT, 
    published_at TIMESTAMP WITH TIME ZONE, 
    content_hash VARCHAR NOT NULL, 
    processing_status processing_status DEFAULT 'pending' NOT NULL, 
    processing_error TEXT, 
    metadata JSONB DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT unique_content_hash UNIQUE (content_hash), 
    FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE, 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE CASCADE
);

CREATE INDEX idx_content_source_id ON content_items (source_id);

CREATE INDEX idx_content_investor_id ON content_items (investor_id);

CREATE INDEX idx_content_status ON content_items (processing_status) WHERE processing_status IN ('pending', 'processing');

CREATE INDEX idx_content_published ON content_items (investor_id, published_at);

CREATE INDEX idx_content_type ON content_items (investor_id, content_type);

CREATE TABLE extracted_mentions (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    content_item_id UUID NOT NULL, 
    investor_id UUID NOT NULL, 
    entity_type entity_type NOT NULL, 
    entity_name VARCHAR NOT NULL, 
    ticker_symbol VARCHAR, 
    sentiment sentiment, 
    conviction_level conviction_level, 
    context_snippet TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(content_item_id) REFERENCES content_items (id) ON DELETE CASCADE, 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE CASCADE
);

CREATE INDEX idx_mentions_content ON extracted_mentions (content_item_id);

CREATE INDEX idx_mentions_investor ON extracted_mentions (investor_id);

CREATE INDEX idx_mentions_ticker ON extracted_mentions (ticker_symbol) WHERE ticker_symbol IS NOT NULL;

CREATE INDEX idx_mentions_entity ON extracted_mentions (entity_type, entity_name);

CREATE TABLE portfolio_changes (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    investor_id UUID NOT NULL, 
    content_item_id UUID NOT NULL, 
    ticker_symbol VARCHAR NOT NULL, 
    company_name VARCHAR, 
    cusip VARCHAR, 
    change_type portfolio_change_type NOT NULL, 
    shares_previous BIGINT DEFAULT '0', 
    shares_current BIGINT NOT NULL, 
    value_usd BIGINT, 
    percent_of_portfolio NUMERIC(6, 3), 
    filing_period VARCHAR NOT NULL, 
    report_date DATE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE CASCADE, 
    FOREIGN KEY(content_item_id) REFERENCES content_items (id) ON DELETE CASCADE
);

CREATE INDEX idx_portfolio_investor ON portfolio_changes (investor_id);

CREATE INDEX idx_portfolio_ticker ON portfolio_changes (ticker_symbol);

CREATE INDEX idx_portfolio_period ON portfolio_changes (investor_id, filing_period);

CREATE INDEX idx_portfolio_change ON portfolio_changes (change_type);

CREATE TABLE reports (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    user_id UUID NOT NULL, 
    investor_id UUID, 
    report_type report_type NOT NULL, 
    title VARCHAR NOT NULL, 
    summary TEXT, 
    content_markdown TEXT NOT NULL, 
    source_item_ids UUID[] DEFAULT '{}' NOT NULL, 
    is_read BOOLEAN DEFAULT 'false' NOT NULL, 
    period_start TIMESTAMP WITH TIME ZONE, 
    period_end TIMESTAMP WITH TIME ZONE, 
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE SET NULL
);

CREATE INDEX idx_reports_user_id ON reports (user_id);

CREATE INDEX idx_reports_investor_id ON reports (investor_id) WHERE investor_id IS NOT NULL;

CREATE INDEX idx_reports_type ON reports (user_id, report_type);

CREATE INDEX idx_reports_generated ON reports (user_id, generated_at);

CREATE INDEX idx_reports_unread ON reports (user_id, is_read) WHERE is_read = FALSE;

CREATE TABLE alerts (
    id UUID DEFAULT uuid_generate_v4() NOT NULL, 
    user_id UUID NOT NULL, 
    investor_id UUID, 
    content_item_id UUID, 
    report_id UUID, 
    alert_type alert_type NOT NULL, 
    title VARCHAR NOT NULL, 
    summary TEXT, 
    severity alert_severity DEFAULT 'medium' NOT NULL, 
    score INTEGER DEFAULT '50' NOT NULL, 
    is_read BOOLEAN DEFAULT 'false' NOT NULL, 
    email_sent BOOLEAN DEFAULT 'false' NOT NULL, 
    metadata JSONB DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT chk_score_range CHECK (score BETWEEN 0 AND 100), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(investor_id) REFERENCES investors (id) ON DELETE SET NULL, 
    FOREIGN KEY(content_item_id) REFERENCES content_items (id) ON DELETE SET NULL, 
    FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE SET NULL
);

CREATE INDEX idx_alerts_user_unread ON alerts (user_id, is_read, created_at);

CREATE INDEX idx_alerts_investor ON alerts (investor_id) WHERE investor_id IS NOT NULL;

CREATE INDEX idx_alerts_type ON alerts (alert_type);

CREATE INDEX idx_alerts_severity ON alerts (user_id, severity) WHERE is_read = FALSE;

INSERT INTO alembic_version (version_num) VALUES ('001') RETURNING alembic_version.version_num;

COMMIT;

