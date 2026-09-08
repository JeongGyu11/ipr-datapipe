-- 일반 수집 런타임의 최종 identity 계약을 DB에서도 강제한다.
-- 모든 legacy key/version 전환이 끝난 DB에서만 적용할 수 있다.

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
        RAISE EXCEPTION
            'identity v4 CHECK를 적용할 수 없습니다: legacy 또는 잘못된 key/version 행이 있습니다';
    END IF;

    ALTER TABLE rs_disclosure_documents
        ALTER COLUMN identity_version SET DEFAULT 4;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND conrelid = 'public.rs_disclosure_documents'::regclass
          AND conname = 'ck_rs_disclosure_documents_identity_version'
    ) THEN
        ALTER TABLE rs_disclosure_documents
            ADD CONSTRAINT ck_rs_disclosure_documents_identity_version
            CHECK (identity_version = 4);
    END IF;
END;
$$;

COMMIT;
