-- Dataset permissions migration

-- datasets table
CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description VARCHAR(1024),
    permission VARCHAR(32) NOT NULL DEFAULT 'all_team_members',
    owner_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_datasets_tenant ON datasets(tenant_id);

-- dataset permissions (partial members)
CREATE TABLE IF NOT EXISTS dataset_permissions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_dataset_perm_dataset FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    CONSTRAINT uq_dataset_permission_member UNIQUE(dataset_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_dataset_permissions_dataset ON dataset_permissions(dataset_id);
CREATE INDEX IF NOT EXISTS idx_dataset_permissions_account ON dataset_permissions(account_id);
CREATE INDEX IF NOT EXISTS idx_dataset_permissions_tenant ON dataset_permissions(tenant_id);

-- documents add dataset_id
ALTER TABLE documents ADD COLUMN IF NOT EXISTS dataset_id UUID;
CREATE INDEX IF NOT EXISTS idx_documents_dataset ON documents(dataset_id);
