with source as (
    select * from {{ source('raw', 'raw_yelp_restaurants') }}
),

deduped as (
    select
        *,
        row_number() over (partition by id order by ingestion_timestamp desc) as row_num
    from source
    where id is not null
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
    ingestion_timestamp
from deduped
where row_num = 1
