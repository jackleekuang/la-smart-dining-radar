{#- Change events between consecutive releases: appeared, disappeared, reappeared,
    status_changed, category_changed. The first loaded release is a baseline, so nothing
    "appears" in it. -#}
with obs as (
    select * from {{ ref('stg_overture__places') }}
),

releases as (
    select
        snapshot_release,
        snapshot_date,
        dense_rank() over (order by snapshot_date, snapshot_release) as release_idx
    from (select distinct snapshot_release, snapshot_date from obs)
),

bounds as (
    select min(release_idx) as first_idx, max(release_idx) as latest_idx from releases
),

seq as (
    select
        o.place_id,
        o.postcode,
        o.operating_status,
        o.primary_category,
        r.release_idx,
        lag(r.release_idx) over w as prev_idx,
        lead(r.release_idx) over w as next_idx,
        lag(o.operating_status) over w as prev_status,
        lag(o.primary_category) over w as prev_category
    from obs as o
    inner join releases as r using (snapshot_release, snapshot_date)
    window w as (partition by o.place_id order by r.release_idx)
),

events as (
    -- first sighting after the baseline release
    select place_id, postcode, release_idx as event_idx, 'appeared' as event_type,
           cast(null as string) as from_value, cast(null as string) as to_value
    from seq cross join bounds
    where prev_idx is null and release_idx > first_idx

    union all
    -- back after missing one or more releases
    select place_id, postcode, release_idx, 'reappeared', null, null
    from seq
    where prev_idx is not null and release_idx > prev_idx + 1

    union all
    -- missing from the next release (either permanently or until it reappears)
    select place_id, postcode, release_idx + 1, 'disappeared', null, null
    from seq cross join bounds
    where (next_idx is null and release_idx < latest_idx)
       or (next_idx is not null and next_idx > release_idx + 1)

    union all
    select place_id, postcode, release_idx, 'status_changed', prev_status, operating_status
    from seq
    where prev_idx = release_idx - 1 and prev_status != operating_status

    union all
    select place_id, postcode, release_idx, 'category_changed', prev_category, primary_category
    from seq
    where prev_idx = release_idx - 1 and prev_category != primary_category
)

select
    concat(e.place_id, '|', r.snapshot_release, '|', e.event_type) as event_key,
    e.place_id,
    e.postcode,
    r.snapshot_release as event_release,
    r.snapshot_date as event_date,
    e.event_type,
    e.from_value,
    e.to_value
from events as e
inner join releases as r on r.release_idx = e.event_idx
