#!/usr/bin/env bash
# SUPERSEDED 8 Nov 2026: the single-step swap started model load before the P-3 check could run.
# Use, in order: apply_overlay.sh, run_p3_check.sh, scale_up_deepep.sh (see RUNBOOK_DETAILED.md).
echo "swap_to_deepep.sh is superseded: run apply_overlay.sh, run_p3_check.sh, scale_up_deepep.sh in order" >&2
exit 2
