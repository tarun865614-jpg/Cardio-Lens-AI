import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..inference.base import VALIDATION_STATUSES
from ..models import Dataset, EvaluationRun, ModelVersion, User
from ..research.evaluation import EvaluationError, evaluate
from ..security import RESEARCH, require_roles

router = APIRouter(prefix="/research", tags=["research"])


class DatasetIn(BaseModel):
    name: str = Field(max_length=200)
    source_url: str | None = None
    license: str
    permitted_use: str
    provenance: str
    label_definitions: str
    recording_devices: str = ""
    population: str = ""
    limitations: str = ""
    n_patients: int | None = None
    n_recordings: int | None = None


def dataset_out(d: Dataset) -> dict:
    return {c: getattr(d, c) for c in ("id", "name", "source_url", "license", "permitted_use", "provenance", "label_definitions",
                                        "recording_devices", "population", "limitations", "n_patients", "n_recordings",
                                        "is_downloaded", "created_at")}


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    return [dataset_out(d) for d in db.scalars(select(Dataset).order_by(Dataset.name))]


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    if db.scalar(select(Dataset).where(Dataset.name == body.name)):
        raise HTTPException(409, "Dataset already registered")
    d = Dataset(**body.model_dump())
    db.add(d)
    db.flush()
    audit.record(db, user, "dataset.register", "dataset", d.id, {"name": d.name, "license": d.license})
    db.commit()
    return dataset_out(d)


class ModelIn(BaseModel):
    name: str = Field(max_length=100)
    version: str = Field(max_length=50)
    intended_use: str
    categories: list[dict]
    validation_status: str = "research_only"
    validation_evidence: str | None = None
    input_spec: dict = {}
    training_datasets: list[str] = []
    weights_sha256: str | None = None


def model_out(m: ModelVersion) -> dict:
    return {c: getattr(m, c) for c in ("id", "name", "version", "intended_use", "categories", "validation_status",
                                        "validation_evidence", "input_spec", "training_datasets", "weights_sha256", "is_active", "created_at")}


@router.get("/models")
def list_models(db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    return [model_out(m) for m in db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc()))]


@router.post("/models", status_code=201)
def register_model(body: ModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    if body.validation_status not in VALIDATION_STATUSES:
        raise HTTPException(422, f"validation_status must be one of {sorted(VALIDATION_STATUSES)}")
    if body.validation_status == "externally_validated" and not (body.validation_evidence or "").strip():
        raise HTTPException(422, "Externally validated models must cite validation evidence")
    if body.validation_status == "externally_validated" and user.role != "admin":
        raise HTTPException(403, "Only administrators can register a model as externally validated")
    if db.scalar(select(ModelVersion).where(ModelVersion.name == body.name, ModelVersion.version == body.version)):
        raise HTTPException(409, "Model version already registered (versions are immutable)")
    m = ModelVersion(**body.model_dump())
    db.add(m)
    db.flush()
    audit.record(db, user, "model.register", "model_version", m.id, {"name": m.name, "version": m.version, "validation_status": m.validation_status})
    db.commit()
    return model_out(m)


def run_out(r: EvaluationRun, full: bool = False) -> dict:
    o = r.metrics.get("overall", {})
    out = {"id": r.id, "created_at": r.created_at, "split_name": r.split_name, "is_external": r.is_external, "threshold": r.threshold,
           "n_recordings": r.n_recordings, "n_patients": r.n_patients, "warnings": r.warnings,
           "model": {"id": r.model_version.id, "name": r.model_version.name, "version": r.model_version.version},
           "dataset": {"id": r.dataset.id, "name": r.dataset.name},
           "headline": {k: (o.get(k) or {}).get("value") for k in ("sensitivity", "specificity", "auc")}}
    if full:
        out["metrics"] = r.metrics
    return out


@router.get("/evaluations")
def list_evaluations(db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    return [run_out(r) for r in db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))]


@router.get("/evaluations/{run_id}")
def read_evaluation(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*RESEARCH))):
    r = db.get(EvaluationRun, run_id)
    if r is None:
        raise HTTPException(404, "Evaluation not found")
    return run_out(r, full=True)


@router.post("/evaluations", status_code=201)
async def create_evaluation(
    model_version_id: int = Form(...),
    dataset_id: int = Form(...),
    threshold: float = Form(0.5, ge=0, le=1),
    is_external: bool = Form(False),
    predictions: UploadFile = File(...),
    training_manifest: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*RESEARCH)),
):
    m, d = db.get(ModelVersion, model_version_id), db.get(Dataset, dataset_id)
    if m is None or d is None:
        raise HTTPException(404, "Model version or dataset not found")
    if is_external and d.name in (m.training_datasets or []):
        raise HTTPException(422, "A dataset used for training cannot serve as external validation")
    text = (await predictions.read(50 * 1024 * 1024)).decode("utf-8-sig", errors="replace")
    train_ids = None
    if training_manifest is not None:
        tm = (await training_manifest.read(50 * 1024 * 1024)).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(tm))
        if not reader.fieldnames or "patient_id" not in reader.fieldnames:
            raise HTTPException(422, "Training manifest must have a patient_id column")
        train_ids = {row["patient_id"].strip() for row in reader}
    try:
        res = evaluate(text, threshold=threshold, training_patients=train_ids, is_external=is_external)
    except EvaluationError as e:
        raise HTTPException(422, str(e))
    run = EvaluationRun(model_version_id=m.id, dataset_id=d.id, split_name="external" if is_external else "test", is_external=is_external,
                        threshold=threshold, created_by=user.id, n_recordings=res["n_recordings"], n_patients=res["n_patients"],
                        metrics={"overall": res["overall"], "subgroups": res["subgroups"]}, warnings=res["warnings"])
    db.add(run)
    db.flush()
    audit.record(db, user, "evaluation.create", "evaluation_run", run.id, {"model": f"{m.name}@{m.version}", "dataset": d.name, "external": is_external})
    db.commit()
    db.refresh(run)
    return run_out(run, full=True)
