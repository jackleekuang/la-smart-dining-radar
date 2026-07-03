with source as (
    select * from {{ source('raw', 'raw_yelp_restaurants') }}
),

deduped as (
    select
        *,
        row_number() over (partition by id order by ingestion_timestamp desc) as row_num
    from source
    where id is not null
),

cleaned as (
    select
        *,
        -- Yelp's location.city is free text entered by business owners, so it
        -- arrives with inconsistent whitespace/casing/annotations. Strip the
        -- mechanical noise here; true aliases (e.g. "W Hollywood") still need
        -- the city_alias_map seed, applied in int_restaurants_city_mapped.
        initcap(
            trim(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(trim(city), r'\s*\([^)]*\)\s*$', ''),
                            r',\s*$', ''
                        ),
                        r'(?i)\s+ca$', ''
                    ),
                    r'\s+', ' '
                )
            )
        ) as city_cleaned
    from deduped
    where row_num = 1
)

select
    id,
    name,
    rating,
    review_count,
    price,
    categories,
    latitude,
    longitude,
    ingestion_timestamp,
    is_closed,
    address1,
    address2,
    address3,
    city as city_raw,
    city_cleaned as city,
    zip_code,
    state,
    country,
    transactions,
    business_hours
from cleaned
