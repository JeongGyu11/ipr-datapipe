-- 상품공시실에서 수집한 문서의 최신 상태를 문서 1건당 1행으로 관리한다.
-- PostgreSQL 14+ 기준.

BEGIN;

CREATE TABLE rs_disclosure_documents (
    document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 논리 식별자는 짧은 업무용 코드다. 파일 내용 SHA-256은 아래
    -- sha256 컬럼에 별도로 보관한다.
    document_key VARCHAR(14) NOT NULL,
    product_version_key VARCHAR(19) NOT NULL,

    -- 수집 주체 대분류. API/HTML/Playwright 등 상세 방식은
    -- source_metadata에 collection_method_detail로 저장할 수 있다.
    collector_type VARCHAR(16) NOT NULL DEFAULT 'PYTHON',

    company_code VARCHAR(32) NOT NULL,
    company_name TEXT NOT NULL,
    product_category TEXT,
    source_product_id TEXT,
    product_name TEXT NOT NULL,
    product_name_normalized TEXT NOT NULL,

    sale_status VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN',
    sale_status_raw TEXT,
    sale_start_date DATE,
    sale_end_date DATE,
    status_checked_at TIMESTAMPTZ,
    status_changed_at TIMESTAMPTZ,
    status_missing_count INTEGER NOT NULL DEFAULT 0,

    document_date DATE,
    document_date_basis VARCHAR(32),

    -- NO_DOCUMENT_LINK 항목은 문서 유형이 없을 수 있다.
    document_type VARCHAR(32),
    document_label TEXT,
    source_page_url TEXT,
    document_url TEXT,
    original_filename TEXT,
    -- 보험사 원본 버전 키, checkpoint_key, POST 다운로드 힌트 등
    -- 어댑터별 안정적인 추가 정보만 보관한다.
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    saved_relative_path TEXT,
    file_size BIGINT,
    sha256 VARCHAR(64),
    file_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',

    -- file_status는 현재 파일 상태, last_attempt_status는 마지막 시도 결과다.
    last_attempt_status VARCHAR(32),
    error_message TEXT,
    downloaded_at TIMESTAMPTZ,

    last_seen_run_id TEXT,
    last_download_run_id TEXT,
    last_status_run_id TEXT,

    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 신규 설치의 최종 identity 계약. 기존 설치는 006 migration에서
    -- 동일한 기본값과 CHECK를 적용한다.
    identity_version SMALLINT NOT NULL DEFAULT 4,

    CONSTRAINT uq_rs_disclosure_documents_document_key
        UNIQUE (document_key),

    CONSTRAINT ck_rs_disclosure_documents_document_key
        CHECK (document_key ~ '^DOC_[0-9A-Za-z]{10}$'),

    CONSTRAINT ck_rs_disclosure_documents_product_version_key
        CHECK (product_version_key ~ '^PROD_VER_[0-9A-Za-z]{10}$'),

    CONSTRAINT ck_rs_disclosure_documents_identity_version
        CHECK (identity_version = 4),

    CONSTRAINT ck_rs_disclosure_documents_collector_type
        CHECK (collector_type IN ('PYTHON', 'RPA')),

    CONSTRAINT ck_rs_disclosure_documents_sale_status
        CHECK (sale_status IN ('ACTIVE', 'ENDED', 'UNKNOWN')),

    CONSTRAINT ck_rs_disclosure_documents_document_type
        CHECK (
            document_type IS NULL
            OR document_type IN (
                'POLICY',
                'SUMMARY',
                'METHOD',
                'UNKNOWN_DOCUMENT_TYPE'
            )
        ),

    CONSTRAINT ck_rs_disclosure_documents_file_status
        CHECK (
            file_status IN (
                'PENDING',
                'AVAILABLE',
                'UNAVAILABLE',
                'INVALID',
                'MANUAL_REVIEW'
            )
        ),

    CONSTRAINT ck_rs_disclosure_documents_last_attempt_status
        CHECK (
            last_attempt_status IS NULL
            OR last_attempt_status IN (
                'SUCCESS',
                'DUPLICATE_SKIPPED',
                'NO_DOCUMENT_LINK',
                'INVALID_RESPONSE',
                'INVALID_FILE',
                'DOWNLOAD_FAILED',
                'ACCESS_DENIED',
                'UNKNOWN_DOCUMENT_TYPE',
                'MANUAL_REVIEW_REQUIRED',
                'DRY_RUN'
            )
        ),

    CONSTRAINT ck_rs_disclosure_documents_status_missing_count
        CHECK (status_missing_count >= 0),

    CONSTRAINT ck_rs_disclosure_documents_file_size
        CHECK (file_size IS NULL OR file_size >= 0),

    CONSTRAINT ck_rs_disclosure_documents_sha256
        CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
);

COMMENT ON TABLE rs_disclosure_documents IS
    '상품공시실 수집 문서의 최신 상태(문서 1건당 1행)';
COMMENT ON COLUMN rs_disclosure_documents.collector_type IS
    '수집 주체 대분류: PYTHON 또는 RPA';
COMMENT ON COLUMN rs_disclosure_documents.document_key IS
    '논리 문서 중복 방지용 DOC_ 접두사 + 결정적 Base62 10자리 코드';
COMMENT ON COLUMN rs_disclosure_documents.product_version_key IS
    '동일 상품 판매 버전의 문서를 묶는 PROD_VER_ 접두사 + 결정적 Base62 10자리 코드';
COMMENT ON COLUMN rs_disclosure_documents.source_metadata IS
    '어댑터별 원본 버전 키, checkpoint_key, 비밀값을 제외한 POST 다운로드 힌트';
COMMENT ON COLUMN rs_disclosure_documents.file_status IS
    '현재 물리 파일 상태';
COMMENT ON COLUMN rs_disclosure_documents.last_attempt_status IS
    '마지막 다운로드 시도의 처리 결과';

CREATE FUNCTION set_rs_disclosure_documents_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_rs_disclosure_documents_updated_at
BEFORE UPDATE ON rs_disclosure_documents
FOR EACH ROW
EXECUTE FUNCTION set_rs_disclosure_documents_updated_at();

CREATE INDEX ix_rs_disclosure_documents_company_date
    ON rs_disclosure_documents (company_code, document_date DESC);

CREATE INDEX ix_rs_disclosure_documents_product_version
    ON rs_disclosure_documents (product_version_key);

CREATE INDEX ix_rs_disclosure_documents_sale_status
    ON rs_disclosure_documents (company_code, sale_status);

CREATE INDEX ix_rs_disclosure_documents_file_status
    ON rs_disclosure_documents (file_status, last_attempt_status);

CREATE INDEX ix_rs_disclosure_documents_last_seen
    ON rs_disclosure_documents (last_seen_at DESC);

CREATE INDEX ix_rs_disclosure_documents_sha256
    ON rs_disclosure_documents (sha256)
    WHERE sha256 IS NOT NULL;

COMMIT;
