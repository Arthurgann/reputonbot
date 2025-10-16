
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
  created_at timestamp with time zone default now()
);

-- Seed example
insert into platform_rules(platform, system_prompt, rules, report_url) values
('yandex_maps', 'Ты эксперт по модерации отзывов на Яндекс.Картах. Помогаешь формировать корректные жалобы.', '{"rule1": "Отзывы должны быть объективными", "rule2": "Запрещены оскорбления"}', 'https://yandex.ru/support/maps/troubleshooting/reviews.html'),
('ozon', 'Ты эксперт по модерации отзывов на Ozon. Помогаешь формировать корректные жалобы.', '{"rule1": "Отзывы должны соответствовать правилам площадки", "rule2": "Требуются доказательства"}', 'https://seller.ozon.ru/app/review/moderation')
on conflict (platform) do nothing;
