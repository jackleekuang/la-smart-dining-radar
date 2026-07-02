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
    ARRAY(
        SELECT JSON_EXTRACT_SCALAR(cat, '$.title')
        FROM UNNEST(JSON_EXTRACT_ARRAY(categories)) AS cat
    ) AS category_titles,
    latitude,
    longitude,
    round(rating * ln(review_count + 1), 3) as popularity_score,
    is_closed,
    address1,
    address2,
    address3,
    city,
    zip_code,
    state,
    country,
    transactions,
    business_hours,
    ingestion_timestamp
from staged
where is_closed = false
