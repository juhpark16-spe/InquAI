"""KoELECTRA로 고객 문의 유형 분류 모델을 Fine-tuning 합니다.

데이터 형식 (CSV 또는 JSONL, UTF-8)
    text,category,sentiment
    "주문한 상품이 아직 안 왔어요",배송,부정
    ...
    - text: 문의 내용 (필수)
    - category / sentiment: 라벨 (학습할 컬럼만 있으면 됨, 값은 labels.py 참고)
    - 긴급도는 규칙으로 정하므로 학습 데이터에 필요 없습니다.

실행 예시 (프로젝트 루트에서)
    # 문의 유형 (기본 모델: KoELECTRA)
    python backend/training/train.py --data data/raw/inquiries.csv
    # 감정
    python backend/training/train.py --data data/raw/inquiries.csv --label-column sentiment
    # 비교 모델: KcELECTRA (v2022 revision), 결과를 다른 폴더에 저장
    python backend/training/train.py --data data/raw/inquiries.csv --model-name beomi/KcELECTRA-base --revision v2022 --output-dir models/category_kcelectra --report-name category_kcelectra

결과
    models/<label>_classifier/        학습된 모델과 토크나이저 (id2label 포함)
    data/processed/<label>_{train,valid,test}.csv   분할한 데이터 (Zero-shot 비교 시 같은 test 사용)
    evaluation/<report-name>_test_report.json       평가 데이터 정확도, Macro F1, 혼동 행렬
                                                    (report-name 기본값: <label>)
    같은 --seed면 데이터 분할이 같으므로 모델끼리 같은 평가 데이터로 비교됩니다.
    데이터에 dialog_id 컬럼이 있으면 같은 상담 통화의 문장은 학습·검증·평가 중 한 곳에만 들어갑니다.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.utils.class_weight import compute_class_weight
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
    set_seed,
)

from labels import LABEL_SETS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "monologg/koelectra-base-v3-discriminator"
DEFAULT_DATA = "data/raw/inquiries.csv"


def parse_args():
    p = argparse.ArgumentParser(description="KoELECTRA 문의 분류 모델 학습")
    p.add_argument(
        "--data",
        default=DEFAULT_DATA,
        help=f"학습 데이터 파일 (.csv / .jsonl, 기본값: {DEFAULT_DATA})",
    )
    p.add_argument("--label-column", default="category", choices=list(LABEL_SETS))
    p.add_argument("--model-name", default=DEFAULT_MODEL)
    p.add_argument("--revision", default=None, help="Hugging Face 모델 revision (예: v2022)")
    p.add_argument("--output-dir", default=None, help="기본값: models/<label>_classifier")
    p.add_argument("--report-name", default=None, help="평가 결과 파일 이름, 기본값: <label>")
    p.add_argument("--epochs", type=float, default=6)
    p.add_argument("--lr", type=float, default=3e-5)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--max-length", type=int, default=256)
    p.add_argument("--warmup-ratio", type=float, default=0.1)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--class-weight", action="store_true", help="클래스 불균형 보정용 가중치 적용")
    p.add_argument("--class-weight-power", type=float, default=0.5,
                   help="가중치 완화 정도 (1=balanced 그대로, 0.5=제곱근으로 완화, 0=가중치 없음)")
    p.add_argument("--label-smoothing", type=float, default=0.1,
                   help="정답을 100%%가 아닌 90%% 등으로 부드럽게 학습해 과한 확신도를 줄임 (0이면 끔)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--extra-train", nargs="*", default=[],
                   help="학습 분할에만 더할 CSV (text, <라벨> 컬럼). 상담원 분류 수정·약점 보강 문장 등 (docs/retraining.md)")
    p.add_argument("--extra-repeat", type=int, nargs="*", default=[],
                   help="--extra-train 파일마다 반복 횟수 (가중치 대신 여러 번 넣기, 기본 1)")
    p.add_argument("--label-fixes", default=None,
                   help="기본 데이터 라벨 수정 CSV (text, <라벨> 컬럼). 분할 후 적용해 분할은 그대로 유지 (docs/retraining.md)")
    p.add_argument("--group-column", default="dialog_id",
                   help="같은 대화의 문장을 한쪽에만 넣기 위한 컬럼. 빈 문자열이면 문장 단위로 분할")
    return p.parse_args()


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_data(path: Path, label_column: str, labels: list[str], group_column: str | None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"데이터 파일을 찾을 수 없습니다: {path}\n"
            f"'python backend/training/prepare_data.py'를 먼저 실행하여 학습 데이터를 생성하거나 올바른 경로를 지정해 주세요."
        )

    if path.suffix == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")
    elif path.suffix in (".jsonl", ".json"):
        df = pd.read_json(path, lines=path.suffix == ".jsonl")
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {path.suffix}")

    missing = {"text", label_column} - set(df.columns)
    if missing:
        raise ValueError(f"데이터에 컬럼이 없습니다: {missing} (현재 컬럼: {list(df.columns)})")

    columns = ["text", label_column]
    if group_column and group_column in df.columns:
        columns.append(group_column)
    df = df[columns].dropna(subset=["text", label_column])
    df["text"] = df["text"].astype(str).str.strip()
    df[label_column] = df[label_column].astype(str).str.strip()
    df = df[df["text"] != ""].drop_duplicates(subset="text")

    unknown = sorted(set(df[label_column]) - set(labels))
    if unknown:
        raise ValueError(f"정의되지 않은 라벨이 있습니다: {unknown} (허용: {labels})")

    print(f"[데이터] {len(df)}건 / 라벨 분포:\n{df[label_column].value_counts().to_string()}\n")
    return df.reset_index(drop=True)


def add_extra_train(train_df, df, args, label_column, labels):
    """--extra-train 파일을 학습 분할에만 더합니다. 검증·평가 분할에는 넣지 않아 내부 평가 점수가 그대로 비교됩니다.

    이미 데이터에 있는 문장은 빼고, --extra-repeat만큼 반복해서 넣습니다.
    """
    info = []
    known = set(df["text"].str.replace(" ", "", regex=False))
    for i, path in enumerate(args.extra_train):
        repeat = args.extra_repeat[i] if i < len(args.extra_repeat) else 1
        extra = load_data(resolve(path), label_column, labels, None)[["text", label_column]]
        extra = extra[~extra["text"].str.replace(" ", "", regex=False).isin(known)]
        known |= set(extra["text"].str.replace(" ", "", regex=False))
        train_df = pd.concat([train_df] + [extra] * repeat, ignore_index=True)
        info.append({"file": str(path), "rows": len(extra), "repeat": repeat})
        print(f"[추가 학습 데이터] {Path(path).name}: {len(extra)}건 × {repeat}회 (학습 분할에만)")
    return train_df, info


def split_data(df: pd.DataFrame, label_column: str, seed: int, group_column: str | None = None):
    """학습 80% / 검증 10% / 평가 10%, 라벨 비율을 유지(stratify)해서 나눕니다.

    group_column(예: dialog_id)이 있으면 같은 대화(상담 통화)의 문장은 반드시 같은 쪽에 넣습니다.
    같은 통화의 다른 문장을 학습에서 미리 보면 평가가 실제보다 쉬워지기 때문입니다.
    그룹 값이 없는 문장(보충 데이터 등)은 문장 하나를 하나의 그룹으로 봅니다.
    """
    if group_column and group_column in df.columns:
        groups = df[group_column].fillna("").astype(str)
        groups = groups.where(groups != "", "_row" + df.index.astype(str))
        # 10개 묶음으로 나눈 뒤 1개는 평가, 1개는 검증, 나머지 8개는 학습 (라벨 비율도 최대한 유지)
        folds = list(
            StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=seed).split(
                df, df[label_column], groups
            )
        )
        test_idx, valid_idx = folds[0][1], folds[1][1]
        train_idx = np.setdiff1d(np.arange(len(df)), np.concatenate([test_idx, valid_idx]))
        train_df, valid_df, test_df = df.iloc[train_idx], df.iloc[valid_idx], df.iloc[test_idx]

        shared = set(groups.iloc[train_idx]) & (set(groups.iloc[test_idx]) | set(groups.iloc[valid_idx]))
        print(f"[분할] 대화 단위 ({group_column}), 학습과 겹치는 대화 수: {len(shared)}")
        return train_df, valid_df, test_df

    print("[분할] 문장 단위 (그룹 컬럼 없음)")
    train_df, rest_df = train_test_split(
        df, test_size=0.2, stratify=df[label_column], random_state=seed
    )
    valid_df, test_df = train_test_split(
        rest_df, test_size=0.5, stratify=rest_df[label_column], random_state=seed
    )
    return train_df, valid_df, test_df


def to_dataset(df: pd.DataFrame, label_column: str, label2id: dict, tokenizer, max_length: int):
    ds = Dataset.from_dict(
        {"text": df["text"].tolist(), "labels": [label2id[x] for x in df[label_column]]}
    )
    return ds.map(
        lambda batch: tokenizer(batch["text"], truncation=True, max_length=max_length),
        batched=True,
        remove_columns=["text"],
    )


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "macro_f1": f1_score(labels, preds, average="macro"),
    }


class WeightedTrainer(Trainer):
    """클래스 가중치와 라벨 스무딩을 적용한 CrossEntropy 손실을 쓰는 Trainer."""

    def __init__(self, *args, class_weights: torch.Tensor | None = None, label_smoothing: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights
        self.label_smoothing = label_smoothing

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        weight = None
        if self.class_weights is not None:
            weight = self.class_weights.to(outputs.logits.device)
        loss = torch.nn.functional.cross_entropy(
            outputs.logits, labels, weight=weight, label_smoothing=self.label_smoothing
        )
        return (loss, outputs) if return_outputs else loss


def main():
    args = parse_args()
    set_seed(args.seed)

    label_column = args.label_column
    labels = LABEL_SETS[label_column]
    label2id = {label: i for i, label in enumerate(labels)}
    id2label = {i: label for label, i in label2id.items()}

    output_dir = resolve(args.output_dir or f"models/{label_column}_classifier")
    processed_dir = PROJECT_ROOT / "data" / "processed"
    eval_dir = PROJECT_ROOT / "evaluation"
    processed_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    # 1. 데이터 로드·분할
    df = load_data(resolve(args.data), label_column, labels, args.group_column)
    train_df, valid_df, test_df = split_data(df, label_column, args.seed, args.group_column)
    if args.label_fixes:
        # 분할한 뒤에 고쳐야 분할이 지금 모델과 똑같아 공정하게 비교할 수 있음
        fixes = pd.read_csv(resolve(args.label_fixes), encoding="utf-8-sig")
        fix_map = dict(zip(fixes["text"], fixes[label_column].astype(str).str.strip()))
        bad = sorted(set(fix_map.values()) - set(labels))
        if bad:
            raise ValueError(f"라벨 수정 파일에 정의되지 않은 라벨: {bad}")
        changed = 0
        train_df, valid_df, test_df = train_df.copy(), valid_df.copy(), test_df.copy()
        for part in (train_df, valid_df, test_df):
            hit = part["text"].isin(fix_map)
            part.loc[hit, label_column] = part.loc[hit, "text"].map(fix_map)
            changed += int(hit.sum())
        print(f"[라벨 수정] {Path(args.label_fixes).name}: {len(fix_map)}개 문장, {changed}건 고침")
    train_df, extra_info = add_extra_train(train_df, df, args, label_column, labels)
    for name, part in (("train", train_df), ("valid", valid_df), ("test", test_df)):
        part.to_csv(processed_dir / f"{label_column}_{name}.csv", index=False, encoding="utf-8-sig")
    print(f"[분할] train {len(train_df)} / valid {len(valid_df)} / test {len(test_df)}")

    # 2. 토크나이저·모델
    # 사전학습용 AutoModelForPreTraining 대신 분류 헤드가 붙은 AutoModelForSequenceClassification 사용
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, revision=args.revision)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        revision=args.revision,
        num_labels=len(labels),
        id2label=id2label,
        label2id=label2id,
    )

    train_ds = to_dataset(train_df, label_column, label2id, tokenizer, args.max_length)
    valid_ds = to_dataset(valid_df, label_column, label2id, tokenizer, args.max_length)
    test_ds = to_dataset(test_df, label_column, label2id, tokenizer, args.max_length)

    class_weights = None
    if args.class_weight:
        # 학습 데이터에 없는 라벨이 있으면 compute_class_weight가 실패하므로 등장한 라벨만 계산
        y = np.array(train_ds["labels"])
        present = np.unique(y)
        weights = np.ones(len(labels), dtype=np.float32)
        weights[present] = compute_class_weight("balanced", classes=present, y=y)
        # 불균형이 심하면(예: 긍정 1%) balanced 가중치가 수십 배가 되어 모델이 한 라벨만 예측하게 무너집니다.
        # 제곱근(power 0.5)으로 완화하고 평균이 1이 되도록 맞춥니다.
        weights = weights ** args.class_weight_power
        weights = weights / weights.mean()
        class_weights = torch.tensor(weights, dtype=torch.float)
        print(f"[클래스 가중치] { {id2label[i]: round(float(w), 3) for i, w in enumerate(weights)} }")

    # 3. 학습 설정
    training_args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        # transformers 5에서 warmup_ratio가 없어짐. warmup_steps에 0~1 소수를 넣으면 전체 스텝 대비 비율
        warmup_steps=args.warmup_ratio,
        weight_decay=args.weight_decay,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        save_only_model=True,  # 옵티마이저 상태는 저장 안 함 (체크포인트 약 2.6GB → 0.9GB, 학습 이어하기만 불가)
        train_sampling_strategy="group_by_length",  # 비슷한 길이끼리 묶어 패딩 낭비 감소
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=20,
        fp16=torch.cuda.is_available(),
        report_to="none",
        seed=args.seed,
    )

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)],
        class_weights=class_weights,
        label_smoothing=args.label_smoothing,
    )

    # 4. 학습 (검증 Macro F1이 가장 높은 체크포인트를 최종 모델로 사용)
    trainer.train()

    # 5. 평가 데이터로 최종 성능 측정
    pred = trainer.predict(test_ds)
    y_pred = np.argmax(pred.predictions, axis=-1)
    y_true = pred.label_ids
    label_ids = list(range(len(labels)))

    report_text = classification_report(
        y_true, y_pred, labels=label_ids, target_names=labels, digits=4, zero_division=0
    )
    print(f"\n[평가 데이터 결과]\n{report_text}")

    result = {
        "label_column": label_column,
        "model_name": args.model_name,
        "revision": args.revision,
        "num_samples": {"train": len(train_df), "valid": len(valid_df), "test": len(test_df)},
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, labels=label_ids, average="macro", zero_division=0),
        "classification_report": classification_report(
            y_true, y_pred, labels=label_ids, target_names=labels, output_dict=True, zero_division=0
        ),
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=label_ids).tolist(),
        },
        "hyperparameters": {
            "epochs": args.epochs,
            "lr": args.lr,
            "batch_size": args.batch_size,
            "max_length": args.max_length,
            "class_weight": args.class_weight,
            "class_weight_power": args.class_weight_power,
            "label_smoothing": args.label_smoothing,
            "seed": args.seed,
            "extra_train": extra_info,
        },
    }
    report_path = eval_dir / f"{args.report_name or label_column}_test_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6. 최종 모델 저장 (FastAPI에서 이 폴더를 불러와 추론)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    print(f"[저장] 모델: {output_dir}")
    print(f"[저장] 평가 결과: {report_path}")
    print(f"accuracy={result['accuracy']:.4f}  macro_f1={result['macro_f1']:.4f}")


if __name__ == "__main__":
    main()
