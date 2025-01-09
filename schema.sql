-- Create tables for Xero sync

-- Create updated_at trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Table for storing Xero OAuth tokens
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL UNIQUE,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_type VARCHAR NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing Xero invoices
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL UNIQUE,
    tenant_id UUID NOT NULL,
    contact_id UUID,
    contact_name TEXT,
    invoice_number TEXT,
    reference TEXT,
    issue_date TIMESTAMP WITH TIME ZONE,
    due_date TIMESTAMP WITH TIME ZONE,
    status TEXT,
    line_amount_types TEXT,
    sub_total DECIMAL(15,4),
    total_tax DECIMAL(15,4),
    total DECIMAL(15,4),
    currency_code VARCHAR(3),
    type TEXT,
    xero_updated_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES oauth_tokens(tenant_id)
);

-- Table for storing invoice line items
CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id UUID NOT NULL UNIQUE,
    invoice_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    description TEXT,
    quantity DECIMAL(15,4),
    unit_amount DECIMAL(15,4),
    tax_amount DECIMAL(15,4),
    line_amount DECIMAL(15,4),
    account_code TEXT,
    tax_type TEXT,
    item_code TEXT,
    tracking JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id),
    FOREIGN KEY (tenant_id) REFERENCES oauth_tokens(tenant_id)
);

-- Drop and recreate sync_logs table
DROP TABLE IF EXISTS sync_logs;
CREATE TABLE sync_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    records_processed INTEGER DEFAULT 0,
    records_created INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    items_processed INTEGER DEFAULT 0,
    items_created INTEGER DEFAULT 0,
    items_updated INTEGER DEFAULT 0
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
    DROP TRIGGER IF EXISTS update_invoices_updated_at ON invoices;
    DROP TRIGGER IF EXISTS update_invoice_items_updated_at ON invoice_items;
    
    -- Create triggers
    CREATE TRIGGER update_oauth_tokens_updated_at
        BEFORE UPDATE ON oauth_tokens
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    CREATE TRIGGER update_invoices_updated_at
        BEFORE UPDATE ON invoices
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    
    CREATE TRIGGER update_invoice_items_updated_at
        BEFORE UPDATE ON invoice_items
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
    CREATE INDEX idx_invoices_tenant_id ON invoices(tenant_id);
    CREATE INDEX idx_invoices_contact_id ON invoices(contact_id);
    CREATE INDEX idx_invoices_status ON invoices(status);
    CREATE INDEX idx_invoices_xero_updated_at ON invoices(xero_updated_at);
    
    CREATE INDEX idx_invoice_items_invoice_id ON invoice_items(invoice_id);
    CREATE INDEX idx_invoice_items_tenant_id ON invoice_items(tenant_id);
    CREATE INDEX idx_invoice_items_item_code ON invoice_items(item_code);
    
    CREATE INDEX idx_sync_logs_status ON sync_logs(status);
    CREATE INDEX idx_sync_logs_start_time ON sync_logs(start_time);
    
    CREATE INDEX idx_error_logs_error_type ON error_logs(error_type);
    CREATE INDEX idx_error_logs_timestamp ON error_logs(timestamp);
END $$;
