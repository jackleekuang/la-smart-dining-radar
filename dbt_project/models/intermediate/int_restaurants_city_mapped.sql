with restaurants as (
    select * from {{ ref('stg_yelp_restaurants') }}
),

alias_map as (
    select * from {{ ref('city_alias_map') }}
)

select
    restaurants.* except (city),
    coalesce(alias_map.canonical_city, restaurants.city) as city
from restaurants
left join alias_map
    on restaurants.city = alias_map.raw_city
