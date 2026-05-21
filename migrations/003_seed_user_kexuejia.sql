-- =============================================================================
-- 15 Signals · 直接在 SQL 里创建第二个登录账号
-- =============================================================================
-- 前置：migrations/001_auth_user_id.sql 已经跑过
-- 运行方式：Supabase Dashboard → SQL Editor → 粘贴运行
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    user_email text := 'kexuejia@gmail.com';
    user_pass  text := 'beijing2026';

    new_user_id uuid := gen_random_uuid();
BEGIN
    IF EXISTS (SELECT 1 FROM auth.users WHERE email = user_email) THEN
        RAISE NOTICE '账号 % 已存在于 auth.users，跳过创建', user_email;
        RETURN;
    END IF;

    INSERT INTO auth.users (
        instance_id, id, aud, role, email,
        encrypted_password, email_confirmed_at,
        raw_app_meta_data, raw_user_meta_data,
        created_at, updated_at,
        confirmation_token, email_change, email_change_token_new, recovery_token
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
        now(), now(),
        '', '', '', ''
    );

    INSERT INTO auth.identities (
        id, user_id, identity_data, provider, provider_id,
        last_sign_in_at, created_at, updated_at
    ) VALUES (
        gen_random_uuid(),
        new_user_id,
        jsonb_build_object('sub', new_user_id::text, 'email', user_email),
        'email',
        user_email,
        now(), now(), now()
    );

    RAISE NOTICE '已创建账号：% (id=%)，密码=%', user_email, new_user_id, user_pass;
END $$;
