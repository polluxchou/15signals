-- =============================================================================
-- 15 Signals · 直接在 SQL 里创建一个登录账号（绕过 Supabase Auth API）
-- =============================================================================
-- ⚠️ 用途说明：
--   - 仅适合：本地/开发环境造个测试号
--   - 不适合：生产环境（生产应走 supa.auth.signUp 或 Admin API）
--   - 前置：migrations/001_auth_user_id.sql 已经跑过（trigger 会自动 upsert public.users）
--
-- 运行方式：Supabase Dashboard → SQL Editor → 粘贴运行
-- =============================================================================

-- 装 pgcrypto（Supabase 默认已装，这里幂等保险）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    -- ▼▼▼ 改这两行就够了 ▼▼▼
    user_email text := 'hkiaowzf@gmail.com';
    user_pass  text := 'shanghai2026';
    -- ▲▲▲ ▲▲▲ ▲▲▲

    new_user_id uuid := gen_random_uuid();
BEGIN
    -- 如果同邮箱已存在，先告知再退出（避免 unique 冲突时一脸懵）
    IF EXISTS (SELECT 1 FROM auth.users WHERE email = user_email) THEN
        RAISE NOTICE '账号 % 已存在于 auth.users，跳过创建', user_email;
        RETURN;
    END IF;

    -- 1) 插入 auth.users
    INSERT INTO auth.users (
        instance_id,
        id,
        aud,
        role,
        email,
        encrypted_password,
        email_confirmed_at,      -- 直接标记已确认，省去发邮件
        raw_app_meta_data,
        raw_user_meta_data,
        created_at,
        updated_at,
        confirmation_token,
        email_change,
        email_change_token_new,
        recovery_token
    ) VALUES (
        '00000000-0000-0000-0000-000000000000',
        new_user_id,
        'authenticated',
        'authenticated',
        user_email,
        crypt(user_pass, gen_salt('bf')),
        now(),
        '{"provider":"email","providers":["email"]}'::jsonb,
        '{}'::jsonb,
        now(),
        now(),
        '', '', '', ''
    );

    -- 2) 插入 auth.identities —— Supabase 用密码登录需要这一行配套
    INSERT INTO auth.identities (
        id,
        user_id,
        identity_data,
        provider,
        provider_id,
        last_sign_in_at,
        created_at,
        updated_at
    ) VALUES (
        gen_random_uuid(),
        new_user_id,
        jsonb_build_object('sub', new_user_id::text, 'email', user_email),
        'email',
        user_email,           -- 新版 Supabase 要求 provider_id 不为空
        now(),
        now(),
        now()
    );

    RAISE NOTICE '已创建账号：% (id=%)，密码=%', user_email, new_user_id, user_pass;
    RAISE NOTICE 'public.users 由 trigger on_auth_user_created 自动同步一行';
END $$;

-- =============================================================================
-- 验证：
--   SELECT id, email, email_confirmed_at FROM auth.users WHERE email = 'hkiaowzf@gmail.com';
--   SELECT id, email, auth_user_id FROM public.users WHERE email = 'hkiaowzf@gmail.com';
--
-- 清理（如需删账号重来）：
--   DELETE FROM auth.users WHERE email = 'hkiaowzf@gmail.com';
--   （会级联删 auth.identities；public.users 的 auth_user_id 由 ON DELETE SET NULL 置空）
-- =============================================================================
