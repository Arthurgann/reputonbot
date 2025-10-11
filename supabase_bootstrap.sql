
-- Minimal bootstrap for platform rules & interactions

create table if not exists platform_rules (
  id bigserial primary key,
  platform text not null unique,
  system_prompt text not null,
  created_at timestamp with time zone default now()
);

create table if not exists interactions (
  id bigserial primary key,
  tg_user_id text,
  platform text,
  input_text text,
  output_json jsonb,
  created_at timestamp with time zone default now()
);

-- Seed example
insert into platform_rules(platform, system_prompt) values
('yandex_maps', 'Ты помогаешь формировать корректные жалобы для Яндекс.Карт...'),
('ozon', 'Ты помогаешь формировать корректные жалобы для Ozon...')
on conflict (platform) do nothing;
