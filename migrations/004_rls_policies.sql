-- =============================================================================
-- 15 Signals · Migration 004: 给 sessions / turns / signal_scores / users 启用 RLS
-- =============================================================================
-- 设计：
--   - 前端用 anon key + 用户 access_token 直连 Supabase，RLS 做行级隔离
--   - serverless function（api/session/*）用同样的 token 调，等同前端权限
--   - service_role key 绕过 RLS，仅 api/session/close.js 这类需要后台权限的用
--
-- 关键映射：
--   auth.uid() (uuid) → public.users.auth_user_id → public.users.id (bigint)
--   靠 public.current_public_user_id() 这个 STABLE 函数做转换
-- =============================================================================

-- ----- 1. helper: 当前登录用户的 public.users.id -----
CREATE OR REPLACE FUNCTION public.current_public_user_id()
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id FROM public.users WHERE auth_user_id = auth.uid() LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION public.current_public_user_id() TO authenticated, anon;

-- ----- 2. 启用 RLS -----
ALTER TABLE public.users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.turns          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signal_scores  ENABLE ROW LEVEL SECURITY;

-- ----- 3. policies -----

-- public.users: 用户只能看到/更新自己那一行
DROP POLICY IF EXISTS users_self_select ON public.users;
CREATE POLICY users_self_select ON public.users
    FOR SELECT TO authenticated
    USING (auth_user_id = auth.uid());

DROP POLICY IF EXISTS users_self_update ON public.users;
CREATE POLICY users_self_update ON public.users
    FOR UPDATE TO authenticated
    USING (auth_user_id = auth.uid())
    WITH CHECK (auth_user_id = auth.uid());

-- sessions: 完全私有
DROP POLICY IF EXISTS sessions_self_select ON public.sessions;
CREATE POLICY sessions_self_select ON public.sessions
    FOR SELECT TO authenticated
    USING (user_id = public.current_public_user_id());

DROP POLICY IF EXISTS sessions_self_insert ON public.sessions;
CREATE POLICY sessions_self_insert ON public.sessions
    FOR INSERT TO authenticated
    WITH CHECK (user_id = public.current_public_user_id());

DROP POLICY IF EXISTS sessions_self_update ON public.sessions;
CREATE POLICY sessions_self_update ON public.sessions
    FOR UPDATE TO authenticated
    USING (user_id = public.current_public_user_id())
    WITH CHECK (user_id = public.current_public_user_id());

-- turns: 通过 session 间接判断归属
DROP POLICY IF EXISTS turns_self_select ON public.turns;
CREATE POLICY turns_self_select ON public.turns
    FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = turns.session_id
          AND s.user_id = public.current_public_user_id()
    ));

DROP POLICY IF EXISTS turns_self_insert ON public.turns;
CREATE POLICY turns_self_insert ON public.turns
    FOR INSERT TO authenticated
    WITH CHECK (EXISTS (
        SELECT 1 FROM public.sessions s
        WHERE s.id = turns.session_id
          AND s.user_id = public.current_public_user_id()
    ));

-- signal_scores: 只读自己的（写由 close.js 用 service-role 跳过 RLS 完成）
DROP POLICY IF EXISTS signal_scores_self_select ON public.signal_scores;
CREATE POLICY signal_scores_self_select ON public.signal_scores
    FOR SELECT TO authenticated
    USING (user_id = public.current_public_user_id());

-- =============================================================================
-- 验证：以匿名身份查 sessions 应返回 0 行；以登录用户身份查应只看到自己的
-- 回滚：DROP POLICY 各条；ALTER TABLE ... DISABLE ROW LEVEL SECURITY;
-- =============================================================================
