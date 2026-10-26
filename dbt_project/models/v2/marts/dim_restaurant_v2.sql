{#- One row per Overture food place in LA with a unified status that reconciles both sources.
    Disagreements are surfaced as their own status instead of being silently resolved. -#}
with place as (
    select * from {{ ref('int_overture__place_history') }}
),

match as (
    select * from {{ ref('int_entity__overture_la_city_match') }}
),

license as (
    select location_account, business_name, dba_name, naics, location_start_date, location_end_date
    from {{ ref('snap_la_city__businesses') }}
    where dbt_valid_to is null
)

select
    cast(p.place_id as string) as place_id,
    cast(p.place_name as string) as place_name,
    cast(p.primary_category as string) as primary_category,
    cast(p.street_address as string) as street_address,
    cast(p.postcode as string) as postcode,
    cast(p.lat as float64) as lat,
    cast(p.lon as float64) as lon,
    cast(p.first_seen_date as date) as first_seen_date,
    cast(p.last_seen_date as date) as last_seen_date,
    cast(p.is_present_latest as bool) as is_present_latest,
    cast(p.last_operating_status as string) as last_operating_status,
    cast(m.location_account as string) as la_city_location_account,
    cast(m.match_score as float64) as match_score,
    cast(m.match_confidence as string) as match_confidence,
    cast(l.naics as string) as la_city_naics,
    cast(l.location_start_date as date) as license_start_date,
    cast(l.location_end_date as date) as license_end_date,
    cast(
        case
            when not p.is_present_latest or p.last_operating_status = 'permanently_closed' then
                if(l.location_end_date is not null, 'closed_confirmed', 'closed_unverified')
            when p.last_operating_status = 'temporarily_closed' then 'temporarily_closed'
            when l.location_end_date is not null then 'conflict'  -- map says open, registry says closed
            when m.location_account is not null then 'open_confirmed'
            else 'open_unverified'
        end
    as string) as unified_status
from place as p
left join match as m using (place_id)
left join license as l on l.location_account = m.location_account
