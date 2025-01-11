-- Create tables for Xero sync

-- Create updated_at trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Drop tables in correct order
DROP TABLE IF EXISTS invoice_items_new;
DROP TABLE IF EXISTS invoices_new;
DROP TABLE IF EXISTS oauth_tokens;

-- Recreate oauth_tokens table with scope
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id TEXT NOT NULL UNIQUE,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_type VARCHAR(50) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    scope TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Recreate invoices table
CREATE TABLE invoices_new (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id VARCHAR NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    invoice_number VARCHAR,
    reference VARCHAR,
    type VARCHAR,
    status VARCHAR,
    contact_id VARCHAR,
    contact_name VARCHAR,
    date DATE,
    due_date DATE,
    updated_date_utc TIMESTAMP WITH TIME ZONE,
    currency_code VARCHAR(3),
    sub_total DECIMAL(15,2),
    total_tax DECIMAL(15,2),
    total DECIMAL(15,2),
    amount_due DECIMAL(15,2),
    amount_paid DECIMAL(15,2),
    amount_credited DECIMAL(15,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add updated_at trigger
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_oauth_tokens_updated_at') THEN
        CREATE TRIGGER update_oauth_tokens_updated_at
            BEFORE UPDATE ON oauth_tokens
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;

-- Drop existing tables
DROP TABLE IF EXISTS invoice_items;
DROP TABLE IF EXISTS invoices;

-- Create new tables with _new suffix
CREATE TABLE invoice_items_new (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    xero_invoice_id VARCHAR REFERENCES invoices_new(invoice_id),
    line_item_id VARCHAR,
    description TEXT,
    quantity DECIMAL(15,2),
    unit_amount DECIMAL(15,2),
    tax_amount DECIMAL(15,2),
    line_amount DECIMAL(15,2),
    account_code VARCHAR,
    tax_type VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(xero_invoice_id, line_item_id)
);

-- Drop and recreate sync_logs table
DROP TABLE IF EXISTS sync_logs;
CREATE TABLE sync_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    status VARCHAR NOT NULL,
    records_processed INTEGER DEFAULT 0,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing error logs
CREATE TABLE IF NOT EXISTS error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    additional_data JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate triggers
DO $$ 
BEGIN
    -- Drop triggers if they exist
    DROP TRIGGER IF EXISTS update_oauth_tokens_updated_at ON oauth_tokens;
    DROP TRIGGER IF EXISTS update_invoices_new_updated_at ON invoices_new;
    DROP TRIGGER IF EXISTS update_invoice_items_new_updated_at ON invoice_items_new;
    
    -- Create triggers
    CREATE TRIGGER update_oauth_tokens_updated_at
        BEFORE UPDATE ON oauth_tokens
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    CREATE TRIGGER update_invoices_new_updated_at
        BEFORE UPDATE ON invoices_new
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    CREATE TRIGGER update_invoice_items_new_updated_at
        BEFORE UPDATE ON invoice_items_new
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
END $$;

-- Drop and recreate indexes
DO $$ 
BEGIN
    -- Drop indexes if they exist
    DROP INDEX IF EXISTS idx_invoices_tenant_id;
    DROP INDEX IF EXISTS idx_invoices_contact_id;
    DROP INDEX IF EXISTS idx_invoices_status;
    DROP INDEX IF EXISTS idx_invoices_xero_updated_at;
    DROP INDEX IF EXISTS idx_invoice_items_invoice_id;
    DROP INDEX IF EXISTS idx_invoice_items_tenant_id;
    DROP INDEX IF EXISTS idx_invoice_items_item_code;
    DROP INDEX IF EXISTS idx_sync_logs_status;
    DROP INDEX IF EXISTS idx_sync_logs_start_time;
    DROP INDEX IF EXISTS idx_error_logs_error_type;
    DROP INDEX IF EXISTS idx_error_logs_timestamp;
    
    -- Create indexes
    CREATE INDEX idx_invoices_tenant_id ON invoices_new(tenant_id);
    CREATE INDEX idx_invoices_contact_id ON invoices_new(contact_id);
    CREATE INDEX idx_invoices_status ON invoices_new(status);
    CREATE INDEX idx_invoices_xero_updated_at ON invoices_new(xero_updated_at);
    
    CREATE INDEX idx_invoice_items_invoice_id ON invoice_items_new(invoice_id);
    CREATE INDEX idx_invoice_items_tenant_id ON invoice_items_new(tenant_id);
    CREATE INDEX idx_invoice_items_item_code ON invoice_items_new(item_code);
    
    CREATE INDEX idx_sync_logs_status ON sync_logs(status);
    CREATE INDEX idx_sync_logs_start_time ON sync_logs(start_time);
    
    CREATE INDEX idx_error_logs_error_type ON error_logs(error_type);
    CREATE INDEX idx_error_logs_timestamp ON error_logs(timestamp);
END $$;

-- Add updated_at triggers
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_invoices_new_updated_at') THEN
        CREATE TRIGGER update_invoices_new_updated_at
            BEFORE UPDATE ON invoices_new
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_invoice_items_new_updated_at') THEN
        CREATE TRIGGER update_invoice_items_new_updated_at
            BEFORE UPDATE ON invoice_items_new
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;

-- Drop and recreate contacts table
DROP TABLE IF EXISTS contacts;

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id VARCHAR NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL REFERENCES oauth_tokens(tenant_id),
    name VARCHAR,
    first_name VARCHAR,
    last_name VARCHAR,
    email VARCHAR,
    phone VARCHAR,
    status VARCHAR,
    updated_date_utc TIMESTAMP WITH TIME ZONE,
    is_customer BOOLEAN DEFAULT FALSE,
    is_supplier BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add contacts trigger
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_contacts_updated_at') THEN
        CREATE TRIGGER update_contacts_updated_at
            BEFORE UPDATE ON contacts
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;
