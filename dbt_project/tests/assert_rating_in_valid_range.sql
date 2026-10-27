-- Yelp ratings are 1.0-5.0 in 0.5 steps; 0 must have been converted to NULL
-- in staging. Any rated row outside 1-5 means the sentinel handling broke.

select id, rating
from {{ ref('dim_restaurants') }}
where rating is not null
  and (rating < 1 or rating > 5)
