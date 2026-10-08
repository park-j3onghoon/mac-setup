- PATCH DTO: HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, the named fields read with `dict(exclude_unset=True)` (a key sent as null stays in it), the pre-validator `_forbid_null` only on fields that cannot be empty, a null passed to the entity as `unset_{field}=True`, and cross-field checks (dates/budget) only over fields present in the partial; a check over absent fields re-validates a name-only edit against old values.
- Request DTO defaults: declare the required field with `Field(...)`:
  ```python
  # 지적 대상: UI 초기값을 BE에도 둔다
  loan_type: LoanType = Field(default=LoanType.STANDARD)
  reminder_channel: ReminderChannel = Field(default=ReminderChannel.EMAIL)
  # 맞는 형태: BE는 받기만 하고 FE가 정한다
  loan_type: LoanType = Field(...)
  reminder_channel: ReminderChannel = Field(...)
  ```
