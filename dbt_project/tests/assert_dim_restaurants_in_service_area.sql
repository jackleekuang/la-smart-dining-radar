-- Contract test, written independently of the model logic: nothing outside
-- LA County (state, ZIP prefix, bounding box) may reach the published mart.
-- Returns offending rows; any row fails the run.

select
    dim.id,
    dim.name,
    dim.state,
    dim.zip_code,
    dim.latitude,
    dim.longitude
from {{ ref('dim_restaurants') }} as dim
left join {{ ref('service_area_zip3') }} as zip3
    on substr(dim.zip_code, 1, 3) = zip3.zip3
where coalesce(dim.state, '') != 'CA'
   or zip3.zip3 is null
   or dim.latitude not between {{ var('service_area')['min_lat'] }} and {{ var('service_area')['max_lat'] }}
   or dim.longitude not between {{ var('service_area')['min_lng'] }} and {{ var('service_area')['max_lng'] }}
