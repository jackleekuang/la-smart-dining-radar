{#- Openings, closures and net change per ZIP per Overture release. -#}
with active as (
    select postcode, snapshot_release, snapshot_date, count(distinct place_id) as active_places
    from {{ ref('stg_overture__places') }}
    where postcode is not null
    group by postcode, snapshot_release, snapshot_date
),

events as (
    select
        postcode,
        event_release as snapshot_release,
        countif(event_type in ('appeared', 'reappeared')) as openings,
        countif(event_type = 'disappeared') as closures,
        countif(event_type = 'status_changed') as status_changes
    from {{ ref('int_overture__place_events') }}
    where postcode is not null
    group by postcode, event_release
)

select
    concat(a.postcode, '|', a.snapshot_release) as zip_release_key,
    a.postcode,
    a.snapshot_release,
    a.snapshot_date,
    a.active_places,
    coalesce(e.openings, 0) as openings,
    coalesce(e.closures, 0) as closures,
    coalesce(e.openings, 0) - coalesce(e.closures, 0) as net_change,
    coalesce(e.status_changes, 0) as status_changes
from active as a
left join events as e using (postcode, snapshot_release)
