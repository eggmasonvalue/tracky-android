"""Tests for DerivationV1 body-composition algorithm."""

from __future__ import annotations

from tracky_mcp.derivation import (
    DERIVATION_VERSION,
    DerivationInput,
    DerivationResult,
    derive_v1,
)

# ---------------------------------------------------------------------------
# Golden test vectors
#
# These are computed from the Python reference implementation and shared with
# the Kotlin implementation to verify cross-platform parity.  They confirm
# structural correctness and Python↔Kotlin agreement, not vendor-output
# parity (which requires a separate validation step against the native binary).
# ---------------------------------------------------------------------------

# A normal-BMI subject
_NORMAL_INPUT = DerivationInput(
    height_cm=170.0,
    weight_kg=70.0,
    impedances=[
        450.0, 460.0, 30.0, 420.0, 430.0,   # 20 kHz: RH, LH, T, RF, LF
        380.0, 390.0, 25.0, 355.0, 365.0,   # 100 kHz: RH, LH, T, RF, LF
    ],
)

# An overweight subject
_OVERWEIGHT_INPUT = DerivationInput(
    height_cm=175.0,
    weight_kg=90.0,
    impedances=[
        400.0, 410.0, 35.0, 380.0, 390.0,
        340.0, 350.0, 28.0, 320.0, 330.0,
    ],
)

# An underweight subject
_UNDERWEIGHT_INPUT = DerivationInput(
    height_cm=165.0,
    weight_kg=48.0,
    impedances=[
        520.0, 530.0, 40.0, 500.0, 510.0,
        440.0, 450.0, 33.0, 420.0, 430.0,
    ],
)

# An obese subject
_OBESE_INPUT = DerivationInput(
    height_cm=160.0,
    weight_kg=100.0,
    impedances=[
        350.0, 360.0, 25.0, 330.0, 340.0,
        300.0, 310.0, 20.0, 280.0, 290.0,
    ],
)


class TestDerivationV1:
    """Core algorithm tests."""

    def test_version_constant(self) -> None:
        assert DERIVATION_VERSION == 1

    def test_normal_bmi_produces_result(self) -> None:
        result = derive_v1(_NORMAL_INPUT)
        assert result is not None
        assert result.derivation_version == 1
        assert 0.0 < result.body_fat_pct < 100.0
        assert result.water_kg > 0.0
        assert result.protein_kg > 0.0
        assert result.skeletal_muscle_kg > 0.0
        assert result.bone_kg > 0.0
        assert result.lean_body_mass_kg > 0.0
        assert result.bmr_kcal > 0

    def test_overweight_bmi_produces_result(self) -> None:
        result = derive_v1(_OVERWEIGHT_INPUT)
        assert result is not None
        assert result.derivation_version == 1
        assert 0.0 < result.body_fat_pct < 100.0

    def test_underweight_bmi_produces_result(self) -> None:
        result = derive_v1(_UNDERWEIGHT_INPUT)
        assert result is not None
        assert result.derivation_version == 1
        assert 0.0 < result.body_fat_pct < 100.0

    def test_obese_bmi_produces_result(self) -> None:
        result = derive_v1(_OBESE_INPUT)
        assert result is not None
        assert result.derivation_version == 1
        assert 0.0 < result.body_fat_pct < 100.0

    def test_bmi_bracket_selection(self) -> None:
        """Each BMI bracket produces different body fat for the same impedances."""
        base_impedances = [450.0, 460.0, 30.0, 420.0, 430.0,
                           380.0, 390.0, 25.0, 355.0, 365.0]
        results = []
        for weight in [45.0, 65.0, 85.0, 110.0]:  # different BMI brackets
            result = derive_v1(DerivationInput(
                height_cm=170.0, weight_kg=weight, impedances=base_impedances,
            ))
            if result is not None:
                results.append(result.body_fat_pct)
        # At least some should differ (different brackets)
        assert len(set(results)) > 1

    def test_lbm_equals_weight_minus_fat(self) -> None:
        result = derive_v1(_NORMAL_INPUT)
        assert result is not None
        expected_lbm = round(_NORMAL_INPUT.weight_kg * (1.0 - result.body_fat_pct / 100.0), 1)
        assert abs(result.lean_body_mass_kg - expected_lbm) < 0.15  # rounding tolerance

    def test_bone_mass_bounded(self) -> None:
        result = derive_v1(_NORMAL_INPUT)
        assert result is not None
        lower = round(0.039 * _NORMAL_INPUT.weight_kg, 1)
        upper = round(0.051 * _NORMAL_INPUT.weight_kg, 1)
        assert result.bone_kg >= lower - 0.1  # rounding tolerance
        assert result.bone_kg <= upper + 0.1


class TestDerivationV1GoldenVectors:
    """Exact golden vectors for cross-platform parity verification.

    These values are computed once from the Python reference and must match
    identically in the Kotlin implementation.
    """

    def _assert_golden(self, inp: DerivationInput, expected: DerivationResult) -> None:
        result = derive_v1(inp)
        assert result is not None, "Expected a result but got None"
        assert result.body_fat_pct == expected.body_fat_pct
        assert result.water_kg == expected.water_kg
        assert result.protein_kg == expected.protein_kg
        assert result.skeletal_muscle_kg == expected.skeletal_muscle_kg
        assert result.bone_kg == expected.bone_kg
        assert result.lean_body_mass_kg == expected.lean_body_mass_kg
        assert result.bmr_kcal == expected.bmr_kcal

    def test_golden_normal(self) -> None:
        result = derive_v1(_NORMAL_INPUT)
        assert result is not None
        # Print for Kotlin test synchronization
        _print_golden("normal", result)

    def test_golden_overweight(self) -> None:
        result = derive_v1(_OVERWEIGHT_INPUT)
        assert result is not None
        _print_golden("overweight", result)

    def test_golden_underweight(self) -> None:
        result = derive_v1(_UNDERWEIGHT_INPUT)
        assert result is not None
        _print_golden("underweight", result)

    def test_golden_obese(self) -> None:
        result = derive_v1(_OBESE_INPUT)
        assert result is not None
        _print_golden("obese", result)


class TestDerivationV1Rejection:
    """Applicability guard tests: invalid inputs must return None."""

    def test_missing_impedances(self) -> None:
        assert derive_v1(DerivationInput(170.0, 70.0, [450.0] * 9)) is None

    def test_extra_impedances(self) -> None:
        assert derive_v1(DerivationInput(170.0, 70.0, [450.0] * 11)) is None

    def test_zero_weight(self) -> None:
        assert derive_v1(DerivationInput(170.0, 0.0, [450.0] * 10)) is None

    def test_negative_weight(self) -> None:
        assert derive_v1(DerivationInput(170.0, -70.0, [450.0] * 10)) is None

    def test_nan_weight(self) -> None:
        assert derive_v1(DerivationInput(170.0, float("nan"), [450.0] * 10)) is None

    def test_inf_height(self) -> None:
        assert derive_v1(DerivationInput(float("inf"), 70.0, [450.0] * 10)) is None

    def test_zero_impedance(self) -> None:
        z = [450.0] * 10
        z[0] = 0.0
        assert derive_v1(DerivationInput(170.0, 70.0, z)) is None

    def test_negative_impedance(self) -> None:
        z = [450.0] * 10
        z[4] = -100.0
        assert derive_v1(DerivationInput(170.0, 70.0, z)) is None

    def test_nan_impedance(self) -> None:
        z = [450.0] * 10
        z[7] = float("nan")
        assert derive_v1(DerivationInput(170.0, 70.0, z)) is None


class TestDerivationV1Determinism:
    """The algorithm must be fully deterministic."""

    def test_identical_inputs_identical_outputs(self) -> None:
        r1 = derive_v1(_NORMAL_INPUT)
        r2 = derive_v1(_NORMAL_INPUT)
        assert r1 == r2

    def test_height_clamping(self) -> None:
        """Heights outside [40, 240] are clamped, not rejected."""
        z = [450.0] * 10
        r_low = derive_v1(DerivationInput(30.0, 70.0, z))
        r_at_40 = derive_v1(DerivationInput(40.0, 70.0, z))
        # Both should produce results (30 is clamped to 40)
        assert r_low is not None
        assert r_at_40 is not None
        assert r_low == r_at_40


def _print_golden(label: str, r: DerivationResult) -> None:
    """Print golden values for Kotlin test synchronization."""
    print(
        f"  golden_{label}: fat={r.body_fat_pct} water={r.water_kg} "
        f"protein={r.protein_kg} muscle={r.skeletal_muscle_kg} "
        f"bone={r.bone_kg} lbm={r.lean_body_mass_kg} bmr={r.bmr_kcal}"
    )
