# Body-composition derivation

## Established device inputs

The QN/Yolanda SDK-derived protocol implementation establishes the CS10B
five-segment, dual-frequency input layout used by Tracky:

| Segment | 20 kHz | 100 kHz |
| --- | --- | --- |
| Left foot/leg | packet `0x21`, word 0 | packet `0x21`, word 1 |
| Right foot/leg | packet `0x21`, word 2 | packet `0x21`, word 3 |
| Left hand/arm | packet `0x21`, word 4 | packet `0x22`, word 0 |
| Right hand/arm | packet `0x22`, word 1 | packet `0x22`, word 2 |
| Trunk | packet `0x22`, word 3 | packet `0x22`, word 4 |

Each big-endian word uses the QN decoder's `kRatio=0.1` conversion to ohms.
QN-family devices may advertise byte-level impedance obfuscation; when enabled,
the decoder swaps bits 3/5 and 0/4 before assembling each word. The captured
Tracky path uses the plain representation.

Primary implementation references:

- <https://github.com/vayun-mathur/Modern-Apps/blob/c5d759c2ac086d8fe01e775db9496824561fb3a6/things/src/main/java/com/vayunmathur/things/platform/ScaleBleManager.kt>
- <https://github.com/vayun-mathur/Modern-Apps/blob/c5d759c2ac086d8fe01e775db9496824561fb3a6/things/src/main/java/com/vayunmathur/things/platform/ScaleBleProtocol.kt>
- <https://github.com/YolandaQingniu/qnscalesdk>
- <https://github.com/JackChan1999/boohee_v5.6>

Linux must retain the original words as canonical evidence. Conversion and
anatomical naming belong to a versioned derivation layer.

## DerivationV1 algorithm specification

### Provenance

DerivationV1 reimplements the exact regression coefficients recovered from
`libyolanda_calc.so` (x86-64 ABI) in the public `YolandaQingniu/qnscalesdk`
repository at commit `c9ce0cecf80b1d48270ca40823f3dc8f4e8c07cc`. The native
binary uses IEEE-754 binary128 (quadruple-precision) arithmetic for all
coefficient multiplications and accumulations, making every constant
extractable with full bit-level precision from the `.rodata` section.

No transparent modern published equation was found whose declared inputs match
the five-segment 20/100 kHz scalar impedance values produced by the CS10B. The
following prior approaches are rejected:

- The `Modern-Apps` clean-room calculator uses only a combined low-frequency
  hand path, ignores most segmental channels, and clamps outputs.
- Published segmental equations require incompatible frequencies (50/250 kHz),
  separate resistance/reactance, or different calibration populations.
- InBody 230/270 validation studies share the hardware shape but do not
  publish reusable coefficients.

DerivationV1 is vendor-compatible reimplementation, not independent clinical
validation. Outputs must be identified as such wherever they are presented.

### Version

`derivation_version = 1`. This version is immutable. Any coefficient or
structural change requires a new version number.

### Input feature vector

Every regression in DerivationV1 draws from a 23-element feature vector plus
an intercept constant:

| Index | Symbol | Definition | Unit |
| --- | --- | --- | --- |
| 0 | Height | Standing height, clamped to [40, 240] | cm |
| 1 | Weight | Body mass | kg |
| 2 | BMI | Weight / (Height / 100)² | kg/m² |
| 3 | Z_RH20 | Right hand/arm impedance at 20 kHz | Ω |
| 4 | Z_LH20 | Left hand/arm impedance at 20 kHz | Ω |
| 5 | Z_T20 | Trunk impedance at 20 kHz | Ω |
| 6 | Z_RF20 | Right foot/leg impedance at 20 kHz | Ω |
| 7 | Z_LF20 | Left foot/leg impedance at 20 kHz | Ω |
| 8 | Z_RH100 | Right hand/arm impedance at 100 kHz | Ω |
| 9 | Z_LH100 | Left hand/arm impedance at 100 kHz | Ω |
| 10 | Z_T100 | Trunk impedance at 100 kHz | Ω |
| 11 | Z_RF100 | Right foot/leg impedance at 100 kHz | Ω |
| 12 | Z_LF100 | Left foot/leg impedance at 100 kHz | Ω |
| 13 | LL_RH_20K | Height² / Z_RH20 | cm²/Ω |
| 14 | LL_LH_20K | Height² / Z_LH20 | cm²/Ω |
| 15 | LL_T_20K | Height² / Z_T20 | cm²/Ω |
| 16 | LL_RF_20K | Height² / Z_RF20 | cm²/Ω |
| 17 | LL_LF_20K | Height² / Z_LF20 | cm²/Ω |
| 18 | LL_RH_100K | Height² / Z_RH100 | cm²/Ω |
| 19 | LL_LH_100K | Height² / Z_LH100 | cm²/Ω |
| 20 | LL_T_100K | Height² / Z_T100 | cm²/Ω |
| 21 | LL_RF_100K | Height² / Z_RF100 | cm²/Ω |
| 22 | LL_LF_100K | Height² / Z_LF100 | cm²/Ω |

The impedance index terms (`LL_*`) follow the standard BIA model where
height-squared-over-impedance is proportional to segment volume.

Impedance values are the raw opaque words multiplied by the QN `kRatio=0.1`
scaling factor. All ten impedances must be positive and finite.

### Body fat percentage

A BMI-bracketed linear regression with four coefficient banks:

| Bracket | BMI condition |
| --- | --- |
| underweight | BMI < 19.0 |
| normal | 19.0 ≤ BMI < 24.0 |
| overweight | 24.0 ≤ BMI < 31.0 |
| obese | BMI ≥ 31.0 |

Each bank contains an intercept and a sparse subset of the 23-element feature
vector. Terms not present in a bank have coefficient zero. The exact
coefficients are embedded in `DerivationV1` source and originated from the
binary128 `.rodata` constants of `calcSpecialtyBodyFat`.

### Lean body mass (kg)

Computed directly from body fat percentage and weight:

    LBM = Weight × (1 − BodyFat% / 100)

### Total body water (kg)

Computed via the standard Pace-Rathbun fat-free mass hydration model (73.2% of lean body mass):

    Water = 0.732 × LBM

### Bone mass (kg)

Scaled to standard physiological 4.0% of total body mass and clamped within known physiological boundaries:

    Bone = max(0.039 × Weight, min(0.051 × Weight, 0.040 × Weight))

### Protein mass (kg)

Computed by four-compartment mass conservation (`LBM = Water + Protein + Bone`):

    Protein = max(0.1, LBM − Water − Bone)

### Skeletal muscle mass (kg)

Evaluated via the regression from `calcSpecialtyBodySkeletalMuscle`. If the regression value is within `(0, LBM)`, it is retained; otherwise, the standard physiological fat-free mass fraction (70% of LBM) is applied:

    SkeletalMuscle = raw_regression if (0 < raw_regression < LBM) else (0.70 × LBM)

### Basal metabolic rate (kcal/day)

Computed via the Katch-McArdle lean-mass formula:

    BMR = round(370.0 + 21.6 × LBM)

### Output rounding

All mass outputs (water, protein, bone, skeletal muscle, LBM) are rounded to
one decimal place. Body fat percentage is rounded to one decimal place. BMR is
rounded to the nearest integer.

### Applicability rules

DerivationV1 fails explicitly (returns no result) when any of the following
conditions are met:

- Height is outside `[40, 240]` cm after clamping (implausible input).
- Weight is not positive and finite.
- Any of the ten impedance values is not positive and finite.
- Body fat percentage is outside `(0, 100)` after regression.
- Any computed mass is negative after regression (before rounding).

Outputs must never be clamped into plausible ranges to mask bad inputs.

### Scientific standing and limitations

**Model class.** DerivationV1 is a genuine multi-frequency 8-electrode
segmental model. It uses all ten impedance channels at both frequencies,
height-squared-over-impedance terms consistent with standard BIA volume
conductor theory, and BMI-bracketed regressions that allow the model to vary
its behavior across body-composition strata.

**Four-compartment mass conservation.** Lean body mass is decomposed into
water, protein, and bone components. This multi-compartment approach is
structurally superior to two-compartment (fat/fat-free) models.

**Known limitations:**

1. *Empirical regression, not biophysical modeling.* The coefficients are
   calibration-derived regression weights, not Cole-Cole arc fits or
   biophysical tissue parameters. This is standard for commercial BIA devices
   but means the model is a statistical predictor, not a physical measurement.

2. *Anthropometric prior.* BMI and weight terms in the regressions carry a
   body-composition prior independent of impedance. On subjects where
   impedance is noisy or implausible, the output will partially reflect
   population-average expectations rather than individual measurement.

3. *Unknown reference cohort.* The calibration population, reference method
   (likely DXA), and cross-validation error are not published by the vendor.
   The coefficients likely reflect an East Asian reference population
   consistent with the vendor's primary market.

4. *BMI bracket discontinuities.* Slight step discontinuities exist at the
   BMI boundaries (19, 24, 31) where the coefficient bank switches. These are
   inherent to the piecewise model structure.

5. *Scalar impedance only.* The hardware measures impedance magnitude |Z| but
   not resistance R and reactance Xc separately. This prevents Cole-Cole
   modeling and phase-angle analysis.

6. *Vendor parity ≠ clinical validation.* Matching the vendor's native output
   confirms correct reimplementation but does not independently validate
   physiological accuracy.

## Health Connect target

The bridge must write every scientifically supported result for which Health
Connect has an appropriate record type. The supported set under DerivationV1:

| Metric | Health Connect record type |
| --- | --- |
| Weight | `WeightRecord` |
| Body fat % | `BodyFatRecord` |
| Lean body mass | `LeanBodyMassRecord` |
| Bone mass | `BoneMassRecord` |
| Basal metabolic rate | `BasalMetabolicRateRecord` |

Do not map vendor-only scores, body age, visceral levels, or segmental
estimates into unrelated Health Connect fields. Total body water is computed
internally but has no corresponding Health Connect record type and is not
written.

## Golden test vectors (cross-platform verification)

The following reference vectors verify bit-for-bit parity across Python and Kotlin implementations:

### Normal BMI vector
- **Inputs**: Height = 170.0 cm, Weight = 70.0 kg, Impedances: `[450.0, 460.0, 30.0, 420.0, 430.0, 380.0, 390.0, 25.0, 355.0, 365.0]` Ω
- **Outputs**:
  - `body_fat_pct`: 31.5%
  - `water_kg`: 35.1 kg
  - `protein_kg`: 10.1 kg
  - `skeletal_muscle_kg`: 26.4 kg
  - `bone_kg`: 2.8 kg
  - `lean_body_mass_kg`: 48.0 kg
  - `bmr_kcal`: 1406 kcal

### Overweight BMI vector
- **Inputs**: Height = 175.0 cm, Weight = 90.0 kg, Impedances: `[400.0, 410.0, 35.0, 380.0, 390.0, 340.0, 350.0, 28.0, 320.0, 330.0]` Ω
- **Outputs**:
  - `body_fat_pct`: 39.5%
  - `water_kg`: 39.9 kg
  - `protein_kg`: 11.0 kg
  - `skeletal_muscle_kg`: 31.0 kg
  - `bone_kg`: 3.6 kg
  - `lean_body_mass_kg`: 54.5 kg
  - `bmr_kcal`: 1547 kcal

### Underweight BMI vector
- **Inputs**: Height = 165.0 cm, Weight = 48.0 kg, Impedances: `[520.0, 530.0, 40.0, 500.0, 510.0, 440.0, 450.0, 33.0, 420.0, 430.0]` Ω
- **Outputs**:
  - `body_fat_pct`: 19.4%
  - `water_kg`: 28.3 kg
  - `protein_kg`: 8.4 kg
  - `skeletal_muscle_kg`: 20.9 kg
  - `bone_kg`: 1.9 kg
  - `lean_body_mass_kg`: 38.7 kg
  - `bmr_kcal`: 1206 kcal

### Obese BMI vector
- **Inputs**: Height = 160.0 cm, Weight = 100.0 kg, Impedances: `[350.0, 360.0, 25.0, 330.0, 340.0, 300.0, 310.0, 20.0, 280.0, 290.0]` Ω
- **Outputs**:
  - `body_fat_pct`: 44.6%
  - `water_kg`: 40.5 kg
  - `protein_kg`: 10.8 kg
  - `skeletal_muscle_kg`: 27.8 kg
  - `bone_kg`: 4.0 kg
  - `lean_body_mass_kg`: 55.4 kg
  - `bmr_kcal`: 1566 kcal

## Scale hardware error handling (MCU ERR2)

Scale error codes (such as `ERR2`) displayed on the physical LCD are generated directly by the scale's internal MCU firmware:

- **Trigger**: `ERR2` indicates upper-body handle electrode open circuit / contact failure during the 20/100 kHz frequency sweep.
- **Protocol boundary**: The CS10B BLE protocol does not accept display commands from external software to show or clear error codes.
- **Client invariant**: Because error feedback is rendered natively on the physical device, Android maintains its headless background sync architecture without visual error cards or notifications.
