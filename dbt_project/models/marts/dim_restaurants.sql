with staged as (
    select * from {{ ref('int_restaurants_service_area') }}
)

select
    id,
    name,
    rating,
    rating is not null as is_rated,
    review_count,
    coalesce(price, 'Unknown') as price,
    categories,
    ARRAY(
        SELECT JSON_EXTRACT_SCALAR(cat, '$.title')
        FROM UNNEST(JSON_EXTRACT_ARRAY(categories)) AS cat
    ) AS category_titles,
    latitude,
    longitude,
    -- NULL for unrated restaurants (rating is NULL), so they sort last
    round(rating * ln(review_count + 1), 3) as popularity_score,
    is_closed,
    address1,
    address2,
    address3,
    city,
    city_raw,
    zip_code,
    state,
    country,
    transactions,
    business_hours,
    ingestion_timestamp
from staged
where is_closed = false
  and is_in_service_area
