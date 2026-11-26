"""학습된 문의 분류 모델로 추론합니다.

실행 예시 (프로젝트 루트에서)
    python backend/training/predict.py "주문한 지 일주일인데 아직 배송이 안 왔어요"
    python backend/training/predict.py --model-dir models/sentiment_classifier "환불 빨리 해주세요"
"""

import argparse
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class InquiryClassifier:
    """서버 시작 시 한 번 만들어 두고 계속 재사용합니다."""

    def __init__(self, model_dir: str | Path, device: str | None = None, max_length: int = 256):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(self.device)
        self.model.eval()
        self.id2label = self.model.config.id2label

    @torch.inference_mode()
    def predict(self, texts: str | list[str]) -> list[dict]:
        if isinstance(texts, str):
            texts = [texts]
        inputs = self.tokenizer(
            texts, truncation=True, max_length=self.max_length, padding=True, return_tensors="pt"
        ).to(self.device)
        logits = self.model(**inputs).logits
        # sigmoid 로 학습한 모델(train.py --loss bce, 실험)은 유형마다 따로 0~1. 지금 서버 모델은 softmax (합 1)
        if self.model.config.problem_type == "multi_label_classification":
            probs = torch.sigmoid(logits).cpu()
        else:
            probs = torch.softmax(logits, dim=-1).cpu()

        results = []
        for row in probs:
            idx = int(row.argmax())
            results.append(
                {
                    "label": self.id2label[idx],
                    "confidence": round(float(row[idx]), 4),  # 확신도 (0.0 ~ 1.0)
                    "scores": {self.id2label[i]: round(float(p), 4) for i, p in enumerate(row)},
                }
            )
        return results


def main():
    p = argparse.ArgumentParser(description="문의 분류 모델 추론")
    p.add_argument("texts", nargs="+", help="분류할 문의 내용")
    p.add_argument("--model-dir", default="models/category_classifier")
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    if not model_dir.is_absolute():
        model_dir = PROJECT_ROOT / model_dir

    clf = InquiryClassifier(model_dir)
    for text, result in zip(args.texts, clf.predict(args.texts)):
        print(f"{text}\n  → {result['label']} (확신도 {result['confidence']})\n  {result['scores']}\n")


if __name__ == "__main__":
    main()
