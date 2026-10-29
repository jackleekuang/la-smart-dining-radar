{#- Latest version of each LA City business location (raw is append-only across incremental loads).
    Field names follow the Socrata dataset r4uk-afju; the payload_missing_account Soda check
    fails the run if the city renames the id column. -#}
with source as (
    select * from {{ source('raw_v2', 'raw_la_city_businesses') }}
),

parsed as (
    select
        json_value(payload, '$.location_account') as location_account,
        json_value(payload, '$.business_name') as business_name,
        json_value(payload, '$.dba_name') as dba_name,
        json_value(payload, '$.street_address') as street_address,
        json_value(payload, '$.city') as city,
        left(json_value(payload, '$.zip_code'), 5) as zip_code,
        json_value(payload, '$.naics') as naics,
        json_value(payload, '$.primary_naics_description') as naics_description,
        safe_cast(left(json_value(payload, '$.location_start_date'), 10) as date) as location_start_date,
        safe_cast(left(json_value(payload, '$.location_end_date'), 10) as date) as location_end_date,
        safe_cast(json_value(payload, '$.location.latitude') as float64) as lat,
        safe_cast(json_value(payload, '$.location.longitude') as float64) as lon,
        source_updated_at,
        _loaded_at,
        row_number() over (
            partition by json_value(payload, '$.location_account')
            order by source_updated_at desc, _loaded_at desc
        ) as _rn
    from source
)

select * except (_rn)
from parsed
where _rn = 1
  and location_account is not null
