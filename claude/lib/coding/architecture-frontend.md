# Architecture: Frontend

- Leaf modules import no UI: a leaf module (`routes.ts`, `lib/api/*`) imports no UI component; move a type both sides need into the domain type file (`lib/api/{domain}/types/`) and import it from there, also where existing code already imports the other way.
