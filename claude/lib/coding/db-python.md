# DB and repositories: Python

- `updated_at`: `auto_now` fires on `save()` only, and a `queryset.update()` such as `Foo.objects.filter(id=...).update(name='x')` is complete where the DDL has `ON UPDATE`; set it by hand only on a legacy table with neither `auto_now` nor `ON UPDATE`.
- Timezone anchoring: when the repository anchors with `arrow.replace(tzinfo='Asia/Seoul').floor('day')`, pass `astimezone(tz).date()`.
