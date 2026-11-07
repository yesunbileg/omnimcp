# Four confirmed audit fixes — current status

The original WIP handoff has been implemented. See
[fixes and validation](2026-11-07-fix-validation.md) for current commits, test
results, independent review and runtime limits. The original findings remain in
[the independent audit](2026-11-07-review.md); saved reproductions are in
`2026-11-07-repros/`.

All changes remain on `wip/audit-fixes-20261107`; main is unchanged at `4b67a7c`.
The pointer change fixes the confirmed default-seat rounding defect. Named-seat
relative positioning and wire quantization remain separate unverified behavior.
The known Hyprland/Aquamarine compositor shutdown crash is tracked separately
from desktop acceptance. No universal desktop or multi-seat validation is claimed.
