"""Baseline schema (generated from SQLAlchemy metadata).

Notes:
- This revision is intended for *new* databases.
- Existing databases created before Alembic was introduced should typically use
  `alembic stamp head` after validating schema compatibility.
"""


import sqlalchemy as sa

from alembic import op

revision = '0001_baseline_schema'
down_revision = None
branch_labels = None
depends_on = None

# fmt: off
UPGRADE_SQL = ["CREATE TYPE datasetpermissionenum AS ENUM ('ONLY_ME', 'ALL_TEAM_MEMBERS', 'PARTIAL_MEMBERS')",
 'CREATE TABLE conversations (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tuser_id UUID, \n'
 '\tdataset_id UUID, \n'
 '\ttitle VARCHAR(500), \n'
 '\tdocument_ids UUID[], \n'
 '\tmessage_count INTEGER, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_conversations_dataset_id ON conversations (dataset_id)',
 'CREATE INDEX ix_conversations_tenant_id ON conversations (tenant_id)',
 'CREATE TABLE chunk_presets (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tname VARCHAR(200) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\tpayload JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_chunk_presets_tenant_name ON chunk_presets (tenant_id, name)',
 'CREATE INDEX ix_chunk_presets_tenant_id ON chunk_presets (tenant_id)',
 'CREATE TABLE datasets (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tdescription VARCHAR(1024), \n'
 '\tpermission datasetpermissionenum NOT NULL, \n'
 '\towner_id VARCHAR(255), \n'
 '\tmetadata JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_datasets_tenant_id_id UNIQUE (tenant_id, id), \n'
 '\tCONSTRAINT uq_datasets_tenant_name UNIQUE (tenant_id, name)\n'
 ')',
 'CREATE INDEX ix_datasets_tenant_id ON datasets (tenant_id)',
 'CREATE TABLE ragas_evaluation_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\taccount_id VARCHAR(255), \n'
 '\tconversation_id UUID, \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tmetrics JSONB, \n'
 '\tparams JSONB, \n'
 '\tsummary JSONB, \n'
 '\terror_message TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_ragas_evaluation_runs_conversation_id ON ragas_evaluation_runs (conversation_id)',
 'CREATE INDEX ix_ragas_evaluation_runs_tenant_id ON ragas_evaluation_runs (tenant_id)',
 'CREATE INDEX ix_ragas_evaluation_runs_account_id ON ragas_evaluation_runs (account_id)',
 'CREATE TABLE ragas_regression_cases (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID, \n'
 '\tdocument_ids JSONB, \n'
 '\tquestion TEXT NOT NULL, \n'
 '\texpected_answer TEXT, \n'
 '\treference_sources JSONB NOT NULL, \n'
 '\ttags JSONB, \n'
 '\textra JSONB, \n'
 '\tcreated_by VARCHAR(255), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_ragas_regression_cases_dataset_id ON ragas_regression_cases (dataset_id)',
 'CREATE INDEX ix_ragas_regression_cases_created_by ON ragas_regression_cases (created_by)',
 'CREATE INDEX ix_ragas_regression_cases_tenant_id ON ragas_regression_cases (tenant_id)',
 'CREATE TABLE ragas_regression_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\taccount_id VARCHAR(255), \n'
 '\tdataset_id UUID, \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tmetrics JSONB, \n'
 '\tparams JSONB, \n'
 '\tsummary JSONB, \n'
 '\terror_message TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_ragas_regression_runs_account_id ON ragas_regression_runs (account_id)',
 'CREATE INDEX ix_ragas_regression_runs_tenant_id ON ragas_regression_runs (tenant_id)',
 'CREATE INDEX ix_ragas_regression_runs_dataset_id ON ragas_regression_runs (dataset_id)',
 'CREATE TABLE evidence_suites (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\ttags JSONB, \n'
 '\tconfig JSONB, \n'
 '\tcreated_by VARCHAR(255), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tarchived_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_evidence_suites_tenant_id ON evidence_suites (tenant_id)',
 'CREATE INDEX ix_evidence_suites_dataset_id ON evidence_suites (dataset_id)',
 'CREATE INDEX ix_evidence_suites_created_by ON evidence_suites (created_by)',
 'CREATE TABLE governance_profiles (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tkey VARCHAR(100), \n'
 '\tname VARCHAR(200) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\tis_system BOOLEAN, \n'
 '\tpayload JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_governance_profiles_tenant_name ON governance_profiles (tenant_id, name)',
 'CREATE INDEX ix_governance_profiles_key ON governance_profiles (key)',
 'CREATE INDEX ix_governance_profiles_tenant_key ON governance_profiles (tenant_id, key)',
 'CREATE INDEX ix_governance_profiles_tenant_id ON governance_profiles (tenant_id)',
 'CREATE TABLE prompt_templates (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tname VARCHAR(200) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\tcontent TEXT NOT NULL, \n'
 '\tvariables JSONB, \n'
 '\tis_system BOOLEAN, \n'
 '\tis_active BOOLEAN, \n'
 '\tcategory VARCHAR(100), \n'
 '\ttags JSONB, \n'
 '\tusage_count INTEGER, \n'
 '\ttemplate_key VARCHAR(100), \n'
 '\tversion INTEGER, \n'
 '\tparent_id UUID, \n'
 '\tab_experiment_key VARCHAR(100), \n'
 '\tab_variant VARCHAR(50), \n'
 '\tab_weight FLOAT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_prompt_templates_ab_experiment_key ON prompt_templates (ab_experiment_key)',
 'CREATE INDEX ix_prompt_templates_tenant_active ON prompt_templates (tenant_id, is_active)',
 'CREATE INDEX ix_prompt_templates_template_key ON prompt_templates (template_key)',
 'CREATE INDEX ix_prompt_templates_tenant_template_key_version ON prompt_templates (tenant_id, template_key, version)',
 'CREATE INDEX ix_prompt_templates_tenant_system ON prompt_templates (tenant_id, is_system)',
 'CREATE INDEX ix_prompt_templates_tenant_name ON prompt_templates (tenant_id, name)',
 'CREATE INDEX ix_prompt_templates_tenant_ab_experiment ON prompt_templates (tenant_id, ab_experiment_key)',
 'CREATE INDEX ix_prompt_templates_tenant_id ON prompt_templates (tenant_id)',
 'CREATE TABLE tenants (\n'
 '\tid UUID NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tstatus VARCHAR(32), \n'
 '\tplan VARCHAR(64), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (name)\n'
 ')',
 'CREATE TABLE tenant_members (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tuser_id VARCHAR(255), \n'
 '\trole VARCHAR(32), \n'
 '\tis_current BOOLEAN, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_tenant_members_tenant_id ON tenant_members (tenant_id)',
 'CREATE TABLE users (\n'
 '\tid UUID NOT NULL, \n'
 '\temail VARCHAR(255) NOT NULL, \n'
 '\tusername VARCHAR(64) NOT NULL, \n'
 '\tpassword_hash VARCHAR(255) NOT NULL, \n'
 '\tis_active BOOLEAN, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tlast_login_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE UNIQUE INDEX ix_users_username ON users (username)',
 'CREATE UNIQUE INDEX ix_users_email ON users (email)',
 'CREATE TABLE kg_entities (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tname VARCHAR(500) NOT NULL, \n'
 '\ttype VARCHAR(100) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\tnormalized_name VARCHAR(500) NOT NULL, \n'
 '\tvector JSON, \n'
 '\textra_data JSON, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_kg_entities_tenant_id ON kg_entities (tenant_id)',
 'CREATE INDEX ix_kg_entities_normalized_name ON kg_entities (normalized_name)',
 'CREATE INDEX ix_kg_entities_type ON kg_entities (type)',
 'CREATE TABLE kg_source_events (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdocument_id UUID, \n'
 '\tchunk_id UUID, \n'
 '\ttitle VARCHAR(255) NOT NULL, \n'
 '\tsummary TEXT NOT NULL, \n'
 '\tcontent TEXT NOT NULL, \n'
 '\tcontent_vector JSON, \n'
 '\tstart_time TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tend_time TIMESTAMP WITHOUT TIME ZONE, \n'
 '\t"references" JSON, \n'
 '\textra_data JSON, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_kg_source_events_chunk_id ON kg_source_events (chunk_id)',
 'CREATE INDEX ix_kg_source_events_document_id ON kg_source_events (document_id)',
 'CREATE INDEX ix_kg_source_events_tenant_id ON kg_source_events (tenant_id)',
 'CREATE TABLE audit_logs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tactor_id VARCHAR(255), \n'
 '\taction VARCHAR(128) NOT NULL, \n'
 '\tresource_type VARCHAR(64), \n'
 '\tresource_id VARCHAR(255), \n'
 '\trequest_id VARCHAR(128), \n'
 '\tip VARCHAR(64), \n'
 '\tuser_agent VARCHAR(512), \n'
 '\tdetails JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_audit_logs_resource_id ON audit_logs (resource_id)',
 'CREATE INDEX ix_audit_logs_actor_id ON audit_logs (actor_id)',
 'CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at)',
 'CREATE INDEX ix_audit_logs_action ON audit_logs (action)',
 'CREATE INDEX ix_audit_logs_resource_type ON audit_logs (resource_type)',
 'CREATE INDEX ix_audit_logs_tenant_id ON audit_logs (tenant_id)',
 'CREATE INDEX ix_audit_logs_request_id ON audit_logs (request_id)',
 'CREATE TABLE conversation_summaries (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tconversation_id UUID NOT NULL, \n'
 '\tsummary TEXT NOT NULL, \n'
 '\tlast_message_count INTEGER NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_conversation_summary_once UNIQUE (tenant_id, conversation_id)\n'
 ')',
 'CREATE INDEX ix_conversation_summaries_conversation_id ON conversation_summaries (conversation_id)',
 'CREATE INDEX ix_conversation_summaries_tenant_id ON conversation_summaries (tenant_id)',
 'CREATE TABLE dataset_categories (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tparent_id UUID, \n'
 '\tsort_order INTEGER NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_dataset_categories_tenant_id_id UNIQUE (tenant_id, id), \n'
 '\tCONSTRAINT uq_dataset_categories_tenant_parent_name UNIQUE (tenant_id, parent_id, name), \n'
 '\tCONSTRAINT fk_dataset_categories_tenant_parent FOREIGN KEY(tenant_id, parent_id) REFERENCES dataset_categories '
 '(tenant_id, id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_dataset_categories_tenant_id ON dataset_categories (tenant_id)',
 'CREATE INDEX ix_dataset_categories_parent_id ON dataset_categories (parent_id)',
 'CREATE TABLE messages (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tconversation_id UUID NOT NULL, \n'
 '\trole VARCHAR(20) NOT NULL, \n'
 '\tcontent TEXT NOT NULL, \n'
 '\tcitations JSONB, \n'
 '\ttoken_count INTEGER, \n'
 '\tmessage_metadata JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_messages_tenant_id ON messages (tenant_id)',
 'CREATE TABLE dataset_permissions (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\taccount_id VARCHAR(255) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_dataset_permission_member UNIQUE (tenant_id, dataset_id, account_id), \n'
 '\tCONSTRAINT fk_dataset_permissions_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets '
 '(tenant_id, id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_dataset_permissions_dataset_id ON dataset_permissions (dataset_id)',
 'CREATE INDEX ix_dataset_permissions_account_id ON dataset_permissions (account_id)',
 'CREATE INDEX ix_dataset_permissions_tenant_id ON dataset_permissions (tenant_id)',
 'CREATE TABLE documents (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID, \n'
 '\tuser_id UUID, \n'
 '\tfilename VARCHAR(500) NOT NULL, \n'
 '\tfile_type VARCHAR(10) NOT NULL, \n'
 '\tfile_size BIGINT NOT NULL, \n'
 '\tfile_path VARCHAR(1000) NOT NULL, \n'
 '\towner_id VARCHAR(255), \n'
 '\taccess_mode VARCHAR(50), \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tprocessing_progress INTEGER, \n'
 '\tcurrent_stage VARCHAR(50), \n'
 '\terror_message TEXT, \n'
 '\tchunk_count INTEGER, \n'
 '\ttotal_characters INTEGER, \n'
 '\tmetadata JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tprocessed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tarchived_at TIMESTAMP WITH TIME ZONE, \n'
 '\tdisabled_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_documents_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets (tenant_id, id)\n'
 ')',
 'CREATE INDEX ix_documents_dataset_id ON documents (dataset_id)',
 'CREATE INDEX ix_documents_tenant_id ON documents (tenant_id)',
 'CREATE TABLE ragas_evaluation_items (\n'
 '\tid UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tconversation_id UUID, \n'
 '\tturn_index INTEGER NOT NULL, \n'
 '\tuser_message_id UUID, \n'
 '\tassistant_message_id UUID, \n'
 '\tuser_input TEXT NOT NULL, \n'
 '\tresponse TEXT NOT NULL, \n'
 '\tretrieved_contexts JSONB, \n'
 '\tcitations JSONB, \n'
 '\tscores JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(run_id) REFERENCES ragas_evaluation_runs (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_ragas_evaluation_items_conversation_id ON ragas_evaluation_items (conversation_id)',
 'CREATE INDEX ix_ragas_evaluation_items_run_id ON ragas_evaluation_items (run_id)',
 'CREATE INDEX ix_ragas_evaluation_items_tenant_id ON ragas_evaluation_items (tenant_id)',
 'CREATE TABLE ragas_regression_items (\n'
 '\tid UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcase_id UUID NOT NULL, \n'
 '\tquestion TEXT NOT NULL, \n'
 '\tresponse TEXT NOT NULL, \n'
 '\tretrieved_contexts JSONB, \n'
 '\tcitations JSONB, \n'
 '\tscores JSONB, \n'
 '\tmeta JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(run_id) REFERENCES ragas_regression_runs (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_ragas_regression_items_run_id ON ragas_regression_items (run_id)',
 'CREATE INDEX ix_ragas_regression_items_case_id ON ragas_regression_items (case_id)',
 'CREATE INDEX ix_ragas_regression_items_tenant_id ON ragas_regression_items (tenant_id)',
 'CREATE TABLE evidence_items (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\tsuite_id UUID NOT NULL, \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tquery TEXT NOT NULL, \n'
 '\texpected_answer TEXT, \n'
 '\ttags JSONB NOT NULL, \n'
 '\tsource_metadata JSONB NOT NULL, \n'
 '\treference_sources JSONB NOT NULL, \n'
 '\tretrieval_snapshot JSONB, \n'
 '\trag_config_snapshot JSONB, \n'
 '\tnotes TEXT, \n'
 '\tregression_case_id UUID, \n'
 '\tcreated_by VARCHAR(255), \n'
 '\treviewed_by VARCHAR(255), \n'
 '\tapproved_by VARCHAR(255), \n'
 '\tarchived_by VARCHAR(255), \n'
 '\treviewed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tapproved_at TIMESTAMP WITH TIME ZONE, \n'
 '\tarchived_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(suite_id) REFERENCES evidence_suites (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_evidence_items_approved_by ON evidence_items (approved_by)',
 'CREATE INDEX ix_evidence_items_created_by ON evidence_items (created_by)',
 'CREATE INDEX ix_evidence_items_archived_by ON evidence_items (archived_by)',
 'CREATE INDEX ix_evidence_items_suite_id ON evidence_items (suite_id)',
 'CREATE INDEX ix_evidence_items_regression_case_id ON evidence_items (regression_case_id)',
 'CREATE INDEX ix_evidence_items_tenant_id ON evidence_items (tenant_id)',
 'CREATE INDEX ix_evidence_items_dataset_id ON evidence_items (dataset_id)',
 'CREATE INDEX ix_evidence_items_reviewed_by ON evidence_items (reviewed_by)',
 'CREATE INDEX ix_evidence_items_status ON evidence_items (status)',
 'CREATE TABLE kg_event_entities (\n'
 '\tid UUID NOT NULL, \n'
 '\tevent_id UUID NOT NULL, \n'
 '\tentity_id UUID NOT NULL, \n'
 '\tweight NUMERIC(5, 2) NOT NULL, \n'
 '\trole VARCHAR(100), \n'
 '\textra_data JSON, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(event_id) REFERENCES kg_source_events (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_kg_event_entities_entity_id ON kg_event_entities (entity_id)',
 'CREATE INDEX ix_kg_event_entities_event_id ON kg_event_entities (event_id)',
 'CREATE TABLE connector_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID, \n'
 '\tconnector_id VARCHAR(80) NOT NULL, \n'
 '\trequested_by VARCHAR(255), \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tconfig JSONB NOT NULL, \n'
 '\tstats JSONB NOT NULL, \n'
 '\terror_message TEXT, \n'
 '\ttask_id VARCHAR(255), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_connector_runs_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) '
 'ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_connector_runs_dataset_id ON connector_runs (dataset_id)',
 'CREATE INDEX ix_connector_runs_tenant_id ON connector_runs (tenant_id)',
 'CREATE INDEX ix_connector_runs_connector_id ON connector_runs (connector_id)',
 'CREATE TABLE connector_configs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\tconnector_id VARCHAR(80) NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tenabled BOOLEAN NOT NULL, \n'
 '\tschedule_cron VARCHAR(64), \n'
 '\tconfig JSONB NOT NULL, \n'
 '\tstate JSONB NOT NULL, \n'
 '\tlast_run_at TIMESTAMP WITH TIME ZONE, \n'
 '\tlast_error TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_connector_configs_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets (tenant_id, '
 'id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_connector_configs_connector_id ON connector_configs (connector_id)',
 'CREATE INDEX ix_connector_configs_dataset_id ON connector_configs (dataset_id)',
 'CREATE INDEX ix_connector_configs_tenant_id ON connector_configs (tenant_id)',
 'CREATE TABLE dataset_category_memberships (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_dataset_category_membership UNIQUE (tenant_id, dataset_id, category_id), \n'
 '\tCONSTRAINT fk_dataset_category_memberships_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets '
 '(tenant_id, id) ON DELETE CASCADE, \n'
 '\tCONSTRAINT fk_dataset_category_memberships_tenant_category FOREIGN KEY(tenant_id, category_id) REFERENCES '
 'dataset_categories (tenant_id, id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_dataset_category_memberships_dataset_id ON dataset_category_memberships (dataset_id)',
 'CREATE INDEX ix_dataset_category_memberships_tenant_id ON dataset_category_memberships (tenant_id)',
 'CREATE INDEX ix_dataset_category_memberships_category_id ON dataset_category_memberships (category_id)',
 'CREATE TABLE dataset_precheck_scan_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\trequested_by VARCHAR(255), \n'
 '\tkind VARCHAR(32) NOT NULL, \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tprogress INTEGER NOT NULL, \n'
 '\tconfig JSONB NOT NULL, \n'
 '\tsummary JSONB NOT NULL, \n'
 '\tartifacts JSONB NOT NULL, \n'
 '\terror_message TEXT, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_dataset_precheck_scan_runs_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets '
 '(tenant_id, id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_dataset_precheck_scan_runs_tenant_dataset_created_at ON dataset_precheck_scan_runs (tenant_id, '
 'dataset_id, created_at)',
 'CREATE INDEX ix_dataset_precheck_scan_runs_dataset_id ON dataset_precheck_scan_runs (dataset_id)',
 'CREATE INDEX ix_dataset_precheck_scan_runs_tenant_id ON dataset_precheck_scan_runs (tenant_id)',
 'CREATE INDEX ix_dataset_precheck_scan_runs_tenant_status_created_at ON dataset_precheck_scan_runs (tenant_id, '
 'status, created_at)',
 'CREATE TABLE dataset_profile_scan_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\trequested_by VARCHAR(255), \n'
 '\tkind VARCHAR(32) NOT NULL, \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tprogress INTEGER NOT NULL, \n'
 '\tconfig JSONB NOT NULL, \n'
 '\tsummary JSONB NOT NULL, \n'
 '\terror_message TEXT, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_dataset_profile_scan_runs_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets '
 '(tenant_id, id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_dataset_profile_scan_runs_tenant_id ON dataset_profile_scan_runs (tenant_id)',
 'CREATE INDEX ix_dataset_profile_scan_runs_tenant_dataset_created_at ON dataset_profile_scan_runs (tenant_id, '
 'dataset_id, created_at)',
 'CREATE INDEX ix_dataset_profile_scan_runs_dataset_id ON dataset_profile_scan_runs (dataset_id)',
 'CREATE INDEX ix_dataset_profile_scan_runs_tenant_status_created_at ON dataset_profile_scan_runs (tenant_id, status, '
 'created_at)',
 'CREATE TABLE ingestion_runs (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID, \n'
 '\tkind VARCHAR(80) NOT NULL, \n'
 '\trequested_by VARCHAR(255), \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tconfig JSONB NOT NULL, \n'
 '\tstats JSONB NOT NULL, \n'
 '\terror_message TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_ingestion_runs_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets (tenant_id, id) '
 'ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_ingestion_runs_tenant_id ON ingestion_runs (tenant_id)',
 'CREATE INDEX ix_ingestion_runs_kind ON ingestion_runs (kind)',
 'CREATE INDEX ix_ingestion_runs_dataset_id ON ingestion_runs (dataset_id)',
 'CREATE TABLE db_catalog_tables (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdataset_id UUID NOT NULL, \n'
 '\tconnector_config_id UUID, \n'
 '\tengine VARCHAR(32) NOT NULL, \n'
 '\tdb_name VARCHAR(255) NOT NULL, \n'
 '\tschema_name VARCHAR(255), \n'
 '\ttable_name VARCHAR(255) NOT NULL, \n'
 '\ttable_type VARCHAR(32) NOT NULL, \n'
 '\tcomment TEXT, \n'
 '\tfingerprint VARCHAR(80) NOT NULL, \n'
 '\tlast_seen_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_db_catalog_tables_tenant_dataset FOREIGN KEY(tenant_id, dataset_id) REFERENCES datasets (tenant_id, '
 'id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(connector_config_id) REFERENCES connector_configs (id) ON DELETE SET NULL\n'
 ')',
 'CREATE INDEX ix_db_catalog_tables_engine ON db_catalog_tables (engine)',
 'CREATE INDEX ix_db_catalog_tables_fingerprint ON db_catalog_tables (fingerprint)',
 'CREATE INDEX ix_db_catalog_tables_connector_config_id ON db_catalog_tables (connector_config_id)',
 'CREATE INDEX ix_db_catalog_tables_tenant_id ON db_catalog_tables (tenant_id)',
 'CREATE INDEX ix_db_catalog_tables_dataset_id ON db_catalog_tables (dataset_id)',
 'CREATE INDEX ix_db_catalog_tables_db_name ON db_catalog_tables (db_name)',
 'CREATE INDEX ix_db_catalog_tables_schema_name ON db_catalog_tables (schema_name)',
 'CREATE INDEX ix_db_catalog_tables_table_name ON db_catalog_tables (table_name)',
 'CREATE TABLE document_permissions (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdocument_id UUID NOT NULL, \n'
 '\taccount_id VARCHAR(255) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_document_permission_member UNIQUE (document_id, account_id), \n'
 '\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_document_permissions_tenant_id ON document_permissions (tenant_id)',
 'CREATE INDEX ix_document_permissions_account_id ON document_permissions (account_id)',
 'CREATE INDEX ix_document_permissions_document_id ON document_permissions (document_id)',
 'CREATE TABLE document_chunks (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdocument_id UUID NOT NULL, \n'
 '\tchunk_index INTEGER NOT NULL, \n'
 '\tcontent TEXT NOT NULL, \n'
 '\tpage_number INTEGER, \n'
 '\tstart_char INTEGER, \n'
 '\tend_char INTEGER, \n'
 '\tmetadata JSONB, \n'
 '\tvector_id VARCHAR(255), \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tdisabled_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_document_chunks_tenant_id ON document_chunks (tenant_id)',
 'CREATE TABLE document_parsed_contents (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tdocument_id UUID NOT NULL, \n'
 '\tmarkdown_content TEXT NOT NULL, \n'
 '\toriginal_markdown_content TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_document_parsed_contents_tenant_id ON document_parsed_contents (tenant_id)',
 'CREATE UNIQUE INDEX ix_document_parsed_contents_document_id ON document_parsed_contents (document_id)',
 'CREATE TABLE connector_run_documents (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\tdocument_id UUID NOT NULL, \n'
 '\tsource_ref VARCHAR(1000), \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(run_id) REFERENCES connector_runs (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_connector_run_documents_tenant_id ON connector_run_documents (tenant_id)',
 'CREATE INDEX ix_connector_run_documents_run_id ON connector_run_documents (run_id)',
 'CREATE INDEX ix_connector_run_documents_document_id ON connector_run_documents (document_id)',
 'CREATE TABLE message_feedback (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tconversation_id UUID NOT NULL, \n'
 '\tmessage_id UUID NOT NULL, \n'
 '\taccount_id VARCHAR(255) NOT NULL, \n'
 '\trating INTEGER NOT NULL, \n'
 '\treason TEXT, \n'
 '\ttags JSONB, \n'
 '\texpected_answer TEXT, \n'
 '\textra JSONB, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_message_feedback_once UNIQUE (tenant_id, message_id, account_id), \n'
 '\tFOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_message_feedback_conversation_id ON message_feedback (conversation_id)',
 'CREATE INDEX ix_message_feedback_message_id ON message_feedback (message_id)',
 'CREATE INDEX ix_message_feedback_tenant_id ON message_feedback (tenant_id)',
 'CREATE INDEX ix_message_feedback_account_id ON message_feedback (account_id)',
 'CREATE TABLE ingestion_run_documents (\n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\tdocument_id UUID NOT NULL, \n'
 '\tsource_ref VARCHAR(1000), \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(run_id) REFERENCES ingestion_runs (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_ingestion_run_documents_tenant_id ON ingestion_run_documents (tenant_id)',
 'CREATE INDEX ix_ingestion_run_documents_document_id ON ingestion_run_documents (document_id)',
 'CREATE INDEX ix_ingestion_run_documents_run_id ON ingestion_run_documents (run_id)',
 'CREATE TABLE db_catalog_columns (\n'
 '\tid UUID NOT NULL, \n'
 '\ttable_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tname VARCHAR(255) NOT NULL, \n'
 '\tdata_type VARCHAR(255), \n'
 '\tnullable BOOLEAN, \n'
 '\tcomment TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(table_id) REFERENCES db_catalog_tables (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_db_catalog_columns_table_id ON db_catalog_columns (table_id)',
 'CREATE INDEX ix_db_catalog_columns_name ON db_catalog_columns (name)',
 'CREATE TABLE db_profile_snapshots (\n'
 '\tid UUID NOT NULL, \n'
 '\ttable_id UUID NOT NULL, \n'
 '\tentitlement_hash VARCHAR(255) NOT NULL, \n'
 '\tprofile JSONB NOT NULL, \n'
 '\tsample_meta JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(table_id) REFERENCES db_catalog_tables (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_db_profile_snapshots_table_id ON db_profile_snapshots (table_id)',
 'CREATE INDEX ix_db_profile_snapshots_entitlement_hash ON db_profile_snapshots (entitlement_hash)']

DOWNGRADE_SQL = ['DROP TABLE db_profile_snapshots',
 'DROP TABLE db_catalog_columns',
 'DROP TABLE ingestion_run_documents',
 'DROP TABLE message_feedback',
 'DROP TABLE connector_run_documents',
 'DROP TABLE document_parsed_contents',
 'DROP TABLE document_chunks',
 'DROP TABLE document_permissions',
 'DROP TABLE db_catalog_tables',
 'DROP TABLE ingestion_runs',
 'DROP TABLE dataset_profile_scan_runs',
 'DROP TABLE dataset_precheck_scan_runs',
 'DROP TABLE dataset_category_memberships',
 'DROP TABLE connector_configs',
 'DROP TABLE connector_runs',
 'DROP TABLE kg_event_entities',
 'DROP TABLE evidence_items',
 'DROP TABLE ragas_regression_items',
 'DROP TABLE ragas_evaluation_items',
 'DROP TABLE documents',
 'DROP TABLE dataset_permissions',
 'DROP TABLE messages',
 'DROP TABLE dataset_categories',
 'DROP TABLE conversation_summaries',
 'DROP TABLE audit_logs',
 'DROP TABLE kg_source_events',
 'DROP TABLE kg_entities',
 'DROP TABLE users',
 'DROP TABLE tenant_members',
 'DROP TABLE tenants',
 'DROP TABLE prompt_templates',
 'DROP TABLE governance_profiles',
 'DROP TABLE evidence_suites',
 'DROP TABLE ragas_regression_runs',
 'DROP TABLE ragas_regression_cases',
 'DROP TABLE ragas_evaluation_runs',
 'DROP TABLE datasets',
 'DROP TABLE chunk_presets',
 'DROP TABLE conversations',
 'DROP TYPE datasetpermissionenum']
# fmt: on


def upgrade() -> None:
    for stmt in UPGRADE_SQL:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    for stmt in DOWNGRADE_SQL:
        op.execute(sa.text(stmt))
