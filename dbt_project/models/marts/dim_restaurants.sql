with staged as (
    select * from {{ ref('stg_yelp_restaurants') }}
)

select
    id,
    name,
    rating,
    review_count,
    coalesce(price, 'Unknown') as price,
    categories,
    latitude,
    longitude,
    round(rating * ln(review_count + 1), 3) as popularity_score,
    ingestion_timestamp
from staged
