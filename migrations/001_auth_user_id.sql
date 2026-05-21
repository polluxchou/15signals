-- =============================================================================
-- 15 Signals · Migration 001: 接入 Supabase Auth
-- 适用：在 Supabase 项目的 SQL Editor 里运行，或本地 psql 连同库执行
-- =============================================================================
--
-- 做了三件事：
--   1. users 表加一列 auth_user_id (uuid) 指向 auth.users(id)
--   2. 给 auth_user_id 加唯一索引 + 普通查询索引
--   3. 装一个 trigger：每次 Supabase Auth 新建一个用户时，自动在 public.users
--      里 upsert 一条对应记录（用 email 关联现有用户；若不存在则新建）
-- =============================================================================

-- ----- 1. 加列 -----
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS auth_user_id uuid;

-- 外键约束（先单独 add constraint，避免在 ALTER COLUMN 时锁表）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_auth_user_id_fkey'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_auth_user_id_fkey
            FOREIGN KEY (auth_user_id)
            REFERENCES auth.users(id)
            ON DELETE SET NULL;
    END IF;
END $$;

-- ----- 2. 索引 -----
CREATE UNIQUE INDEX IF NOT EXISTS users_auth_user_id_uidx
    ON public.users(auth_user_id)
    WHERE auth_user_id IS NOT NULL;

-- ----- 3. trigger：Supabase Auth 新建用户 → 同步到 public.users -----
-- 逻辑：
--   - 如果 public.users 已经有同 email 的行（老用户首次接入 Auth）→ 把 auth_user_id 写进去
--   - 否则插入一条新行
-- 注意：使用 SECURITY DEFINER，因为 trigger 触发时是 supabase_auth_admin 角色，
--       它没有 public.users 的写权限，需要以函数所有者（postgres）身份执行
CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (email, auth_user_id, display_name)
    VALUES (
        NEW.email,
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1))
    )
    ON CONFLICT (email) DO UPDATE
        SET auth_user_id = EXCLUDED.auth_user_id
        WHERE public.users.auth_user_id IS NULL;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_auth_user();

-- =============================================================================
-- 回滚（如需）：
--   DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
--   DROP FUNCTION IF EXISTS public.handle_new_auth_user();
--   ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_auth_user_id_fkey;
--   DROP INDEX IF EXISTS users_auth_user_id_uidx;
--   ALTER TABLE public.users DROP COLUMN IF EXISTS auth_user_id;
-- =============================================================================
