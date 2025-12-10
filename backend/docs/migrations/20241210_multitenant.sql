-- Multi-tenant migration script
-- Note: adjust schema/table names if different; run with appropriate privileges.

-- 1) Tenants & members
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(32) DEFAULT 'active',
    plan VARCHAR(64) DEFAULT 'basic',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_members (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id VARCHAR(255),
    role VARCHAR(32) DEFAULT 'owner',
    is_current BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenant_members_tenant ON tenant_members(tenant_id);

-- 2) Documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE documents SET tenant_id = '00000000-0000-0000-0000-000000000000' WHERE tenant_id IS NULL;
ALTER TABLE documents ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id);

ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE document_chunks SET tenant_id = '00000000-0000-0000-0000-000000000000' WHERE tenant_id IS NULL;
ALTER TABLE document_chunks ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant ON document_chunks(tenant_id);

-- 3) Conversations / messages
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE conversations SET tenant_id = '00000000-0000-0000-0000-000000000000' WHERE tenant_id IS NULL;
ALTER TABLE conversations ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON conversations(tenant_id);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE messages SET tenant_id = '00000000-0000-0000-0000-000000000000' WHERE tenant_id IS NULL;
ALTER TABLE messages ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(tenant_id);

-- 4) (Optional) Defaults
-- Ensure application config DEFAULT_TENANT_ID matches the above default UUID.
