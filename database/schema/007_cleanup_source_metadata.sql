-- source_metadata의 identity 중복을 제거하고 manifest provenance를 보호한다.
--
-- document_key/product_version_key/identity_version는 최상위 컬럼이
-- authoritative하므로 JSONB에 중복 저장하지 않는다. migration provenance,
-- checkpoint_key, source_locator는 archive 재현에 필요하므로 그대로 둔다.
-- updated_at trigger는 정리 대상 행의 기존 값을 보존하도록 일시적으로
-- 비활성화한다. 모든 작업은 한 트랜잭션에서 수행되어 재실행 가능하다.

BEGIN;

-- 이 migration은 기존 행을 모두 검사한 뒤에만 trigger를 잠시 비활성화한다.
-- 잘못된 provenance를 자동 보정하면 source_row의 원본 의미가 바뀌므로
-- 운영자가 원인을 확인할 수 있도록 행 수와 함께 즉시 중단한다.
DO $$
DECLARE
    malformed_count bigint;
    duplicate_count bigint;
    table_owner text;
    is_superuser boolean;
BEGIN
    SELECT pg_get_userbyid(c.relowner), r.rolsuper
      INTO table_owner, is_superuser
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    JOIN pg_roles AS r ON r.rolname = current_user
    WHERE n.nspname = 'public' AND c.relname = 'rs_disclosure_documents';

    IF table_owner IS NULL THEN
        RAISE EXCEPTION '007 preflight 실패: public.rs_disclosure_documents 테이블을 찾을 수 없습니다';
    END IF;
    IF NOT (is_superuser OR table_owner = current_user) THEN
        RAISE EXCEPTION
            '007 preflight 실패: trigger 비활성화 권한이 없습니다 (table_owner=%, current_user=%)',
            table_owner, current_user;
    END IF;

    SELECT COUNT(*)
      INTO malformed_count
    FROM rs_disclosure_documents
    WHERE source_metadata->'migration'->>'source' = 'manifest.csv'
      AND COALESCE(
          source_metadata->'migration'->>'source_row' ~ '^[1-9][0-9]*$',
          FALSE
      ) = FALSE;
    IF malformed_count > 0 THEN
        RAISE EXCEPTION
            '007 preflight 실패: manifest.csv source_row 형식 오류 %건 (양의 정수 필요)',
            malformed_count;
    END IF;

    SELECT COUNT(*)
      INTO duplicate_count
    FROM (
        SELECT source_metadata->'migration'->>'source_row'
        FROM rs_disclosure_documents
        WHERE source_metadata->'migration'->>'source' = 'manifest.csv'
        GROUP BY source_metadata->'migration'->>'source_row'
        HAVING COUNT(*) > 1
    ) AS duplicates;
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION
            '007 preflight 실패: manifest.csv source_row 중복 그룹 %개',
            duplicate_count;
    END IF;
END;
$$;

ALTER TABLE rs_disclosure_documents
    DISABLE TRIGGER trg_rs_disclosure_documents_updated_at;

UPDATE rs_disclosure_documents
SET source_metadata = source_metadata - ARRAY[
    'document_key', 'product_version_key', 'identity_version'
]::text[]
WHERE source_metadata ?| ARRAY[
    'document_key', 'product_version_key', 'identity_version'
];

ALTER TABLE rs_disclosure_documents
    ENABLE TRIGGER trg_rs_disclosure_documents_updated_at;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND conrelid = 'public.rs_disclosure_documents'::regclass
          AND conname = 'ck_rs_disclosure_documents_manifest_source_row'
    ) THEN
        ALTER TABLE rs_disclosure_documents
            ADD CONSTRAINT ck_rs_disclosure_documents_manifest_source_row
            CHECK (
                source_metadata->'migration'->>'source' IS DISTINCT FROM 'manifest.csv'
                OR COALESCE(
                    source_metadata->'migration'->>'source_row' ~ '^[1-9][0-9]*$',
                    FALSE
                )
            );
    END IF;
END;
$$;

-- manifest.csv의 immutable source_row를 DB 행 하나에만 연결한다.  JSONB
-- source_row는 migration이 정수로 기록하므로 source/source_row 문자열의
-- 고유성만 강제해 runtime event가 provenance를 복제하지 못하게 한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rs_disclosure_documents_manifest_source_row
    ON rs_disclosure_documents (
        (source_metadata->'migration'->>'source'),
        (source_metadata->'migration'->>'source_row')
    )
    WHERE source_metadata->'migration'->>'source' = 'manifest.csv'
      AND source_metadata->'migration'->>'source_row' IS NOT NULL;

COMMIT;
