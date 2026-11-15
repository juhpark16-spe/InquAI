"""문의 분석: Fine-tuned 분류 모델(유형·감정·확신도) + 규칙(처리 경로·긴급도).

서버가 시작될 때 Analyzer 를 한 번 만들어 app.state 에 두고 계속 씁니다 (모델 불러오기에 몇 초 걸림).
"""

from backend.ai.rules import get_route, get_urgency
from backend.core.config import Settings
from backend.training.predict import InquiryClassifier


class Analyzer:
    def __init__(self, settings: Settings):
        self.category_model = InquiryClassifier(settings.category_model_dir)
        self.sentiment_model = InquiryClassifier(settings.sentiment_model_dir)
        self.model_version = f"{settings.category_model_version}+{settings.sentiment_model_version}"

    def analyze(self, text: str) -> dict:
        c = self.category_model.predict(text)[0]
        s = self.sentiment_model.predict(text)[0]
        return {
            "category": c["label"],
            "confidence": c["confidence"],
            "sentiment": s["label"],
            "sentiment_confidence": s["confidence"],
            "route": get_route(c["label"]),
            "urgency": get_urgency(c["label"], s["label"], text),
            "scores": {"category": c["scores"], "sentiment": s["scores"]},
            "model_version": self.model_version,
        }
