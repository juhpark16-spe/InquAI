// 핵심 흐름: 고객 문의 등록 → 상담원 답변 발송 → 고객이 조회 화면에서 답변 확인
// 시험용 백엔드는 LLM이 없어 자동 답변 없이 모두 담당자에게 갑니다 (backend/tests/e2e_server.py)
import { expect, test, type Page } from "@playwright/test";

const STAFF_PASSWORD = process.env.E2E_PASSWORD ?? "e2e-test-password-1234";
const LOOKUP_PASSWORD = "lookup-pass-123";

async function staffLogin(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("아이디").fill(username);
  await page.getByLabel("비밀번호").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/admin/);
}

async function createInquiry(page: Page, email: string, title: string, content: string) {
  await page.goto("/inquiry");
  await page.getByLabel("이름").fill("테스트 고객");
  await page.getByLabel(/^이메일/).fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByLabel("비밀번호 확인").fill(LOOKUP_PASSWORD);
  await page.getByLabel("제목").fill(title);
  await page.getByLabel(/문의 내용/).fill(content);
  await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
  await page.getByRole("button", { name: "문의 등록" }).click();

  await expect(page.getByText("문의가 등록되었습니다")).toBeVisible();
  const number = (await page.getByText(/^INQ-\d{8}-\d{4}$/).textContent())!.trim();
  return number;
}

test("고객 문의 → 상담원 답변 발송 → 고객 조회에서 답변 확인", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const title = "배송 문의 (자동 테스트)";

  // 1. 고객: 비회원 문의 등록 → 문의 번호와 접수 안내
  const number = await createInquiry(page, email, title, "어제 주문한 상품이 아직 배송 출발을 안 했어요. 언제 보내 주시나요?");
  await expect(page.getByText(/담당자가 확인 후/)).toBeVisible();

  // 2. 관리자: 로그인 → 위쪽 검색창에 문의 번호 ('/' 키로 바로 입력) → 하나만 찾아져 상세 화면으로 바로
  await staffLogin(page, "admin");
  await page.keyboard.press("/");
  await page.keyboard.type(number);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/inquiries\/\d+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("배송").first()).toBeVisible(); // 분석 결과 유형

  // 3. 답변 작성 → 발송
  const answer = "안녕하세요. 주문하신 상품은 오늘 출고 예정이며, 출고되면 송장번호를 문자로 보내 드리겠습니다.";
  await page.getByPlaceholder(/고객에게 보낼 답변을 입력하세요/).fill(answer);
  await page.getByRole("button", { name: "발송", exact: true }).click();
  await expect(page.getByText(/답변을 보냈습니다/)).toBeVisible();

  // 4. 고객: 이메일 + 조회 비밀번호로 조회 → 상담원 답변이 보임
  await page.context().clearCookies(); // 관리자 로그인과 상관없이 고객으로
  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByText(/문의 1건/)).toBeVisible();
  await expect(page.getByText(answer)).toBeVisible();
});

test("조회 비밀번호가 틀리면 문의가 보이지 않음", async ({ page }) => {
  const email = `e2e-wrong-${Date.now()}@example.com`;
  await createInquiry(page, email, "적립금 문의 (자동 테스트)", "적립금은 언제 들어오나요? 확인 부탁드려요.");

  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill("wrong-password-9");
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByText("적립금 문의 (자동 테스트)")).toHaveCount(0);
});

test("상담원은 관리자 전용 화면에 들어갈 수 없음", async ({ page }) => {
  await staffLogin(page, "agent1");
  await page.goto("/admin/users");
  await expect(page).not.toHaveURL(/\/admin\/users/);
});

test("여러 건이 찾아지면 문의 목록에 검색어와 함께 보여 줌", async ({ page }) => {
  await staffLogin(page, "admin");
  await page.getByLabel("문의 검색").fill("자동 테스트");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/inquiries\?q=/);
  await expect(page.getByText("검색어:")).toBeVisible();
  await page.getByRole("button", { name: "검색어 지우기" }).click();
  await expect(page).not.toHaveURL(/q=/);
});

test("로그인하지 않으면 관리 화면 대신 로그인 화면", async ({ page }) => {
  await page.goto("/admin/inquiries");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "InquAI 관리" })).toBeVisible();
});
