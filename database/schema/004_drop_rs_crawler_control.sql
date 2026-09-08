-- 더 이상 사용하지 않는 crawler control 객체를 제거한다.
-- CASCADE를 사용하지 않아 예상하지 못한 의존 객체가 있으면 배포를 중단한다.

BEGIN;

DROP TABLE IF EXISTS public.rs_crawler_control;
DROP FUNCTION IF EXISTS public.set_rs_crawler_control_updated_at();

COMMIT;
