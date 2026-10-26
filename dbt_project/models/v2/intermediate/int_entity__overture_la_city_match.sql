{#- Entity resolution: link each Overture place to at most one LA City business location.
    Two sources describe the same restaurant with different ids, spellings and coordinates —
    the same problem as mapping one security across several vendor identifiers.

    Blocking: same 5-digit ZIP AND within var('match_max_distance_m') metres.
    Scoring:  0.60 name similarity (best of legal name / DBA)
            + 0.25 street-number agreement
            + 0.15 proximity
    Keep the best candidate per place if score >= var('match_min_score'); a business location
    may only be claimed by its single best-scoring place (no many-to-one). -#}
with places as (
    select
        place_id,
        postcode,
        {{ normalize_name('place_name') }} as name_norm,
        {{ street_number('street_address') }} as street_no,
        st_geogpoint(lon, lat) as geo
    from {{ ref('int_overture__place_history') }}
    where lat is not null and lon is not null
),

businesses as (
    select
        location_account,
        zip_code,
        {{ normalize_name('business_name') }} as legal_norm,
        {{ normalize_name('dba_name') }} as dba_norm,
        {{ street_number('street_address') }} as street_no,
        st_geogpoint(lon, lat) as geo
    from {{ ref('snap_la_city__businesses') }}
    where dbt_valid_to is null
      and lat is not null and lon is not null
),

candidates as (
    select
        p.place_id,
        b.location_account,
        st_distance(p.geo, b.geo) as distance_m,
        greatest(
            {{ name_similarity('p.name_norm', 'b.legal_norm') }},
            {{ name_similarity('p.name_norm', 'b.dba_norm') }}
        ) as name_sim,
        if(p.street_no != '' and p.street_no = b.street_no, 1, 0) as street_no_match
    from places as p
    inner join businesses as b
        on p.postcode = b.zip_code
       and st_dwithin(p.geo, b.geo, {{ var('match_max_distance_m') }})
),

scored as (
    select
        *,
        round(
            0.60 * name_sim
            + 0.25 * street_no_match
            + 0.15 * (1 - distance_m / {{ var('match_max_distance_m') }}),
        4) as match_score
    from candidates
),

best_per_place as (
    select * except (rn)
    from (
        select *, row_number() over (partition by place_id order by match_score desc, distance_m) as rn
        from scored
        where match_score >= {{ var('match_min_score') }}
    )
    where rn = 1
)

select
    place_id,
    location_account,
    match_score,
    name_sim,
    street_no_match = 1 as street_number_agrees,
    distance_m,
    case
        when match_score >= 0.85 then 'high'
        when match_score >= 0.70 then 'medium'
        else 'low'
    end as match_confidence
from (
    select *, row_number() over (partition by location_account order by match_score desc, distance_m) as rn
    from best_per_place
)
where rn = 1
