-- Classify every restaurant against the service-area contract (LA County).
--
-- Yelp occasionally returns records whose address and coordinates disagree,
-- or that sit far outside the searched neighbourhoods (seen in production:
-- a Pizza Hut in Saint Clairsville, OH and a "Monte Rio, CA" listing). These
-- are vendor-side data errors, so instead of guessing which field is right we
-- quarantine the record: it is excluded from dim_restaurants and kept, with a
-- reason, in dq_restaurants_quarantine for review.

with restaurants as (
    select * from {{ ref('int_restaurants_city_mapped') }}
),

service_area_zip3 as (
    select zip3 from {{ ref('service_area_zip3') }}
),

classified as (
    select
        restaurants.*,
        case
            when restaurants.latitude is null or restaurants.longitude is null
                then 'missing_coordinates'
            when coalesce(restaurants.state, '') != 'CA'
                then 'non_ca_state'
            when service_area_zip3.zip3 is null
                then 'zip_outside_service_area'
            when restaurants.latitude not between {{ var('service_area')['min_lat'] }} and {{ var('service_area')['max_lat'] }}
              or restaurants.longitude not between {{ var('service_area')['min_lng'] }} and {{ var('service_area')['max_lng'] }}
                then 'coordinates_outside_service_area'
        end as service_area_issue
    from restaurants
    left join service_area_zip3
        on substr(restaurants.zip_code, 1, 3) = service_area_zip3.zip3
)

select
    *,
    service_area_issue is null as is_in_service_area
from classified
