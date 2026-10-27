-- popularity_score may only be NULL for unrated restaurants.

select id, rating, review_count, popularity_score
from {{ ref('dim_restaurants') }}
where rating is not null
  and popularity_score is null
