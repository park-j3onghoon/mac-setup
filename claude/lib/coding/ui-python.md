# UI: Python

- UI defaults are FE responsibility: declare the required field on the BE request DTO with `Field(...)`:
  ```python
  # 지적 대상: UI 초기값을 BE에도 둔다
  revenue_type: CampaignRevenueType = Field(default=CampaignRevenueType.CPC)
  target_sex_type: CampaignTargetSexType = Field(default=CampaignTargetSexType.ALL)
  # 맞는 형태: BE는 받기만 하고 FE가 정한다
  revenue_type: CampaignRevenueType = Field(...)
  target_sex_type: CampaignTargetSexType = Field(...)
  ```
