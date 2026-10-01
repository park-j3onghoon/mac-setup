# Types: Python

- Collection default: `list[str] = []`.
- Constrained values get a constrained type: `list[EnumA | EnumB]`, with the same Enum Union on the DTO and repo; with `class X(str, Enum)`, set `use_enum_values=True` on the DTO.
- TYPE_CHECKING symbols stay in annotations; a runtime use raises `NameError` that mypy and the build miss and only pytest catches.
- dataclass vs dict: keep dict kwargs for an entity API in sentinel style (`None` = no change, `unset_*` = explicit unset); adopt a dataclass only together with an `UNSET` sentinel / separate-method refactor.
