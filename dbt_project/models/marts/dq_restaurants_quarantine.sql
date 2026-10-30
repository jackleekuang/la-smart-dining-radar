-- Records that failed the service-area contract and were withheld from
-- dim_restaurants. Kept as a table (not just a failing test) so excluded rows
-- stay visible and countable run over run instead of silently disappearing.

select
    id,
    name,
    city,
    city_raw,
    state,
    zip_code,
    latitude,
    longitude,
    is_closed,
    service_area_issue,
    ingestion_timestamp
from {{ ref('int_restaurants_service_area') }}
where not is_in_service_area
