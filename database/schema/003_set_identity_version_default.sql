-- 단축 key 전환 전 legacy DB의 중간 기본값. 신규 설치와 이미 전환된
-- v4 DB에는 적용하지 않으며, 최종 기본값은 005/006이 4로 고정한다.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM rs_disclosure_documents
        WHERE identity_version <> 4
           OR document_key !~ '^DOC_[0-9A-Za-z]{10}$'
           OR product_version_key !~ '^PROD_VER_[0-9A-Za-z]{10}$'
    ) THEN
        ALTER TABLE rs_disclosure_documents
            ALTER COLUMN identity_version SET DEFAULT 2;
    END IF;
END;
$$;

COMMIT;
