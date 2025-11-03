create or replace function public.rate_limit_check_and_inc(
  p_chat_id bigint,
  p_day date,
  p_threshold int
)
returns table(allowed boolean, hits_before int)
language plpgsql
as $$
declare
  v_hits int;
begin
  insert into rate_limits(chat_id, utc_day, hits, threshold)
  values (p_chat_id, p_day, 0, p_threshold)
  on conflict (chat_id, utc_day) do nothing;

  select hits into v_hits
  from rate_limits
  where chat_id = p_chat_id and utc_day = p_day;

  if v_hits < p_threshold then
    update rate_limits
    set hits = hits + 1
    where chat_id = p_chat_id and utc_day = p_day;
    return query select true, v_hits;
  else
    return query select false, v_hits;
  end if;
end
$$;

create unique index if not exists rate_limits_chat_day_uq
  on rate_limits(chat_id, utc_day);