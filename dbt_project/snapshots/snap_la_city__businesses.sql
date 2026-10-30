{#- SCD2 history of LA City business records. The city overwrites rows in place (e.g. sets
    location_end_date when a business closes), so without a snapshot that history is lost.
    Overture is NOT snapshotted here: its history is already landed immutably per release in
    raw, and deriving history from that is replayable — a dbt snapshot is not. -#}
{% snapshot snap_la_city__businesses %}
{{
    config(
        target_schema=env_var('BQ_DATASET_SNAPSHOTS', 'snapshots'),
        unique_key='location_account',
        strategy='timestamp',
        updated_at='source_updated_at',
        invalidate_hard_deletes=True,
    )
}}
select * from {{ ref('stg_la_city__businesses') }}
{% endsnapshot %}
