# Model strategy and validation pathway

CardioLens currently ships **no clinical model**. It runs in research-demo mode and reports signal-quality and acoustic
measurements only. That is deliberate: no accuracy figure can be claimed until a model has been trained and evaluated on
appropriate labelled data, and no clinical claim until independent clinical validation.

## On the "94% accuracy" target

A 94% target is a reasonable *ambition*, but it is not something software can promise, and it is not reported anywhere in
the app because nothing has been measured yet. Before adopting it as a goal, it needs to be pinned down:

* **Accuracy of what?** Normal/abnormal, murmur present/absent, or a specific condition. Each task has very different difficulty.
* **On which population and device?** Published results on curated electronic-stethoscope datasets do not transfer to
  smartphone microphones or to different populations.
* **Accuracy is the wrong headline metric.** It depends on prevalence: at 10% prevalence a model that always says "normal"
  scores 90%. Screening targets should be set as **sensitivity and specificity with 95% confidence intervals** (plus PPV/NPV at
  the expected prevalence), measured on an **external** dataset. The Research Lab reports accuracy only as a secondary,
  prevalence-dependent figure.

A defensible target statement looks like: *"Sensitivity ≥ X% (lower 95% CI ≥ Y%) and specificity ≥ Z% for murmur detection on
an independent, prospectively collected cohort recorded with device D, with ≤ W% recordings rejected for quality."*

## Pathway

1. **Datasets** — Register candidates in the Research Lab (PhysioNet/CinC 2016 and CirCor DigiScope 2022 are pre-listed as
   *candidates*). Verify licence, permitted use, label definitions, devices and population on the source page before download.
2. **Baseline** — `python -m app.research.baseline --circor-dir <path> --out runs/v0` trains the transparent feature +
   logistic-regression baseline with a **patient-level** split (70/15/15), temperature scaling on validation only, and writes
   `test_predictions.csv` + `training_manifest.csv`. Its purpose is to be a reference point, not a product.
3. **Candidate models** — train stronger models (e.g. CNNs on log-mel spectrograms with segment aggregation) in a separate
   training repo; serve them behind the `inference/v1` contract. Record weights SHA-256 in the model registry.
4. **Internal held-out evaluation** — upload test predictions + training manifest. The lab refuses train/val rows, patients in
   multiple splits and patient-level leakage, and computes Wilson CIs, cluster-bootstrap AUC CIs, calibration (ECE, Brier,
   slope/intercept), subgroup, device and environment breakdowns, and failed-recording rates.
5. **External validation** — evaluate on an independent dataset never used for training or tuning (the API refuses a training
   dataset as "external"). Compare against the baseline.
6. **Calibration & thresholds** — choose operating thresholds on validation data for the intended screening use; report
   calibration on external data before displaying any score as a probability (`calibrated: true` in the card).
7. **Reproducibility** — pin data versions, code commit, seeds and weights hashes; every analysis row records pipeline and
   model versions.
8. **Independent clinical validation** — prospective study with predefined endpoints, ethics approval and a reference standard
   (e.g. echocardiography). Only after this, and an admin registering the evidence, can results be shown as `validated`.
9. **Regulatory** — assess medical-device classification (e.g. FDA SaMD, EU MDR, UK MDR) and QMS obligations before any
   clinical use or marketing claim.

## Signal-quality thresholds

`sqa-1.0` thresholds are engineering heuristics, checked against synthetic signals in the test suite. They should be tuned
against human quality labels (PhysioNet 2016 includes quality annotations) and the false-rejection rate should be reported per
device and subgroup, since over-rejection can bias who gets analysed. Rhythm irregularity is never a rejection criterion.
