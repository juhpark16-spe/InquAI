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
  // 비회원 예시는 주문번호 없이도 답할 수 있는 일반 질문으로 (특정 주문의 배송 상태·파손·중복 결제는 주문번호가 있어야 상담 가능)
  const number = await createInquiry(page, email, title, "주말이나 공휴일에도 배송하나요? 금요일 저녁에 주문하면 언제 받을 수 있는지 궁금해요.");
  await expect(page.getByText(/담당자가 확인 후/)).toBeVisible();

  // 2. 관리자: 로그인 → 위쪽 검색창에 문의 번호 ('/' 키로 바로 입력) → 하나만 찾아져 상세 화면으로 바로
  await staffLogin(page, "admin");
  await page.getByLabel("문의 검색").focus();       // 대시보드를 다 불러온 뒤 ('/' 키 단축키는 아래 검색 테스트에서 확인)
  await page.keyboard.type(number);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/inquiries\/\d+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("배송").first()).toBeVisible(); // 분석 결과 유형

  // 3. 답변 작성 → 발송
  const answer = "안녕하세요. 주말·공휴일에는 배송하지 않으며, 금요일 오후 2시 이후 결제하신 주문은 다음 영업일에 출고됩니다.";
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

test("배정받은 상담원의 알림 종에 새 문의가 뜨고, 누르면 상세로", async ({ page }) => {
  // 시험용 분석기는 '배송' 단어를 배송 유형으로 봄 → 배송 담당 상담원(agent2)에게 자동 배정
  const title = `배송비 문의 ${Date.now()} (자동 테스트)`;
  await createInquiry(page, `e2e-bell-${Date.now()}@example.com`, title, "제주도도 3만원 넘으면 무료배송인가요? 추가 배송비가 있는지 궁금해요.");

  await staffLogin(page, "agent2");
  const bell = page.getByRole("button", { name: /^알림 \d+건$/ });
  await expect(bell).toBeVisible();
  await bell.click();
  await expect(page.getByRole("dialog", { name: "알림" }).getByText(title)).toBeVisible();
  await expect(page.getByRole("button", { name: "알림" })).toBeVisible();   // 열면 새 알림 숫자가 사라짐
  await page.getByRole("dialog", { name: "알림" }).getByText(title).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  // 배송 문의인데 주문번호가 없음 → 주문 정보 카드에서 [주문번호 요청 문구 넣기] → 답변 칸에 들어감
  await expect(page.getByText("배송 문의인데 주문번호가 없어요")).toBeVisible();
  await page.getByRole("button", { name: "+ 주문번호 요청 문구 넣기" }).click();
  await expect(page.getByPlaceholder(/고객에게 보낼 답변/)).toHaveValue(/주문번호\(예: 20261103-0042\)를 알려 주시겠어요/);
});

test("회원 주문 취소 요청 → 상담원이 취소 티켓 승인·문구 넣어 발송 → 고객 화면에서 주문 취소·답변 완료", async ({ page, browser }) => {
  // 고객(쇼핑몰 회원): 내 쇼핑에서 '결제 완료' 주문의 [이 주문 문의하기]
  await page.goto("/shop/login");
  await page.getByLabel("이메일").fill("customer08@example.com");
  await page.getByLabel("비밀번호").fill(STAFF_PASSWORD);   // 시험용 서버는 고객 비밀번호도 같은 값
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).not.toHaveURL(/\/shop\/login/);     // 로그인이 끝난 뒤 이동
  await page.goto("/my");
  const order = page.locator("li").filter({ hasText: "결제 완료" }).filter({ has: page.getByRole("link", { name: "이 주문 문의하기" }) }).first();
  const orderNumber = (await order.locator(".font-mono").first().textContent())!.trim();
  await order.getByRole("link", { name: "이 주문 문의하기" }).click();

  const title = `주문 취소 요청 ${Date.now()} (자동 테스트)`;
  await page.getByLabel("제목").fill(title);
  await page.getByLabel(/문의 내용/).fill("방금 결제했는데 색상을 잘못 골랐어요. 이 주문 취소해 주세요.");
  await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
  await page.getByRole("button", { name: "문의 등록" }).click();
  await expect(page.getByText("문의가 등록되었습니다")).toBeVisible();
  const number = (await page.getByText(/^INQ-\d{8}-\d{4}$/).textContent())!.trim();

  // 상담원(주문 취소 담당 agent1): 다른 브라우저 창에서 문의를 찾아 취소 티켓 승인
  const staff = await (await browser.newContext({ baseURL: "http://127.0.0.1:5174", locale: "ko-KR" })).newPage();
  await staffLogin(staff, "agent1");
  await expect(staff).toHaveURL(/\/admin\/inquiries/);   // 상담원은 로그인 후 문의 목록으로 옮겨짐 → 옮긴 뒤 검색
  await staff.getByLabel("문의 검색").fill(number);
  await staff.keyboard.press("Enter");
  await expect(staff.getByRole("heading", { name: title })).toBeVisible();
  await expect(staff.getByText("가능 (출고 전)")).toBeVisible();                 // 주문 정보: 출고 전이라 취소 가능
  await staff.getByRole("button", { name: "취소 승인" }).click();
  await expect(staff.getByText(/티켓을 승인했습니다/)).toBeVisible();
  await expect(staff.getByText("이미 취소된 주문")).toBeVisible();               // 승인하면 주문이 바로 취소됨

  // 답변: 관리자가 정한 '취소 완료' 문구를 넣고 발송
  await staff.getByRole("button", { name: /문구·주문 정보/ }).click();
  await staff.getByRole("button", { name: "취소 완료", exact: true }).click();
  await expect(staff.getByPlaceholder(/고객에게 보낼 답변/)).toHaveValue(/주문 취소가 완료되었습니다/);
  await staff.getByRole("button", { name: "발송", exact: true }).click();
  await expect(staff.getByText(/답변을 보냈습니다/)).toBeVisible();

  // 고객: 내 쇼핑에서 주문 '취소', 문의 '답변 완료'
  await page.goto("/my");
  await expect(page.locator("li").filter({ hasText: orderNumber }).getByText("취소", { exact: true })).toBeVisible();
  await expect(page.locator("section").filter({ hasText: title }).getByText("답변 완료")).toBeVisible();
});

test("출고 전 배송지 변경 요청 → 상담원이 [바로 처리]로 배송지 변경 → 처리 이력에 남음", async ({ page, browser }) => {
  // 고객(장시우): 내 쇼핑의 출고 전 주문에서 배송지 변경 문의 (주문번호 자동)
  await page.goto("/shop/login");
  await page.getByLabel("이메일").fill("customer09@example.com");
  await page.getByLabel("비밀번호").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).not.toHaveURL(/\/shop\/login/);
  await page.goto("/my");
  const order = page.locator("li").filter({ hasText: /결제 완료|상품 준비 중/ }).filter({ has: page.getByRole("link", { name: "이 주문 문의하기" }) }).first();
  await order.getByRole("link", { name: "이 주문 문의하기" }).click();
  const title = `배송지 변경 ${Date.now()} (자동 테스트)`;
  await page.getByLabel("제목").fill(title);
  await page.getByLabel(/문의 내용/).fill("이사를 가게 돼서 배송지를 새 주소로 바꾸고 싶어요. 아직 출고 전이죠?");
  await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
  await page.getByRole("button", { name: "문의 등록" }).click();
  const number = (await page.getByText(/^INQ-\d{8}-\d{4}$/).textContent())!.trim();

  // 상담원(배송 담당 agent2): 바로 처리 → 배송지 변경 (확인 창은 수락)
  const staff = await (await browser.newContext({ baseURL: "http://127.0.0.1:5174", locale: "ko-KR" })).newPage();
  staff.on("dialog", (d) => d.accept());
  await staffLogin(staff, "agent2");
  await expect(staff).toHaveURL(/\/admin\/inquiries/);
  await staff.getByLabel("문의 검색").fill(number);
  await staff.keyboard.press("Enter");
  await expect(staff.getByRole("heading", { name: title })).toBeVisible();
  await staff.getByRole("button", { name: "배송지 변경", exact: true }).click();
  const address = "경기 성남시 분당구 판교역로 166, 7층 (자동 테스트)";
  await staff.getByLabel("새 배송지").fill(address);
  await staff.getByRole("button", { name: "배송지 변경", exact: true }).last().click();
  await expect(staff.getByText(/배송지 변경: 경기 성남시 분당구 판교역로 166/).first()).toBeVisible();   // 결과 안내·처리 이력
  await expect(staff.getByText(`배송지 ${address}`, { exact: true })).toBeVisible();                     // 주문 정보의 배송지
});

test("확인 후 다시 안내를 체크해 발송 → 다시 안내 표시·목록 필터 → 고객에게 '추가 안내 예정'", async ({ page }) => {
  // 주문과 상관없는 일반 질문 (재입고 일정은 공급사 확인이 필요해 먼저 '확인 후 안내')
  const email = `e2e-recheck-${Date.now()}@example.com`;
  const title = "재입고 일정 문의 (자동 테스트)";
  const number = await createInquiry(page, email, title, "니트 가디건 아이보리 M 사이즈가 품절인데 언제 다시 들어오는지 알 수 있을까요?");

  await staffLogin(page, "admin");
  await page.getByLabel("문의 검색").focus();
  await page.keyboard.type(number);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  await page.getByPlaceholder(/고객에게 보낼 답변을 입력하세요/).fill("문의 감사합니다. 공급사에 재입고 일정을 확인 후 다시 안내드리겠습니다.");
  await expect(page.getByText(/'확인 후 안내' 문장이 있어요/)).toBeVisible();          // 체크 권유
  await page.getByLabel("🔁 확인 후 다시 안내").check();
  await page.getByLabel("확인할 내용").fill("공급사 재입고 일정");
  await page.getByRole("button", { name: "내일 오전 10시" }).click();
  await page.getByRole("button", { name: "발송 · 다시 안내 표시" }).click();
  await expect(page.getByText(/공급사 재입고 일정'을\(를\) 확인한 뒤/)).toBeVisible();
  await expect(page.getByText(/다시 안내할 문의 ·/)).toBeVisible();                     // 답변 칸 위 표시

  await page.goto("/admin/inquiries?recheck=true");
  await expect(page.getByRole("cell", { name: title })).toBeVisible();

  await page.context().clearCookies();
  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByText("추가 안내 예정")).toBeVisible();
  await expect(page.getByText("공급사 재입고 일정")).toHaveCount(0);                     // 내부 메모는 고객에게 안 보임
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
  await expect(page.getByLabel("문의 검색")).toBeVisible();   // 로그인 확인이 끝나 관리 화면이 뜬 뒤
  await page.keyboard.press("/");                     // '/' 키로 검색창에 바로 입력
  await expect(page.getByLabel("문의 검색")).toBeFocused();
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
