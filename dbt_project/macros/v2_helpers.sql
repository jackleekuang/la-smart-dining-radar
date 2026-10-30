{#- Helpers for the v2 open-data models. BigQuery dialect. -#}

{#- First non-null JSON value among several paths. Overture's BigQuery mirror nests arrays as
    {list: [{element: ...}]} (Parquet LIST encoding) while the GeoParquet files use plain arrays;
    taxonomy/category fields have also been renamed across releases. Listing every known path
    keeps staging working across releases instead of silently returning NULL. -#}
{% macro json_coalesce(payload, paths) -%}
    coalesce(
        {%- for p in paths %}
        json_value({{ payload }}, '{{ p }}'){{ "," if not loop.last }}
        {%- endfor %}
    )
{%- endmacro %}

{#- Business-name normalization used for entity matching. -#}
{% macro normalize_name(expr) -%}
    trim(regexp_replace(
        regexp_replace(
            regexp_replace(
                regexp_replace(lower(coalesce({{ expr }}, '')), r'&', ' and '),
                r"[^a-z0-9 ]", ' '),
            r'\b(the|inc|llc|corp|corporation|co|ltd|restaurant|restaurants|cafe)\b', ' '),
        r'\s+', ' '))
{%- endmacro %}

{#- 0..1 similarity from Levenshtein distance; 1 = identical. -#}
{% macro name_similarity(a, b) -%}
    case
        when {{ a }} = '' or {{ b }} = '' then 0
        else 1 - safe_divide(edit_distance({{ a }}, {{ b }}), greatest(length({{ a }}), length({{ b }})))
    end
{%- endmacro %}

{#- Leading street number, used as a cheap address agreement signal. -#}
{% macro street_number(expr) -%}
    regexp_extract(coalesce({{ expr }}, ''), r'^\s*(\d+)')
{%- endmacro %}

{#- Precise food-place filter on Overture's primary category (snake_case taxonomy names). -#}
{% macro is_food_category(expr) -%}
    regexp_contains(coalesce({{ expr }}, ''),
        r'restaurant|^cafe|_cafe|coffee|bakery|^bar$|_bar$|^pub$|brewery|food_truck|diner|bistro|eatery|tea_room|dessert|ice_cream|juice|^deli$|_deli$|pizza|taco|sushi|ramen|noodle|bbq|barbecue|food_court|bagel|donut|creperie|gastropub|winery|wine_bar|cocktail')
{%- endmacro %}
