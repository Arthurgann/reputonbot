
-- v0.1.1 schema sync (interactions: request_id, meta_json + indexes)

-- Minimal bootstrap for platform rules & interactions

create table if not exists platform_rules (
  id bigserial primary key,
  platform text not null unique,
  system_prompt text not null,
  rules jsonb,
  report_url text,
  created_at timestamp with time zone default now()
);

create table if not exists interactions (
  id bigserial primary key,
  tg_user_id text,
  platform text,
  input_text text,
  output_json jsonb,
  created_at timestamp with time zone default now(),
  request_id text,
  meta_json jsonb
);

-- Create chat_state table to store platform selection per chat
create table if not exists chat_state (
  chat_id bigint primary key,
  platform text not null,
  updated_at timestamp default now()
);

-- Add indexes for performance
create index if not exists idx_chat_state_chat_id on chat_state(chat_id);
create index if not exists idx_chat_state_updated_at on chat_state(updated_at);
create index if not exists idx_interactions_chat_id_created_at on interactions(chat_id, created_at desc);

-- Add new columns to interactions table (idempotent)
alter table interactions add column if not exists request_id text;
alter table interactions add column if not exists meta_json jsonb;

-- Additional indexes for interactions table
create index if not exists interactions_user_time_idx on interactions (tg_user_id, created_at DESC);
create unique index if not exists interactions_request_id_uq_partial on interactions (request_id) where request_id is not null;
create index if not exists interactions_meta_json_gin on interactions using gin (meta_json);

-- Additional indexes for other tables
create index if not exists chat_state_updated_at_idx on chat_state (updated_at DESC);

-- Note: For large production tables, consider using CREATE INDEX CONCURRENTLY as an alternative
-- to avoid locking the table during index creation.

-- Trigger to update updated_at on every update
create or replace function update_chat_state_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger chat_state_updated_at_trigger
  before update on chat_state
  for each row
  execute function update_chat_state_updated_at();

-- Add chat_id column to interactions table for consistency
alter table interactions add column if not exists chat_id bigint;
update interactions set chat_id = tg_user_id::bigint where chat_id is null and tg_user_id is not null;

-- Additional indexes for rate_limits table
create index if not exists rate_limits_updated_at_idx on rate_limits (created_at DESC); -- Using created_at since updated_at doesn't exist
create index if not exists rate_limits_chat_id_idx on rate_limits (chat_id);

-- Ensure request_cache has expiration index
create index if not exists request_cache_expires_idx on request_cache (created_at); -- Using created_at since expires_at doesn't exist

-- Create rate_limits table for per-day rate limiting
create table if not exists rate_limits (
  chat_id bigint not null,
  utc_day date not null,
  hits int not null default 0,
  threshold int not null default 10,
  primary key (chat_id, utc_day)
);

-- Create request_cache table for caching by content
create table if not exists request_cache (
  chat_id bigint not null,
  text_hash text not null,
  platform text not null,
  result_json jsonb,
  created_at timestamp with time zone default now(),
  expires_at timestamp with time zone,
  primary key (chat_id, text_hash, platform)
);

-- Add indexes for performance
create index if not exists idx_rate_limits_chat_id_utc_day on rate_limits(chat_id, utc_day);
create index if not exists idx_request_cache_expires_idx on request_cache (expires_at);

-- RPC function for atomic increment of rate_limits
create or replace function increment_rate_limit(p_chat_id bigint, p_utc_day date, p_threshold int)
returns boolean as $$
declare
  current_hits int;
begin
  -- Try to update existing row
  update rate_limits
  set hits = hits + 1
  where chat_id = p_chat_id and utc_day = p_utc_day and hits < p_threshold
  returning hits into current_hits;

  -- If no row was updated, insert new row if under threshold
  if not found then
    insert into rate_limits (chat_id, utc_day, hits, threshold)
    values (p_chat_id, p_utc_day, 1, p_threshold)
    returning hits into current_hits;
  end if;

  -- Return true if increment was successful (hits <= threshold)
  return current_hits is not null and current_hits <= p_threshold;
end;
$$ language plpgsql;

-- Seed example
insert into platform_rules(platform, system_prompt, rules, report_url) values
('yandex_maps', 'Ты эксперт по модерации отзывов на Яндекс.Картах. Помогаешь формировать корректные жалобы.', '{"rule1": "Отзывы должны быть объективными", "rule2": "Запрещены оскорбления"}', 'https://yandex.ru/support/maps/troubleshooting/reviews.html'),
('ozon', 'Ты эксперт по модерации отзывов на Ozon. Помогаешь формировать корректные жалобы.', '{"rule1": "Отзывы должны соответствовать правилам площадки", "rule2": "Требуются доказательства"}', 'https://seller.ozon.ru/app/review/moderation')
on conflict (platform) do nothing;
