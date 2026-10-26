{#- One row per place: lifecycle across all loaded releases + latest attributes.
    Derived from immutable per-release snapshots, so it can be rebuilt from scratch at any time
    and answers "what did we know as of release X" without look-ahead. -#}
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
    select max(release_idx) as latest_idx, count(*) as n_releases from releases
),

obs_idx as (
    select o.*, r.release_idx
    from obs as o
    inner join releases as r using (snapshot_release, snapshot_date)
),

lifecycle as (
    select
        place_id,
        min(snapshot_date) as first_seen_date,
        max(snapshot_date) as last_seen_date,
        min(release_idx) as first_seen_idx,
        max(release_idx) as last_seen_idx,
        count(*) as releases_present
    from obs_idx
    group by place_id
),

latest_attrs as (
    select * except (rn)
    from (
        select
            place_id, place_name, primary_category, operating_status, confidence,
            street_address, locality, postcode, website, brand_name, lat, lon,
            row_number() over (partition by place_id order by release_idx desc) as rn
        from obs_idx
    )
    where rn = 1
)

select
    l.place_id,
    a.place_name,
    a.primary_category,
    a.operating_status as last_operating_status,
    a.confidence,
    a.street_address,
    a.locality,
    a.postcode,
    a.website,
    a.brand_name,
    a.lat,
    a.lon,
    l.first_seen_date,
    l.last_seen_date,
    l.releases_present,
    b.n_releases as releases_loaded,
    l.last_seen_idx = b.latest_idx as is_present_latest,
    -- Gaps mean the place dropped out of one or more releases and came back.
    l.releases_present < (l.last_seen_idx - l.first_seen_idx + 1) as has_presence_gap
from lifecycle as l
inner join latest_attrs as a using (place_id)
cross join bounds as b
