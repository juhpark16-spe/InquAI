"""모델이 자주 틀리는 유형만 골라 OpenAI LLM으로 고객 문의를 생성합니다 (재학습 약점 보강, 4주차).

왜 필요한가
    상담원 분류 수정(data/test/written_pool.csv로 흉내 낸 11건)을 보면 모델이 틀리는 곳이 몰려 있습니다
    (docs/retraining.md "모델이 틀리는 곳"). 수정 11건만으로는 양이 적어서, 같은 유형의 문장을 더 만들어 보강합니다.
    - 배송 사고(누락·오배송·배송 중 파손)를 '상품'으로 봄
    - '주문 취소'를 다른 말로 하면(없던 걸로, 하나만 빼 주세요, 수량 줄이기) '기타'로 봄
    - 회원 정보·계정 문의를 '기타'로 봄, 받는 사람 변경을 '교환'으로 봄

    목표 유형은 **수정용 세트(written_pool)에서 드러난 약점만** 골랐습니다.
    평가 세트(written_eval)에서만 틀린 문장(선물 포장, 페이지 표기 오류 등)을 보고 목표를 정하면
    평가 점수가 부풀려지므로 넣지 않았습니다. 평가 세트 문장은 LLM에 보내지도 않습니다.

하는 일
    1. 약점 하위 유형(SUBTYPES) × 말투 3가지(generate_other.STYLES)마다 문장을 생성합니다.
       말투 참고용으로 data/supplement/seed_inquiries.csv(직접 만든 합성 문의, 라벨은 기준서로 고침)에서 같은 유형 2문장을 넣습니다.
    2. 걸러내기: 너무 짧음, 다른 유형으로 읽히는 단어(예: 배송 사고 문장에 '교환·반품·환불'),
       필요한 단서 없음, 기존 데이터와 겹침, **평가 세트 문장과 비슷함**(글자 3개 묶음 Jaccard 0.5 이상), 생성 문장끼리 비슷함.
    3. 남은 문장을 지금 분류 모델로 분류해(이 컴퓨터 안에서만) model_pred·model_conf를 붙입니다.
       지금 모델이 이미 맞히는 문장도 남깁니다 (틀린 문장만 넣으면 그 유형 쪽으로 너무 쏠림).

결과
    data/supplement/generated_weak.csv   text, category, sentiment, subtype, style, model_pred, model_conf
    → train.py --extra-train 으로 학습 데이터에만 더합니다 (prepare_data 기본 보충에는 넣지 않음).
    생성 문장은 꼭 일부를 사람이 읽어 보고, 이상한 문장은 지운 뒤 --refilter로 다시 정리하세요.

2차 보강 (--round 2, 2026-11-19)
    1차 모델(category_aug_s42)이 수정용·1차 평가 세트에서 여전히 틀린 유형: 회원 등급, 배송 요청사항, 누락,
    부가 서비스(선물 포장)·페이지 표기 오류·새 주문 방법(기타 경계), 결제 이상, 단순 변심 반품 구어체.
    1차 평가 세트의 오답도 목표에 넣었으므로, 공정한 비교를 위해 **생성 전에** 새 평가 세트
    data/test/written_eval2.csv(직접 작성 120문장)를 먼저 만들고 그 점수로 판단합니다 (docs/retraining.md).
    대조용으로 헷갈리기 쉬운 상품 질문(구성·사양·"~오나요")도 함께 생성해 한쪽으로 쏠리지 않게 합니다.
    결과: data/supplement/generated_weak2.csv

실행 예시 (프로젝트 루트에서)
    python backend/training/generate_weak.py --per-request 10
    python backend/training/generate_weak.py --refilter        # API 없이 걸러내기·분류만 다시
    python backend/training/generate_weak.py --round 2         # 2차 보강
"""

import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from generate_other import STYLES, clean_tail
from labels import CATEGORY_LABELS, SENTIMENT_LABELS
from prepare_data import MIN_TEXT_LENGTH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = "data/supplement/seed_inquiries.csv"
EVAL_FILES = ["data/test/written_eval.csv", "data/test/written_eval2.csv"]   # 평가 문장 (LLM에 보내지 않음)
EXISTING_FILES = ["data/raw/inquiries_with_qa.csv", "data/supplement/web_inquiries.csv",
                  "data/supplement/generated_other.csv", "data/supplement/generated_weak.csv", "data/supplement/generated_weak2.csv",
                  "data/test/real_inquiries_100.csv", "data/test/external_test.csv", "data/test/written_pool.csv",
                  *EVAL_FILES]
EVAL_SIMILAR = 0.5     # 평가 문장과 글자 3개 묶음이 이만큼 겹치면 버림
SELF_SIMILAR = 0.7     # 생성 문장끼리

NO_REQUEST = r"교환|반품|환불|바꿔|바꾸|취소|돌려"
# (하위 유형, 정답 유형, 설명, 예시, 있으면 버릴 단어, 꼭 있어야 할 단어)
SUBTYPES = [
    ("누락", "배송",
     "받은 상자에 구성품·여러 개 중 일부·사은품이 빠져 있음을 알림. 교환·반품·환불 요청은 하지 않고, 빠진 게 어떻게 되는지 묻거나 보내 달라고만 함 (원칙 5)",
     "3개 묶음 샀는데 상자 열어 보니 2개만 들어 있네요", NO_REQUEST, None),
    ("오배송", "배송",
     "주문한 것과 다른 상품·색상·사이즈, 또는 남의 물건이 옴. 교환·반품·환불이라는 말 없이 알리거나 어떻게 해야 하는지 물음 (원칙 5)",
     "베이지로 주문했는데 카키색이 들어 있어요", NO_REQUEST, None),
    ("배송 중 파손", "배송",
     "택배 상자가 젖음·찌그러짐·뜯김 상태로 와서 내용물이 깨지거나 상함. 배송 과정에서 생긴 일임이 문장에 드러남 (상자 상태, 택배 언급). 교환·반품·환불 요청 없음 (원칙 5)",
     "상자가 다 찌그러져서 왔는데 안에 액자 유리가 금 갔어요", NO_REQUEST, r"상자|박스|택배|포장|배송|도착|왔"),
    ("받는 사람·배송지 변경", "배송",
     "아직 출발 전인 이번 주문의 받는 사람 이름·연락처·배송지·배송 메모를 바꾸고 싶음 (회원 정보 수정이 아님)",
     "선물이라 받는 분 성함을 바꿔야 하는데 아직 안 나갔죠?", r"교환|반품|환불|회원|계정|마이페이지", None),
    ("출고 여부", "배송",
     "주문·결제 후 상품이 출발했는지, 언제 나가는지 물음. '결제했는데', '주문했는데'처럼 결제·주문 말이 앞에 자주 붙음",
     "그저께 결제했는데 아직 안 나간 건가요", r"취소|교환|반품|환불|오류|실패", None),
    ("바꿔 말한 취소", "주문 취소",
     "출고 전 주문을 없애 달라는 요청. 절반 이상은 '취소'라는 단어 없이 다른 말로 함 (없던 걸로, 안 살게요, 주문 넣은 거 빼 주세요, 접을게요, 철회 등)",
     "어제 넣은 주문 그냥 안 할게요 보내지 마세요", r"교환|반품|환불|쿠폰|적립", None),
    ("부분 취소·수량 줄이기", "주문 취소",
     "출고 전 주문에서 일부 상품만 빼거나 수량을 줄이고 싶음",
     "5개 주문했는데 3개만 받을게요 2개는 빼 주세요", r"교환|반품|환불|쿠폰|적립", None),
    ("취소 후 환불 수단", "주문 취소",
     "이미 취소한 주문의 결제 금액이 어떤 수단(카드·계좌·적립금)으로, 언제 돌아오는지 물음. 사용한 쿠폰·적립금이 되살아나는지는 묻지 않음 (원칙 2)",
     "취소한 주문 돈은 카드로 다시 들어오나요 계좌로 들어오나요", r"교환|반품|쿠폰", r"취소"),
    ("회원 정보 변경", "쿠폰·적립금·회원",
     "계정(회원 정보)에 등록된 휴대폰 번호·주소·이메일·이름·생일을 바꾸고 싶음. 특정 주문의 배송지 변경이 아님 (원칙 7)",
     "가입할 때 쓴 이메일을 다른 걸로 바꾸고 싶어요", r"주문|배송|택배|출고|개인정보",
     r"회원|계정|가입|마이페이지|내 ?정보|프로필|아이디"),
    ("계정 문제", "쿠폰·적립금·회원",
     "비밀번호 재설정·인증 메일이나 문자가 안 옴, 로그인 잠김, 휴면 해제, 아이디 찾기, 간편 로그인 연결 (원칙 7)",
     "본인인증 문자가 안 와서 비번을 못 바꿔요", r"주문|배송|결제|앱이 ?(꺼|튕)", None),
    ("구매 전 실물 질문", "상품",
     "사기 전에 사진과 실물의 색감·크기감·질감이 얼마나 다른지 물음. 페이지 표기가 틀렸다는 말은 없음 (원칙 7 상품 페이지 표기 문제)",
     "사진이 보정된 건지 실제로 보면 더 노란가요", r"교환|반품|환불|틀렸|잘못|다르게 (나와|적혀)", None),
]

# 2차 (2026-11-19): 1차 뒤에도 남은 약점 + 대조용 상품 질문
SUBTYPES2 = [
    ("회원 등급", "쿠폰·적립금·회원",
     "쇼핑몰 회원 등급의 기준·산정 시기·등급별 혜택·등급 유지·등급 하락을 물음 (원칙 4: 쇼핑몰이 주는 혜택). 특정 상품 질문이 아님",
     "실버에서 골드 되려면 몇 번 더 사야 해요", r"교환|반품|환불|취소|카드사", r"등급|VIP|vip|멤버십|회원|레벨"),
    ("배송 요청사항", "배송",
     "이번 배송을 어떻게 받을지 요청함: 문 앞·경비실·택배함·관리실에 맡기기, 부재 시 처리, 공동현관 비밀번호, 배송 메모, 도착 전 연락, 받는 시간",
     "벨 누르지 말고 문고리에 걸어 두고 가 주세요", r"교환|반품|환불|취소|회원|계정", None),
    ("구성품 누락", "배송",
     "세트·묶음 상품을 받았는데 구성품·부속품·사은품·여러 개 중 일부가 상자에 들어 있지 않음. 교환·반품·환불 요청 없이 알리거나 보내 달라고만 함 (원칙 5)",
     "믹서기 왔는데 칼날 부품이 안 들어 있어요", NO_REQUEST, r"없|빠|안 ?(들어|왔|와)|누락|모자"),
    ("부가 서비스", "기타",
     "선물 포장, 포장지·리본 선택, 쇼핑백 추가, 메시지 카드, 가격표·영수증 빼고 보내기 같은 부가 서비스를 묻거나 요청함 (원칙 7). 배송지·받는 사람 변경이 아님",
     "선물이라 예쁘게 포장해 주실 수 있나요", r"교환|반품|환불|취소|배송지|주소|등급", None),
    ("페이지 표기 오류", "기타",
     "상품 페이지의 표기가 서로 다르거나 틀렸다고 알림: 상세 설명과 옵션, 사진과 상품명, 페이지마다 가격·용량·개수가 다름. 받은 상품 이야기가 아니라 구매 전에 페이지를 보고 하는 말 (원칙 7 상품 페이지 표기 문제)",
     "상세 설명엔 500ml인데 옵션 선택하는 곳엔 300ml로 나와요", r"교환|반품|환불|받았|왔어|도착",
     r"다르|달라|틀|맞아|맞나|어느|뭐가|헷갈|잘못|안 ?맞"),
    ("새 주문 방법", "기타",
     "아직 사지 않은 고객이 주문하는 방법 자체를 물음: 방송·라이브에서 본 상품 주문, 전화 주문, 단체·대량 구매, 매장 주문 (원칙 7). 해외 배송은 배송 유형이라 넣지 않음. 결제 수단·쿠폰 문제가 아님",
     "라이브에서 본 원피스 주문 링크가 어디 있어요", r"결제|카드|쿠폰|적립|취소|교환|반품|배송비", None),
    ("결제 이상", "결제",
     "결제 과정 오류: 결제 실패라고 떴는데 돈이 빠져나감, 승인 문자가 두 번 옴, 입금했는데 입금 대기, 결제 후 주문 내역이 안 보임 (원칙 3)",
     # '취소'가 든 문장은 뺌: 1차 학습에서 "취소하면 카드 결제도 취소되나요"(주문 취소, 원칙 2)까지 결제로 보는 부작용이 생김
     "결제창이 멈춰서 다시 했더니 카드 승인이 두 번 났어요", r"교환|반품|쿠폰|적립|실수로|취소",
     r"결제|승인|출금|빠져|빠졌|카드|이체|입금|돈|계좌"),
    ("단순 변심 반품", "반품·환불",
     "받은 상품이 마음에 안 들거나 필요 없어져서 돌려보내고 돈을 돌려받고 싶음. 절반 이상은 '반품·환불'이라는 단어 없이 다른 말로 함 (물리다, 돌려보내다, 다시 보내 드리다, 반송, 돈으로 돌려받다)",
     "써 보니 생각보다 별로라 그냥 돌려보내고 싶어요", r"교환|바꿔|바꾸|다른 (사이즈|색)|취소|불량|파손", None),
    ("구성·사양 질문", "상품",
     "사기 전에 상품의 구성품·사양·용량·인원·유통기한·AS를 물음. '같이 와요?', '얼마나 남은 게 오나요', '어디로 보내요'처럼 배송 말투가 섞여도 상품 자체에 대한 질문 (원칙 6, 대조용)",
     "이 도시락통 뚜껑이랑 수저도 같이 와요?", r"교환|반품|환불|취소|안 ?(왔|와|들어)|빠져|없어요", None),
]
# 3차 (2026-11-19): 2차 보강의 부작용을 막는 대조 문장. 2차 보강 뒤 외부 테스트에서 늘어난 오답 유형(개수만 확인, 문장은 보지 않음)이
# 상품 → 배송(+4)·결제(+3)였고, 실전·평가 세트에서는 "취소 + 카드"를 결제로 봄. 같은 단어를 쓰지만 유형이 다른 문장을 넣어 균형을 맞춤.
SUBTYPES3 = [
    ("배송 말이 섞인 상품 질문", "상품",
     "사기 전에 상품 자체를 묻는데 '받으면, 와요, 오나요, 배송될 때, 택배로' 같은 말이 섞임: 받으면 바로 쓸 수 있는지, 조립된 채로 오는지, 냉동 상태로 오는지, 몇 개 들어 있는지 (원칙 6)",
     "이 선반 받으면 조립 따로 해야 해요 아니면 완제품으로 와요?",
     r"교환|반품|환불|취소|안 ?(왔|와|들어)|빠져|없어요|언제 (와|오|도착|출발)|배송비|운송장|송장",
     r"받|와요|오나요|와서|오는|배송|택배|도착"),
    ("가격·결제 말이 섞인 상품 질문", "상품",
     "사기 전에 상품 자체를 묻는데 '가격, 이 돈이면, 결제 전에, 구매 전에' 같은 말이 섞임: 이 가격에 몇 개 들었는지, 세트 구성, 정품 여부, 사양·사이즈 확인 (원칙 6). 결제 수단·할인·결제 오류 질문이 아님",
     "결제하기 전에 확인하려는데 이 가격이 한 개 값이에요 두 개 값이에요?",
     r"교환|반품|환불|취소|카드|할부|쿠폰|적립|할인|오류|영수증|입금",
     r"가격|원|결제|구매|사기 전|사려|주문하기 전"),
    ("취소 후 카드 승인 취소", "주문 취소",
     "출고 전 주문을 취소했거나 취소하려는데, 카드 결제·승인 취소가 언제 어떻게 되는지 물음 (원칙 2: 처음 신청한 처리 = 주문 취소)",
     "주문 취소했는데 카드 승인 취소 문자가 아직 안 와요",
     r"교환|반품|중복|두 ?번|이중|오류|실패", r"취소"),
    ("중복 주문 취소", "주문 취소",
     "고객이 실수로 같은 상품을 두 번 주문했거나 주문을 두 건 넣어서 그중 하나를 없애 달라고 함. 결제 오류가 아니라 주문을 잘못 넣은 것 (원칙 3 대조)",
     "실수로 같은 걸 두 번 주문해 버렸어요 하나는 취소해 주세요",
     r"교환|반품|오류|실패|승인|이중", r"주문"),
    ("중복 결제", "결제",
     "주문은 한 건인데 결제·카드 승인이 두 번 됨. 하나 취소해 달라고 해도 원인이 결제 오류 (원칙 3)",
     "주문은 하나만 했는데 카드 결제가 두 번 됐어요",
     r"교환|반품|실수로|두 ?(개|건) ?주문|주문을 두", r"결제|승인|카드|출금|빠져|청구"),
    ("교환 신청 철회", "교환",
     "이미 신청한 교환을 취소하거나 없던 걸로 하고 싶음 (원칙 2: 처음 신청한 처리 = 교환)",
     "교환 신청했는데 그냥 이대로 쓸게요 접수 취소해 주세요",
     r"반품|환불|주문 취소", r"교환"),
    ("반품 신청 철회", "반품·환불",
     "이미 신청한 반품·환불을 취소하거나 없던 걸로 하고 싶음 (원칙 2: 처음 신청한 처리 = 반품·환불)",
     "반품 접수한 거 취소할게요 그냥 쓰려고요",
     r"교환|주문 취소", r"반품|환불"),
]
ROUNDS = {1: (SUBTYPES, "data/supplement/generated_weak.csv"), 2: (SUBTYPES2, "data/supplement/generated_weak2.csv"),
          3: (SUBTYPES3, "data/supplement/generated_weak3.csv")}

# 생성 문장을 사람이 읽고 뺀 문장 (2026-11-17 검토). --refilter 때도 다시 빠집니다.
REVIEWED_OUT = [
    ("방금 결제직전인데 안 살게요 주문 넣은거 빼 주세요", "결제 전인지 주문 후인지 모호"),
    ("선물이라 수취인 이름 안 보이게 해주시면 감사해요", "요청이 무엇인지 모호"),
    ("사이즈 표기가 잘못된 옷이 왔습니다; 라벨은 L인데 실제로는 꽉 끼네요.", "받은 상품 사이즈 문제 = 상품"),
    ("사이즈 표기랑 달라서 입을 수가 없네요", "받은 상품 사이즈 문제 = 상품"),
    ("카라 색상이 사진과 다르게 왔습니다, 배송 과정에서 실수가 있었는지 궁금합니다.", "설명과 다름 = 상품"),
    ("상품 설명에는 블랙으로 되어 있었는데 회색 제품이 왔습니다. 확인 부탁드립니다.", "설명과 다름인지 오배송인지 모호"),
    ("진한네이비 주문했는데 연한네이비가왔어요 색차이가좀있는거같은데 확인만요", "색 차이 정도 = 상품"),
    ("색이 다르긴 한데 의외로 예뻐서 일단 괜찮아요", "색 차이 정도 = 상품"),
    ("색상은 예상과 다르지만 품질 자체는 좋아 보입니다, 확인 부탁드립니다.", "예상과 다름 = 상품"),
    ("취소했는데 결제할때적립금 사용했어요 환불은 적립금으로 다시 들어오나요 얼마나걸리나요", "사용한 적립금 복원 = 쿠폰 (원칙 4)"),
    ("상품취소했고 결제는 적립금+카드로 이중결제된거같아요 환불은 각각 어떻게,언제들어오나요", "적립금·카드 섞임"),
    ("결제 취소했는데 계좌로 며칠 내 입금되나요", "주문 취소인지 결제 취소인지 모호"),
    ("마이페이지에서 이름 수정 시 계속 오류가 발생합니다. 빨리 변경할 수 있는 방법 알려주세요.", "화면 오류 = 기타일 수 있음"),
    # 2차 (2026-11-19 검토)
    ("결제 실패 떴는데 돈은 환불돼서 다행이에요", "문의할 내용이 없음"),
    ("취소 요청했더니 결제 오류라 못해준대요 답답함", "취소가 안 되는 문의 = 주문 취소일 수 있음"),
    ("이전 주문에서 구성품이 누락된 적이 있는데요, 이번 제품은 구성물이 빠짐없이 들어있나요? 답답합니다", "누락 이야기 섞임"),
    ("표기랑 달라요, 실제 중량이 얼마예요?", "표기가 다르다고 알림 = 기타 (원칙 7)"),
    ("구성품중 나사 하나가 빠졌는데 안내문도 친절히 있어 감사해요 바로 확인했어요 나사만 부탁드려요", "문장이 어색함"),
    ("화장품 기프트세트에서 샘플 하나가 비어있어요 상자열자마자 확인했는데 분명 누락입니다 샘플만 보내주세요", "빈 용기 = 불량일 수 있음"),
    ("생각 바뀌어 반송했는데 처리 빨라서 만족스러워요", "칭찬 = 기타일 수 있음"),
    ("한개만 다시보내고싶은데 마이페이지 어디서신청하나요", "교환인지 반품인지 모호"),
    ("가능하면 첫 배송 시도로 전달해 주세요, 재배송이 어려워 불편합니다.", "설명의 '첫 배송'을 잘못 따라 씀"),
    ("첫 배송 때만 받아야 해서 그때 꼭 배송해 주세요", "설명의 '첫 배송'을 잘못 따라 씀"),
    ("첫배송만 해주세요 재배송하면 힘들어서요", "설명의 '첫 배송'을 잘못 따라 씀"),
    ("지난번 포장 완전 구겨져서 왔어요 이번엔 제발 신경써서 포장해 주세요", "배송 불만 섞임"),
    ("포장 시 상자 크기를 소형으로 해주실 수 있나요? 부피가 커서 걱정되어 문의드립니다.", "부가 서비스인지 모호"),
    ("해외에 거주 중이라 해외배송 가능한지, 해외 주문 방법 안내가 전혀 없어 불편합니다.", "해외 배송 = 배송 (FAQ F21)"),
    ("해외에서 주문하려면 통관 절차는 어떻게 되나요", "해외 배송 = 배송 (FAQ F21)"),
    ("해외(외국)에서 주문 가능한가요 통관이 문제면 어떻게 해야하는지 먼저 알고싶어요", "해외 배송 = 배송 (FAQ F21)"),
    ("해외에서도 주문 가능하면 좋겠는데 방법 알려줘요", "해외 배송 = 배송 (FAQ F21)"),
    ("해외에서 주문하려는데 절차랑 배송은 어떻게 되는지 알려줘요", "해외 배송 = 배송 (FAQ F21)"),
    ("평소 자주 이용하는데 이번에 옵션명이 달라 보여 구매 전 확인 요청드립니다", "무엇이 다른지 모호"),
    # 3차 (2026-11-19 검토)
    ("가격 보고 결제 전에 퀄리티 괜찮으면 바로 살게요", "질문이 아님"),
    ("결제하기전에 확인할게요 이 돈이면 용량이 500ml인지 1L인지 표기좀 정확히 해주세요", "표기 문제 = 기타일 수 있음"),
    ("결제전에 문의드려요 배송비 포함한가격인가요? 가격대가 착하네여ㅋ", "배송비 = 배송 (FAQ F15)"),
    ("도자기 찻잔 주문하려는데 택배로 올 때 포장이 불충분하면 깨질까 걱정됩니다, 포장 상태가 어떻게 되나요?", "배송 포장 = 배송일 수 있음"),
    ("상품설명엔2개라고돼있는데 받아보면1개만 와요? 이거 오류 아닌가요", "표기 오류 = 기타"),
    ("냉동 디저트인데 배송될 때 완전히 얼어 있는 상태로 오나요, 해동된 채로 오지 않으면 좋겠습니다", "냉동 배송 = 배송일 수 있음"),
    ("치즈케이크 배송올때 아이스팩 넣어서 와요 선물이라 걱정돼서요", "냉동 배송 = 배송일 수 있음"),
    ("아이스크림 냉동상태로 배송되서 오나요 녹아있진 않겠죠", "냉동 배송 = 배송일 수 있음"),
    ("이 냉동식품 받으면 냉동 상태로 오나요?", "냉동 배송 = 배송일 수 있음"),
    ("샐러드용 손질 채소 세트는 배송될 때 신선도가 어느 정도 유지되나요, 받자마자 바로 먹어도 괜찮을지 궁금합니다", "신선 배송 = 배송일 수 있음"),
    ("노트북 가방 받으면 내부에 15인치 수납 가능한지 실측 치수가 배송 안내에 같이 오나요?", "문장이 어색함"),
    ("삭제해달라고 했는데 카드승인취소가 안돼서 불편해요 빨리 처리좀", "무엇을 삭제했는지 모호"),
]
# LLM이 실제 값 대신 넣은 자리 표시 → 보충 데이터 관례('ㅇㅇ')로
PLACEHOLDERS = {"[새이름]": "ㅇㅇㅇ", "[새번호]": "010-ㅇㅇㅇㅇ-ㅇㅇㅇㅇ", "[새주소]": "ㅇㅇ동 ㅇㅇ아파트"}

PROMPT = """너는 한국 온라인 쇼핑몰에 들어오는 고객 문의를 만드는 작가다.
아래 조건에 맞는 서로 다른 고객 문의 {n}개를 만든다.

[유형] {category} - {subtype}: {desc}
[예시] {example}
[말투] {style}: {style_desc}
[실제 고객 말투 참고 (내용·길이는 따라 하지 않음)]
{seeds}

[규칙]
- 실제 고객이 쓴 것처럼 자연스럽게. 문장마다 상품·상황·표현·길이를 다르게 한다. 예시 문장을 바꿔 쓰지 않는다.
- 한 문의에는 위 내용 하나만 담는다. 다른 요청(교환·반품·환불 등)을 섞지 않는다.
- 주문번호·이름·전화번호·주소 같은 실제 값은 쓰지 않는다. 실제 브랜드 이름도 쓰지 않는다.
- 감정을 함께 붙인다. 대부분은 중립(담담한 문의·요청), 일부는 부정(불만·답답함을 드러냄, 느낌표를 남발하지 않음), 긍정은 드물게.
- 문장 끝에 인사말을 습관처럼 붙이지 않는다. 대부분은 질문·요청으로 바로 끝난다."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "sentiment": {"type": "string", "enum": SENTIMENT_LABELS}},
        "required": ["text", "sentiment"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def key(text: str) -> str:
    return re.sub(r"[\s.,!?~ㅠㅜ;]", "", str(text))


def grams(text: str) -> set:
    k = key(text)
    return {k[i:i + 3] for i in range(len(k) - 2)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def generate(client, model, subtype, style, n, seeds, rng, retries=3):
    name, category, desc, example, _, _ = subtype
    style_name, style_desc = style
    pool = seeds[seeds["category"] == category]["text"].tolist()
    picked = "\n".join(f"- {t}" for t in rng.sample(pool, min(2, len(pool))))
    content = PROMPT.format(n=n, category=category, subtype=name, desc=desc, example=example,
                            style=style_name, style_desc=style_desc, seeds=picked)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": content}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "inquiries", "strict": True, "schema": SCHEMA}},
            )
            items = json.loads(resp.choices[0].message.content)["items"]
            return [{"text": " ".join(i["text"].split()), "category": category, "sentiment": i["sentiment"],
                     "subtype": name, "style": style_name} for i in items]
        except Exception as e:  # 네트워크 오류, 사용량 제한 등
            print(f"  [재시도 {attempt + 1}/{retries}] {name}/{style_name}: {type(e).__name__}: {str(e)[:100]}")
    return []


def filter_rows(df: pd.DataFrame, out: Path | None = None) -> pd.DataFrame:
    """reason 칸이 비어 있으면 사용. out(지금 만드는 파일)은 겹침 검사에서 뺌."""
    df = df.copy()
    for k, v in PLACEHOLDERS.items():
        df["text"] = df["text"].str.replace(k, v, regex=False)
    df["text"] = df["text"].map(clean_tail)
    rules = {s[0]: (s[4], s[5]) for s in SUBTYPES + SUBTYPES2 + SUBTYPES3}
    reviewed = {key(t): f"사람 검토: {w}" for t, w in REVIEWED_OUT}

    def reason(row):
        if key(row.text) in reviewed:
            return reviewed[key(row.text)]
        if re.search(r"\[[^\]]*\]", row.text):
            return "자리 표시 남음"
        if len(key(row.text)) < MIN_TEXT_LENGTH:
            return "너무 짧음"
        drop, need = rules[row.subtype]
        if drop and re.search(drop, row.text):
            return "다른 유형 단어"
        if need and not re.search(need, row.text):
            return "단서 단어 없음"
        return None

    df["reason"] = [reason(r) for r in df.itertuples()]

    existing = set()
    for f in EXISTING_FILES:
        if resolve(f).exists() and resolve(f) != out:
            existing |= {key(t) for t in pd.read_csv(resolve(f), encoding="utf-8-sig")["text"]}
    df.loc[df["reason"].isna() & df["text"].map(key).isin(existing), "reason"] = "기존 데이터와 겹침"

    eval_grams = [grams(t) for f in EVAL_FILES if resolve(f).exists()
                  for t in pd.read_csv(resolve(f), encoding="utf-8")["text"]]
    kept = []
    for i, row in df[df["reason"].isna()].iterrows():
        g = grams(row.text)
        if any(jaccard(g, e) >= EVAL_SIMILAR for e in eval_grams):
            df.at[i, "reason"] = "평가 문장과 비슷함"
        elif any(jaccard(g, k) >= SELF_SIMILAR for k in kept):
            df.at[i, "reason"] = "생성 문장끼리 비슷함"
        else:
            kept.append(g)
    print(df["reason"].fillna("사용").value_counts().to_string())
    return df


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """지금 서버의 분류 모델로 분류 (이 컴퓨터 안에서만)."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_dir = PROJECT_ROOT / "models" / "category_classifier"
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
    preds, confs = [], []
    with torch.no_grad():
        for i in range(0, len(df), 64):
            enc = tok(df["text"].iloc[i:i + 64].tolist(), truncation=True, max_length=256, padding=True,
                      return_tensors="pt")
            prob = model(**enc).logits.softmax(-1)
            conf, idx = prob.max(-1)
            preds += [model.config.id2label[int(j)] for j in idx]
            confs += [round(float(c), 4) for c in conf]
    return df.assign(model_pred=preds, model_conf=confs)


def save(kept: pd.DataFrame, out: Path, seed: int):
    kept = classify(kept[["text", "category", "sentiment", "subtype", "style"]]).sample(frac=1, random_state=seed)
    kept.to_csv(out, index=False, encoding="utf-8-sig")
    wrong = kept["model_pred"] != kept["category"]
    summary = kept.assign(wrong=wrong).groupby(["category", "subtype"]).agg(n=("text", "size"), wrong=("wrong", "sum"))
    print(f"\n[하위 유형별 문장 수 / 지금 모델이 틀린 수]\n{summary.to_string()}")
    print(f"\n[감정]\n{kept['sentiment'].value_counts().to_string()}")
    print(f"\n[저장] {out} ({len(kept)}건, 지금 모델이 틀린 문장 {int(wrong.sum())}건)"
          " - 일부를 직접 읽어 보고 이상한 문장은 지워 주세요.")


def parse_args():
    p = argparse.ArgumentParser(description="약점 유형 문의 생성 (재학습 보강)")
    p.add_argument("--round", type=int, default=1, choices=sorted(ROUNDS), help="1차·2차 약점 보강, 3차 대조 문장")
    p.add_argument("--output", default=None, help="기본값: 1차 generated_weak.csv, 2차 generated_weak2.csv")
    p.add_argument("--model", default=None, help="기본값: .env의 OPENAI_MODEL, 없으면 gpt-5-mini")
    p.add_argument("--per-request", type=int, default=10, help="하위 유형·말투 조합마다 생성할 문장 수")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--refilter", action="store_true",
                   help="새로 생성하지 않고 --output 파일에 걸러내기·분류만 다시 적용 (API 비용 없음)")
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    subtypes, default_out = ROUNDS[args.round]
    out = resolve(args.output or default_out)
    assert {s[1] for s in subtypes} <= set(CATEGORY_LABELS)
    if args.refilter:
        df = pd.read_csv(out, encoding="utf-8-sig")
        print(f"[다시 걸러내기] {out.name} {len(df)}건")
        df = filter_rows(df.drop(columns=["model_pred", "model_conf"], errors="ignore"), out)
        save(df[df["reason"].isna()], out, args.seed)
        return

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env 를 확인해 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    client = OpenAI()
    seeds = pd.read_csv(resolve(SEED_FILE), encoding="utf-8-sig")
    rng = random.Random(args.seed)

    jobs = [(s, st, random.Random(rng.random())) for s in subtypes for st in STYLES]
    print(f"[생성] 모델 {model} / 요청 {len(jobs)}회 × {args.per_request}문장")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda j: generate(client, model, j[0], j[1], args.per_request, seeds, j[2]), jobs)
    df = pd.DataFrame([r for batch in results for r in batch])
    print(f"  생성 {len(df)}건")
    raw = out.with_name(out.stem + "_raw.csv")      # 걸러내기 전 원본 (다시 생성하지 않고 기준을 바꿔 볼 때)
    df.to_csv(raw, index=False, encoding="utf-8-sig")

    df = filter_rows(df, out)
    save(df[df["reason"].isna()], out, args.seed)


if __name__ == "__main__":
    main()
