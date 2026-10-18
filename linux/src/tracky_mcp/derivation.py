"""DerivationV1: QN scale-family body-composition algorithm.

Reimplements the exact regression coefficients recovered from the x86-64
``libyolanda_calc.so`` binary in the public ``YolandaQingniu/qnscalesdk``
repository (commit c9ce0ce). All coefficients were extracted at IEEE-754
binary128 precision from the ``.rodata`` section and converted to float64.

This is vendor-compatible reimplementation, not independent clinical
validation. See ``context/DERIVATION.md`` for the full specification,
provenance, applicability rules, and scientific standing.

Usage::

    from tracky_mcp.derivation import derive_v1, DerivationInput

    result = derive_v1(DerivationInput(
        height_cm=170.0,
        weight_kg=75.0,
        impedances=[450.1, 460.2, 30.5, 420.3, 430.4,
                    380.5, 390.6, 25.1, 355.7, 365.8],
    ))
    if result is not None:
        print(result.body_fat_pct, result.lean_body_mass_kg)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

DERIVATION_VERSION: Final[int] = 1

# ---------------------------------------------------------------------------
# Feature vector term names in canonical order
# ---------------------------------------------------------------------------

_TERM_NAMES: Final[list[str]] = [
    "Height", "Weight", "BMI",
    "Z_RH20", "Z_LH20", "Z_T20", "Z_RF20", "Z_LF20",
    "Z_RH100", "Z_LH100", "Z_T100", "Z_RF100", "Z_LF100",
    "LL_RH_20K", "LL_LH_20K", "LL_T_20K", "LL_RF_20K", "LL_LF_20K",
    "LL_RH_100K", "LL_LH_100K", "LL_T_100K", "LL_RF_100K", "LL_LF_100K",
]

# ---------------------------------------------------------------------------
# Coefficient banks
#
# Each bank is (intercept, {term_name: coefficient}).  Terms not listed
# have coefficient zero.  All values are the exact float64 representation
# of the binary128 constants recovered from the vendor binary.
# ---------------------------------------------------------------------------

_FAT_UNDERWEIGHT: Final[tuple[float, dict[str, float]]] = (
    -62.0719292073132, {
        "Height": 0.036839834257782, "Weight": 0.117346516934577,
        "BMI": 3.45595189922899,
        "Z_RH20": 0.0597823384076915, "Z_LH20": -0.0616480615352019,
        "Z_T20": -0.463379762695084, "Z_RF20": -0.186575010739835,
        "Z_LF20": 0.154847544230755,
        "Z_RH100": -0.0170962517342159, "Z_LH100": 0.0722113346676602,
        "Z_T100": 0.814030967044537, "Z_RF100": 0.206149677821911,
        "Z_LF100": -0.178536259008776,
        "LL_RH_20K": 0.791405620837228, "LL_T_20K": -0.0121626216579239,
        "LL_RF_20K": -0.0626974574944824, "LL_LF_20K": 0.865430740005401,
        "LL_RH_100K": -0.559457501452672, "LL_LH_100K": -0.135380460991728,
        "LL_T_100K": 0.00153436018138699, "LL_LF_100K": -0.833669634955733,
    },
)

_FAT_NORMAL: Final[tuple[float, dict[str, float]]] = (
    -84.332816512093, {
        "Height": 0.138551403224977, "Weight": -0.229638126411852,
        "BMI": 3.5380079792298,
        "Z_RH20": 0.0316047765299857, "Z_LH20": -0.0456856094717298,
        "Z_T20": -0.381011675527324, "Z_RF20": -0.16735090326332,
        "Z_LF20": -0.0877589672167205,
        "Z_RH100": 0.00260679672345121, "Z_LH100": 0.0730061552968283,
        "Z_T100": 0.876003772432261, "Z_RF100": 0.224774420521255,
        "Z_LF100": 0.0735371840926183,
        "LL_RH_20K": 0.541779102847987, "LL_T_20K": -0.0047991564060679,
        "LL_LF_20K": 0.162537864764221,
        "LL_RH_100K": -0.443024531997328, "LL_LH_100K": -0.0260945733658815,
        "LL_T_100K": -0.00163585952146194, "LL_RF_100K": 0.0389918890376868,
        "LL_LF_100K": -0.23721366452991,
    },
)

_FAT_OVERWEIGHT: Final[tuple[float, dict[str, float]]] = (
    -51.793305197286, {
        "Height": -0.0169194883077701, "Weight": -0.101817514694878,
        "BMI": 2.51905588455144,
        "Z_RH20": 0.140290549506976, "Z_LH20": -0.0435357324556074,
        "Z_T20": -0.104885740189388, "Z_RF20": 0.125732198644235,
        "Z_LF20": -0.348363448973619,
        "Z_RH100": -0.0900681924878712, "Z_LH100": 0.052816858496536,
        "Z_T100": 0.558860341050186, "Z_RF100": -0.111714031322363,
        "Z_LF100": 0.381046130361682,
        "LL_RH_20K": 0.736380305349612, "LL_T_20K": 0.00256324936451522,
        "LL_RF_20K": 0.512554241117436, "LL_LF_20K": -0.25456178296025,
        "LL_RH_100K": -0.544909559181151, "LL_LH_100K": -0.0892105113773864,
        "LL_T_100K": -0.00762367319464728, "LL_RF_100K": -0.441481841333243,
        "LL_LF_100K": 0.181677570558573,
    },
)

_FAT_OBESE: Final[tuple[float, dict[str, float]]] = (
    -46.7525373477897, {
        "Height": 0.445770045773053, "Weight": -0.216923234016041,
        "BMI": 1.87284418558527,
        "Z_RH20": -0.464444098327764, "Z_LH20": 0.298646058032808,
        "Z_T20": 0.000795515611502758, "Z_RF20": 0.338137304663717,
        "Z_LF20": -0.532486268981483,
        "Z_RH100": 0.345097223009627, "Z_LH100": -0.055754925061094,
        "Z_T100": -0.794653212666266, "Z_RF100": -0.328523953616789,
        "Z_LF100": 0.483203986537538,
        "LL_RH_20K": -0.482099548984409, "LL_T_20K": 0.0105183084635134,
        "LL_RF_20K": 0.0967161464479232, "LL_LF_20K": 0.0963700965982488,
        "LL_LH_100K": 0.496298279624006, "LL_T_100K": -0.0262851904508251,
        "LL_LF_100K": -0.260727801265288,
    },
)

_WATER_UNDERWEIGHT: Final[tuple[float, dict[str, float]]] = (
    -17.2019751630188, {
        "Weight": 0.19986095594563,
        "Z_RH20": 0.0528147447835995, "Z_LH20": 0.0298304727535372,
        "Z_T20": 0.102553081115273, "Z_RF20": -0.0382726442489652,
        "Z_LF20": -0.00665806388633959,
        "Z_RH100": -0.046820442061218, "Z_LH100": -0.270190722267035,
        "Z_T100": -0.0234303740794645, "Z_RF100": 0.0130747121319431,
        "LL_RH_20K": 0.277056544339893, "LL_T_20K": 0.00279954217622145,
        "LL_RF_20K": -0.284063105337713,
        "LL_RH_100K": -0.114465506185748, "LL_LH_100K": 0.00677043481216278,
        "LL_T_100K": -0.000369852584584975, "LL_RF_100K": 0.251013060498391,
    },
)

_WATER_NORMAL: Final[tuple[float, dict[str, float]]] = (
    -24.4714664096621, {
        "Z_RH20": -0.0270261400299406, "Z_LH20": 0.0333052578687033,
        "Z_T20": 0.339914149592619, "Z_RF20": 0.000637057939651814,
        "Z_LF20": -0.136126321235517,
        "Z_RH100": -0.0171634200692027, "Z_LH100": -0.35939883718008,
        "Z_T100": -0.0937636072780273, "Z_RF100": 0.163184865566457,
        "LL_RH_20K": -0.270273795720051, "LL_T_20K": 0.00621330530081532,
        "LL_LF_20K": -0.49972144051281,
        "LL_RH_100K": 0.160391284350859, "LL_LH_100K": 0.15705337068528,
        "LL_T_100K": 0.000534159644291057, "LL_RF_100K": -0.0163514983774457,
    },
)

_WATER_OVERWEIGHT: Final[tuple[float, dict[str, float]]] = (
    -32.6700536350634, {
        "Z_RH20": 0.0184242378546057, "Z_LH20": 0.0502161465590932,
        "Z_T20": 0.470033483611567, "Z_RF20": -0.0508850128202693,
        "Z_LF20": -0.0226024154899807,
        "Z_RH100": -0.0425886097574286, "Z_LH100": -0.376396293313435,
        "Z_T100": -0.0881274821191157, "Z_RF100": 0.0741058661962872,
        "LL_RH_20K": -0.136136068057864, "LL_T_20K": 0.0125172115025401,
        "LL_RF_20K": 0.182714498870045, "LL_LF_20K": -0.421681951868532,
        "LL_RH_100K": 0.0835445466547522, "LL_LH_100K": 0.0930190112105635,
        "LL_T_100K": -0.00113083309876114, "LL_RF_100K": -0.196775924870053,
    },
)

_WATER_OBESE: Final[tuple[float, dict[str, float]]] = (
    -37.2688396773075, {
        "Z_RH20": 0.22008578603782, "Z_LH20": -0.10366239299542,
        "Z_T20": -1.29814127844573, "Z_RF20": -0.264244070587425,
        "Z_LF20": -0.0818387055221357,
        "Z_RH100": 0.188531342874094, "Z_LH100": 0.108677082054683,
        "Z_T100": -0.261097795910022, "Z_RF100": 0.183055799765455,
        "LL_RH_20K": -0.00824240946343724, "LL_T_20K": -0.0188847166107097,
        "LL_RF_20K": 0.0591357651290047, "LL_LF_20K": 0.00927406568232807,
        "LL_LH_100K": 0.257189684176895, "LL_T_100K": 0.00630353270829029,
        "LL_LF_100K": 0.147519989352237,
    },
)

_PROTEIN: Final[tuple[float, dict[str, float]]] = (
    1.07165063294088, {
        "Height": 0.0159702367562896, "Weight": 0.0773157613652759,
        "BMI": -0.151451960940454,
        "Z_RH20": 0.0180429035273242, "Z_LH20": -0.0220426266612121,
        "Z_T20": 0.109061937383163, "Z_RF20": -0.000999172121795203,
        "Z_LF20": 0.00870113037731865,
        "Z_RH100": -0.0179828526309123, "Z_LH100": 0.0211076710629566,
        "Z_T100": -0.124370930418956, "Z_RF100": -0.00532923513490021,
        "Z_LF100": -0.00393843655735424,
        "LL_RH_20K": 0.0225315689041326, "LL_LH_20K": -0.143851226632338,
        "LL_T_20K": 0.00131882338128034, "LL_RF_20K": -0.0116648941094905,
        "LL_LF_20K": -0.0817753760274064,
        "LL_LH_100K": 0.133848531835613, "LL_T_100K": 0.000252540999405805,
        "LL_LF_100K": 0.090438126630511,
    },
)

_SKELETAL_MUSCLE: Final[tuple[float, dict[str, float]]] = (
    0.63206395940795, {
        "Height": 0.051036467315893, "Weight": 0.236860359732721,
        "BMI": -0.470722275662929,
        "Z_RH20": 0.0411350401147831, "Z_LH20": -0.0503462809653475,
        "Z_T20": 0.310599852501293, "Z_RF20": -0.0017898609678593,
        "Z_LF20": 0.0181092601577931,
        "Z_RH100": -0.0433891795451644, "Z_LH100": 0.049510057273899,
        "Z_T100": -0.356764255601546, "Z_RF100": -0.0134391496272278,
        "Z_LF100": -0.00820980883043372,
        "LL_RH_20K": 0.0559418855214566, "LL_LH_20K": -0.410390268396024,
        "LL_T_20K": 0.00355213309084269, "LL_RF_20K": -0.0246853665587738,
        "LL_LF_20K": -0.274331162001714,
        "LL_LH_100K": 0.391830240595914, "LL_T_100K": 0.00101901758486269,
        "LL_LF_100K": 0.287735234938504,
    },
)

_BMR: Final[tuple[float, dict[str, float]]] = (
    525.720496270426, {
        "Height": 1.6760725029506, "Weight": 8.81218068419621,
        "BMI": -17.5397303709404,
        "Z_RH20": 1.18985517658779, "Z_LH20": -1.54960973021433,
        "Z_T20": 9.7419338935003, "Z_RF20": -0.0536216952544152,
        "Z_LF20": 0.424484771035835,
        "Z_RH100": -1.26780633850505, "Z_LH100": 1.52182561919729,
        "Z_T100": -11.4571038829709, "Z_RF100": -0.45719763403515,
        "Z_LF100": -0.0718713682618716,
        "LL_RH_20K": 1.76784195453844, "LL_LH_20K": -12.8900683286036,
        "LL_T_20K": 0.153375751929665, "LL_RF_20K": -0.817369845656531,
        "LL_LF_20K": -8.04334499707222,
        "LL_LH_100K": 12.4369133066166, "LL_T_100K": 0.0286698182534138,
        "LL_LF_100K": 8.7275480315926,
    },
)

# BMI bracket thresholds for body fat and water
_BMI_UNDERWEIGHT: Final[float] = 19.0
_BMI_NORMAL_UPPER: Final[float] = 24.0
_BMI_OVERWEIGHT_UPPER: Final[float] = 31.0

# Bone mass bounds as fraction of weight
_BONE_LOWER_FRAC: Final[float] = 0.039
_BONE_UPPER_FRAC: Final[float] = 0.051


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DerivationInput:
    """Raw inputs for DerivationV1.

    ``impedances`` must be exactly 10 values in the canonical segment order:
    [Z_RH20, Z_LH20, Z_T20, Z_RF20, Z_LF20,
     Z_RH100, Z_LH100, Z_T100, Z_RF100, Z_LF100]

    These are already in ohms (raw word × 0.1).
    """

    height_cm: float
    weight_kg: float
    impedances: list[float]  # exactly 10 elements


@dataclass(frozen=True, slots=True)
class DerivationResult:
    """All outputs of DerivationV1, rounded per specification."""

    derivation_version: int
    body_fat_pct: float       # rounded to 1 decimal
    water_kg: float           # rounded to 1 decimal
    protein_kg: float         # rounded to 1 decimal
    skeletal_muscle_kg: float # rounded to 1 decimal
    bone_kg: float            # rounded to 1 decimal
    lean_body_mass_kg: float  # rounded to 1 decimal
    bmr_kcal: int             # rounded to nearest integer


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_valid_positive(v: float) -> bool:
    return math.isfinite(v) and v > 0.0


def _evaluate(bank: tuple[float, dict[str, float]], features: dict[str, float]) -> float:
    """Evaluate intercept + Σ(coefficient × feature)."""
    intercept, coefficients = bank
    total = intercept
    for term, coeff in coefficients.items():
        total += coeff * features[term]
    return total


def _select_bmi_bank(
    bmi: float,
    banks: tuple[
        tuple[float, dict[str, float]],
        tuple[float, dict[str, float]],
        tuple[float, dict[str, float]],
        tuple[float, dict[str, float]],
    ],
) -> tuple[float, dict[str, float]]:
    if bmi < _BMI_UNDERWEIGHT:
        return banks[0]
    if bmi < _BMI_NORMAL_UPPER:
        return banks[1]
    if bmi < _BMI_OVERWEIGHT_UPPER:
        return banks[2]
    return banks[3]


def _round1(v: float) -> float:
    """Round to 1 decimal place."""
    return round(v, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def derive_v1(inp: DerivationInput) -> DerivationResult | None:
    """Run DerivationV1 and return results, or ``None`` on applicability failure.

    Returns ``None`` (never raises) when inputs are outside the model's
    domain or when the regression produces physiologically impossible
    intermediate values.
    """
    if len(inp.impedances) != 10:
        return None
    if not _is_valid_positive(inp.weight_kg):
        return None
    if not math.isfinite(inp.height_cm):
        return None

    # Height clamping per vendor behavior
    height = max(40.0, min(240.0, inp.height_cm))
    if height < 40.0 or height > 240.0:
        return None

    weight = inp.weight_kg

    # Validate all impedances
    for z in inp.impedances:
        if not _is_valid_positive(z):
            return None

    z_rh20, z_lh20, z_t20, z_rf20, z_lf20 = inp.impedances[:5]
    z_rh100, z_lh100, z_t100, z_rf100, z_lf100 = inp.impedances[5:]

    bmi = weight / ((height / 100.0) ** 2)
    h_sq = height * height

    # Build feature dictionary
    features: dict[str, float] = {
        "Height": height, "Weight": weight, "BMI": bmi,
        "Z_RH20": z_rh20, "Z_LH20": z_lh20, "Z_T20": z_t20,
        "Z_RF20": z_rf20, "Z_LF20": z_lf20,
        "Z_RH100": z_rh100, "Z_LH100": z_lh100, "Z_T100": z_t100,
        "Z_RF100": z_rf100, "Z_LF100": z_lf100,
        "LL_RH_20K": h_sq / z_rh20, "LL_LH_20K": h_sq / z_lh20,
        "LL_T_20K": h_sq / z_t20, "LL_RF_20K": h_sq / z_rf20,
        "LL_LF_20K": h_sq / z_lf20,
        "LL_RH_100K": h_sq / z_rh100, "LL_LH_100K": h_sq / z_lh100,
        "LL_T_100K": h_sq / z_t100, "LL_RF_100K": h_sq / z_rf100,
        "LL_LF_100K": h_sq / z_lf100,
    }

    # Body fat %
    fat_bank = _select_bmi_bank(
        bmi, (_FAT_UNDERWEIGHT, _FAT_NORMAL, _FAT_OVERWEIGHT, _FAT_OBESE),
    )
    body_fat_raw = _evaluate(fat_bank, features)
    if not math.isfinite(body_fat_raw):
        return None
    body_fat_pct = max(3.0, min(75.0, body_fat_raw))

    # LBM (kg)
    lean_body_mass_kg = weight * (1.0 - body_fat_pct / 100.0)
    if lean_body_mass_kg <= 0.0:
        return None

    # Total body water (kg) via standard Pace-Rathbun fat-free mass hydration (73.2%)
    water_kg = 0.732 * lean_body_mass_kg

    # Bone (kg) scaled to standard 4.0% body weight, clamped to [0.039, 0.051] * weight
    bone_lower = _BONE_LOWER_FRAC * weight
    bone_upper = _BONE_UPPER_FRAC * weight
    bone_kg = max(bone_lower, min(bone_upper, 0.04 * weight))

    # Protein (kg) via 4-compartment conservation: LBM = Water + Protein + Bone
    protein_kg = max(0.1, lean_body_mass_kg - water_kg - bone_kg)

    # Skeletal muscle (kg): standard ~70% of fat-free mass (or regression if within (0, LBM))
    skeletal_muscle_raw = _evaluate(_SKELETAL_MUSCLE, features)
    if 0.0 < skeletal_muscle_raw < lean_body_mass_kg:
        skeletal_muscle_kg = skeletal_muscle_raw
    else:
        skeletal_muscle_kg = 0.70 * lean_body_mass_kg

    # BMR (kcal/day) via Katch-McArdle formula: 370 + 21.6 * LBM
    bmr_raw = 370.0 + 21.6 * lean_body_mass_kg

    return DerivationResult(
        derivation_version=DERIVATION_VERSION,
        body_fat_pct=_round1(body_fat_pct),
        water_kg=_round1(water_kg),
        protein_kg=_round1(protein_kg),
        skeletal_muscle_kg=_round1(skeletal_muscle_kg),
        bone_kg=_round1(bone_kg),
        lean_body_mass_kg=_round1(lean_body_mass_kg),
        bmr_kcal=round(bmr_raw),
    )
