{#- Warn (not fail) when fewer than 20% of currently present places match the LA City registry.
    A sudden drop usually means a matching or upstream-schema problem, not reality. -#}
{{ config(severity='warn', tags=['v2']) }}

with present as (
    select count(*) as n_present, countif(la_city_location_account is not null) as n_matched
    from {{ ref('dim_restaurant_v2') }}
    where is_present_latest
)

select *, safe_divide(n_matched, n_present) as match_rate
from present
where n_present > 0
  and safe_divide(n_matched, n_present) < 0.20
