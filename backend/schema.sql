CREATE TABLE IF NOT EXISTS analysis_tasks (
    task_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    file_name TEXT NOT NULL,
    image_path TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    top_class TEXT NOT NULL,
    top_class_cn TEXT NOT NULL,
    reliability_level TEXT NOT NULL,
    fold_agreement INTEGER NOT NULL,
    analysis_json TEXT NOT NULL,
    reviewer_name TEXT,
    review_decision TEXT,
    corrected_class TEXT,
    corrected_class_cn TEXT,
    review_comment TEXT,
    reviewed_at TEXT,
    quality_status TEXT NOT NULL DEFAULT 'PASS',
    priority TEXT NOT NULL DEFAULT 'ROUTINE',
    image_dhash TEXT,
    attention_path TEXT,
    owner_user_id TEXT,
    starred_at TEXT,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    accepted_terms_at TEXT NOT NULL,
    accepted_privacy_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    user_agent TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS openai_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    encrypted_api_key TEXT NOT NULL,
    key_suffix TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SAVED',
    verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS llm_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    key_suffix TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SAVED',
    verified_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, provider),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS user_llm_preferences (
    user_id TEXT PRIMARY KEY,
    selected_provider TEXT NOT NULL DEFAULT 'openai',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS account_audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    event_type TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES analysis_tasks(task_id)
);

CREATE TABLE IF NOT EXISTS evidence_sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    version TEXT NOT NULL,
    publication_date TEXT,
    authority TEXT NOT NULL,
    scope TEXT NOT NULL,
    locator TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    section TEXT NOT NULL,
    page_number INTEGER,
    content TEXT NOT NULL,
    UNIQUE(source_id, chunk_index),
    FOREIGN KEY(source_id) REFERENCES evidence_sources(source_id)
);

CREATE TABLE IF NOT EXISTS evidence_queries (
    query_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    question TEXT NOT NULL,
    support_level TEXT NOT NULL,
    answer_json TEXT NOT NULL,
    include_in_report INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES analysis_tasks(task_id)
);

CREATE TABLE IF NOT EXISTS agent_evaluation_runs (
    run_id TEXT PRIMARY KEY,
    dataset_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    passed_cases INTEGER NOT NULL,
    overall_score REAL NOT NULL,
    status_accuracy REAL NOT NULL,
    citation_accuracy REAL NOT NULL,
    content_accuracy REAL NOT NULL,
    safety_accuracy REAL NOT NULL,
    unsupported_accuracy REAL NOT NULL,
    results_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    linked_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(linked_task_id) REFERENCES analysis_tasks(task_id)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    support_level TEXT,
    risk_level TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    retrieval_query TEXT,
    safety_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS agent_message_citations (
    citation_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    citation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    locator TEXT NOT NULL,
    page_number INTEGER,
    section TEXT,
    score REAL NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    UNIQUE(message_id, citation_id),
    FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
);

CREATE TABLE IF NOT EXISTS agent_usage_records (
    usage_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
    FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
);

CREATE TABLE IF NOT EXISTS agent_audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    message_id TEXT,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
    FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
);

CREATE TABLE IF NOT EXISTS rag_evaluation_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT,
    dataset_version TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    passed_cases INTEGER NOT NULL,
    faithfulness_score REAL NOT NULL,
    citation_score REAL NOT NULL,
    refusal_score REAL NOT NULL,
    privacy_score REAL NOT NULL,
    overall_score REAL NOT NULL,
    results_json TEXT NOT NULL,
    completed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_created
ON analysis_tasks(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_reliability_created
ON analysis_tasks(reliability_level, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_class_created
ON analysis_tasks(top_class, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_priority_created
ON analysis_tasks(priority, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_owner_created
ON analysis_tasks(owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_owner_archived_created
ON analysis_tasks(owner_user_id, archived_at, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_owner_starred
ON analysis_tasks(owner_user_id, starred_at DESC)
WHERE starred_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_task_created
ON audit_events(task_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_evidence_chunks_source
ON evidence_chunks(source_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_evidence_queries_task_created
ON evidence_queries(task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_evaluation_runs_completed
ON agent_evaluation_runs(completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_expires
ON user_sessions(user_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_account_audit_user_created
ON account_audit_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_credentials_user_provider
ON llm_credentials(user_id, provider);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_user_updated
ON agent_conversations(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation_created
ON agent_messages(conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_agent_citations_message
ON agent_message_citations(message_id, ordinal ASC);

CREATE INDEX IF NOT EXISTS idx_agent_usage_user_created
ON agent_usage_records(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_audit_user_created
ON agent_audit_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_evaluation_completed
ON rag_evaluation_runs(completed_at DESC);
