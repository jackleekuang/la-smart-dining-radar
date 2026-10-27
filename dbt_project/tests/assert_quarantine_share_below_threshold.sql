-- Anomaly gate on the vendor feed. A handful of bad records per run is normal
-- and handled by quarantine; a jump above var('max_quarantine_share') means the
-- extractor or the vendor changed behaviour, so stop rather than publish a
-- mart that silently lost a large slice of restaurants.

with counts as (
    select
        countif(not is_in_service_area) as quarantined,
        count(*) as total
    from {{ ref('int_restaurants_service_area') }}
    where is_closed = false
)

select
    quarantined,
    total,
    safe_divide(quarantined, total) as quarantine_share
from counts
where safe_divide(quarantined, total) > {{ var('max_quarantine_share') }}
