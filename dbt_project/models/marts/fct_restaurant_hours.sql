with source as (
    select id, business_hours
    from {{ ref('dim_restaurants') }}
    where business_hours is not null and business_hours != '[]'
),

hours_blocks as (
    select id, JSON_EXTRACT_ARRAY(block, '$.open') as open_periods
    from source, UNNEST(JSON_EXTRACT_ARRAY(business_hours)) as block
),

exploded as (
    select
        id as restaurant_id,
        CAST(JSON_EXTRACT_SCALAR(period, '$.day') as INT64) as day_of_week,
        JSON_EXTRACT_SCALAR(period, '$.start') as start_raw,
        JSON_EXTRACT_SCALAR(period, '$.end') as end_raw,
        CAST(JSON_EXTRACT_SCALAR(period, '$.is_overnight') as BOOL) as is_overnight
    from hours_blocks, UNNEST(open_periods) as period
)

select
    restaurant_id,
    day_of_week,
    ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][OFFSET(day_of_week)] as day_name,
    PARSE_TIME('%H%M', start_raw) as start_time,
    PARSE_TIME('%H%M', end_raw) as end_time,
    is_overnight
from exploded
