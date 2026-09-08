-- 문서별 실시간 UPSERT와 오래된 실행 결과의 역전 방지를 위한 증분 스키마.
-- 001 스키마가 이미 적용된 DB와 신규 DB 모두에 안전하게 적용할 수 있다.

BEGIN;

ALTER TABLE rs_disclosure_documents
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS identity_version SMALLINT NOT NULL DEFAULT 4;

COMMENT ON COLUMN rs_disclosure_documents.last_attempt_at IS
    '성공·실패·중복 건너뛰기를 포함한 마지막 문서 처리 시각';
COMMENT ON COLUMN rs_disclosure_documents.identity_version IS
    'document_key/product_version_key 생성 규칙 버전';

CREATE INDEX IF NOT EXISTS ix_rs_disclosure_documents_last_attempt
    ON rs_disclosure_documents (last_attempt_at DESC);

COMMIT;
