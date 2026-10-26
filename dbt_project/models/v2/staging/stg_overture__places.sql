{#- One row per place per Overture release (food places only), fields parsed from the JSON payload. -#}
with source as (
    select * from {{ source('raw_v2', 'raw_overture_places') }}
),

parsed as (
    select
        place_id,
        snapshot_release,
        snapshot_date,
        lon,
        lat,
        {{ json_coalesce('payload', ['$.names.primary']) }} as place_name,
        lower({{ json_coalesce('payload', [
            '$.taxonomy.primary',
            '$.basic_category',
            '$.categories.primary'
        ]) }}) as primary_category,
        safe_cast({{ json_coalesce('payload', ['$.confidence']) }} as float64) as confidence,
        lower(coalesce({{ json_coalesce('payload', ['$.operating_status']) }}, 'open')) as operating_status,
        {{ json_coalesce('payload', [
            '$.addresses[0].freeform',
            '$.addresses.list[0].element.freeform'
        ]) }} as street_address,
        {{ json_coalesce('payload', [
            '$.addresses[0].locality',
            '$.addresses.list[0].element.locality'
        ]) }} as locality,
        left({{ json_coalesce('payload', [
            '$.addresses[0].postcode',
            '$.addresses.list[0].element.postcode'
        ]) }}, 5) as postcode,
        {{ json_coalesce('payload', [
            '$.websites[0]',
            '$.websites.list[0].element'
        ]) }} as website,
        {{ json_coalesce('payload', ['$.brand.names.primary']) }} as brand_name,
        _loaded_at,
        row_number() over (
            partition by place_id, snapshot_release order by _loaded_at desc
        ) as _rn
    from source
)

select
    concat(place_id, '|', snapshot_release) as place_release_key,
    * except (_rn)
from parsed
where _rn = 1
  and {{ is_food_category('primary_category') }}
