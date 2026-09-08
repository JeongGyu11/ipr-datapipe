-- DOC_/PROD_VER_ 접두사 + BLAKE2b/Base62 10자리 identity 규칙을 사용하는
-- 신규 수집 행의 기본 버전.
-- 64자리 기존 행은 migrate_short_identity_keys.py, 접두사 없는 Base62 10자리
-- 행은 migrate_prefixed_identity_keys.py가 변환한다.

BEGIN;

-- 기존 64자리 행이 있는 DB에서는 기본값만 먼저 바꾸지 않는다. 명시적인
-- migrate_short_identity_keys.py --apply가 key와 identity_version을 함께
-- 전환한 뒤에만 신규 기본값 4를 적용한다.
DO $$
BEGIN
    IF to_regclass('public.rs_disclosure_documents') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM rs_disclosure_documents
           WHERE document_key !~ '^DOC_[0-9A-Za-z]{10}$'
              OR product_version_key !~ '^PROD_VER_[0-9A-Za-z]{10}$'
       ) THEN
        ALTER TABLE rs_disclosure_documents
            ALTER COLUMN identity_version SET DEFAULT 4;
    END IF;
END;
$$;

COMMIT;
