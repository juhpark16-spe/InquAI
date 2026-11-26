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

/** 비회원 문의 칸을 채우기만 함 (등록은 하지 않음) */
async function createInquiryStart(page: Page, title: string, content: string) {
  await page.goto("/inquiry");
  await page.getByLabel("이름").fill("테스트 고객");
  await page.getByLabel(/^이메일/).fill(`e2e-${Date.now()}@example.com`);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByLabel("비밀번호 확인").fill(LOOKUP_PASSWORD);
  await page.getByLabel("제목").fill(title);
  await page.getByLabel(/문의 내용/).fill(content);
  await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
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
  await expect(page.getByText("답변 준비 중")).toBeVisible();               // 내부 상태(검토 대기 등) 대신 고객 말로
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/created.png` });
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
  await expect(page.getByRole("heading", { name: "내 문의 조회 비회원" })).toBeVisible();   // 제목 옆 '비회원' 표시
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByRole("button", { name: "조회", exact: true }).click();
  await expect(page.getByText(/문의 1건/)).toBeVisible();                       // 입력 카드는 한 줄 띠로 접힘
  await expect(page.getByText("답변 완료 1")).toBeVisible();
  await expect(page.getByLabel("조회 비밀번호")).toHaveCount(0);
  await expect(page.getByText(answer)).toBeVisible();

  // 5. 조회 끝내기 → 결과와 입력한 내용이 지워지고 처음 화면 (공용 PC)
  await page.getByRole("button", { name: "조회 끝내기" }).click();
  await expect(page.getByText(answer)).toHaveCount(0);
  await expect(page.getByLabel("문의할 때 쓴 이메일")).toHaveValue("");
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
  // 환불 미리 보기: 고른 주문(출고 전)이라 '전체 취소: n원 전액 환불' (동의 체크 없음)
  await expect(page.getByText("이 주문을 취소·반품하면")).toBeVisible();
  await expect(page.getByText(/전체 취소: [\d,]+원 전액 환불/)).toBeVisible();
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/refund-preview.png`, fullPage: true });
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
  await expect(staff.getByText("가능 (출고 전)").first()).toBeVisible();
  // 주문 정보: 한 줄 요약 + 취소 문의에 맞춘 핵심 칸, 나머지는 '주문 전체 정보'로 접힘
  await expect(staff.getByText(/결제 완료.*취소 가능|상품 준비 중.*취소 가능/).first()).toBeVisible();
  if (process.env.E2E_SHOTS) await staff.screenshot({ path: `${process.env.E2E_SHOTS}/order-card.png`, fullPage: true });                 // 주문 정보: 출고 전이라 취소 가능
  await staff.getByRole("button", { name: "취소 승인" }).click();
  // 승인 전 확인창: 주문·전액 환불 안내 → [취소 승인]
  const approve = staff.getByRole("alertdialog");
  await expect(approve).toContainText("전액 환불");
  await approve.getByRole("button", { name: "취소 승인" }).click();
  await expect(staff.getByText(/요청을 승인했습니다/)).toBeVisible();
  await expect(staff.getByRole("button", { name: "AI 초안 다시 만들기" }).first()).toBeVisible();   // 안내 안에 바로 누르는 버튼
  await expect(staff.getByText("이미 취소된 주문").first()).toBeVisible();               // 승인하면 주문이 바로 취소됨

  // 답변: 관리자가 정한 '취소 완료' 문구를 넣고 발송
  await staff.getByRole("button", { name: /문구·주문 정보/ }).click();
  await staff.getByRole("button", { name: "취소 완료", exact: true }).click();
  await expect(staff.getByPlaceholder(/고객에게 보낼 답변/)).toHaveValue(/주문 취소가 완료되었습니다/);
  // 쓰던 답변이 있으면 '문의 목록' 같은 링크를 눌러도 먼저 물음 → [머무르기]면 그대로
  await staff.getByRole("link", { name: "← 문의 목록" }).click();
  const leave = staff.getByRole("alertdialog");
  await expect(leave).toContainText("작성 중인 답변이 있어요");
  await leave.getByRole("button", { name: "머무르기" }).click();
  await expect(staff.getByPlaceholder(/고객에게 보낼 답변/)).toHaveValue(/주문 취소가 완료되었습니다/);
  await staff.getByRole("button", { name: "발송", exact: true }).click();
  await expect(staff.getByText(/답변을 보냈습니다/)).toBeVisible();
  // 답변한 문의를 다시 열었다가 완료: 바로 끝나지 않고 창에서 '답변으로 해결'(기본 선택)을 확인
  await staff.getByRole("button", { name: "다시 열기" }).click();
  await staff.getByRole("button", { name: "완료 처리" }).click();
  const done = staff.getByRole("dialog", { name: "완료 처리" });
  await expect(done.getByRole("radio", { name: "답변으로 해결" })).toBeChecked();
  await done.getByRole("button", { name: "완료 처리" }).click();
  await expect(staff.getByRole("button", { name: "다시 열기" })).toBeVisible();

  // 고객: 내 쇼핑에서 주문 '취소', 문의 '답변 완료'
  await page.goto("/my");
  await expect(page.locator("li").filter({ hasText: orderNumber }).getByText("취소", { exact: true })).toBeVisible();
  await expect(page.locator("section").filter({ hasText: title }).getByText("답변 완료")).toBeVisible();
  // 회원이 문의 조회 화면에 오면: 회원 문의는 여기서 찾을 수 없으니 내 쇼핑으로 안내
  await page.goto("/inquiry/lookup");
  await expect(page.getByRole("link", { name: "내 문의 보기" })).toBeVisible();
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/member-lookup.png` });
  await page.getByRole("link", { name: "내 문의 보기" }).click();
  await expect(page).toHaveURL(/\/my$/);
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

  // 상담원(배송 담당 agent2): 바로 처리 → 배송지 변경 (화면의 확인창에서 [배송지 변경])
  const staff = await (await browser.newContext({ baseURL: "http://127.0.0.1:5174", locale: "ko-KR" })).newPage();
  await staffLogin(staff, "agent2");
  await expect(staff).toHaveURL(/\/admin\/inquiries/);
  await staff.getByLabel("문의 검색").fill(number);
  await staff.keyboard.press("Enter");
  await expect(staff.getByRole("heading", { name: title })).toBeVisible();
  await staff.getByRole("button", { name: "배송지 변경", exact: true }).click();
  const address = "경기 성남시 분당구 판교역로 166, 7층 (자동 테스트)";
  await staff.getByLabel("새 배송지").fill(address);
  await staff.getByRole("button", { name: "배송지 변경", exact: true }).last().click();
  const confirm = staff.getByRole("alertdialog");
  await expect(confirm.getByText(/배송지를 '경기 성남시 분당구 판교역로 166/)).toBeVisible();   // 브라우저 확인창 대신 화면 디자인의 확인창
  await confirm.getByRole("button", { name: "배송지 변경" }).click();
  await expect(confirm).toHaveCount(0);
  await expect(staff.getByText(/배송지 변경: 경기 성남시 분당구 판교역로 166/).first()).toBeVisible();   // 결과 안내·처리 이력
  await expect(staff.getByText(address, { exact: true }).first()).toBeVisible();                       // 주문 정보 핵심 칸의 배송지 (출고 전)
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
  await page.getByRole("button", { name: "조회", exact: true }).click();
  await expect(page.getByText("추가 안내 예정", { exact: true })).toBeVisible();          // 문의 카드의 상태
  await expect(page.getByText("추가 안내 예정 1")).toBeVisible();                          // 위쪽 요약 띠
  await expect(page.getByText("공급사 재입고 일정")).toHaveCount(0);                     // 상담원 공유 메모는 고객에게 안 보임
});

test("파손 문의는 송장·파손 부위 사진 두 장이 있어야 등록 (없으면 '지금은 사진이 없어요')", async ({ page }) => {
  // 파손은 어느 주문인지 알아야 확인할 수 있으므로 주문번호를 함께 적음
  const png = { name: "photo.png", mimeType: "image/png", buffer: Buffer.from("89504e470d0a1a0a" + "00".repeat(64), "hex") };
  const fill = async (title: string, email = `e2e-damage-${Date.now()}@example.com`) => {
    await page.goto("/inquiry");
    await page.getByLabel("이름").fill("테스트 고객");
    await page.getByLabel(/^이메일/).fill(email);
    await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
    await page.getByLabel("비밀번호 확인").fill(LOOKUP_PASSWORD);
    await page.getByLabel("제목").fill(title);
    await page.getByLabel(/문의 내용/).fill("주문한 머그컵이 깨져서 왔어요. 교환 부탁드려요. (주문번호 20261110-0001)");
    await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
  };

  await fill("머그컵 파손 (자동 테스트)");
  await expect(page.getByLabel(/상품이 파손·불량이거나 잘못 왔어요/)).toBeChecked();         // 내용을 보고 자동 체크
  await expect(page.getByText("송장 사진", { exact: false }).first()).toBeVisible();          // → 사진 두 칸
  await page.getByRole("button", { name: "문의 등록" }).click();
  await expect(page.getByText(/송장 · 파손 부위 사진이 필요해요/)).toBeVisible();              // 사진 없이는 등록 안 됨
  await page.getByLabel("송장 사진 올리기").setInputFiles(png);
  await page.getByLabel("파손 부위 사진 올리기").setInputFiles(png);
  await expect(page.getByAltText("파손 부위 사진")).toBeVisible();
  await page.getByRole("button", { name: "문의 등록" }).click();
  await expect(page.getByText("문의가 등록되었습니다")).toBeVisible();

  const email = `e2e-damage-later-${Date.now()}@example.com`;
  await fill("머그컵 파손 사진 없음 (자동 테스트)", email);
  await page.getByLabel(/지금은 사진이 없어요/).check();
  await page.getByRole("button", { name: "문의 등록" }).click();
  await expect(page.getByText("문의가 등록되었습니다")).toBeVisible();
  await expect(page.getByText(/\[내용 보충 · 추가 문의\]로 보내 주세요/)).toBeVisible();

  // 문의 조회 → [내용 보충 · 추가 문의]: 사진 안내 + (처음 문의에 주문번호가 없으니) 주문번호 칸
  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByRole("button", { name: "조회", exact: true }).click();
  await page.getByRole("button", { name: "내용 보충 · 추가 문의" }).click();
  await expect(page.getByText(/송장이 보이는 사진 1장/)).toBeVisible();
  await page.getByPlaceholder(/빠뜨린 내용/).fill("주문번호 보내 드려요");
  await page.getByLabel(/주문번호/).fill("202611100001");
  await page.getByRole("button", { name: "보내기", exact: true }).click();
  await expect(page.getByText(/추가 문의가 접수되었습니다/)).toBeVisible();
  await expect(page.getByText(/주문번호 추가: 20261110-0001/)).toBeVisible();   // 대화에 남음
});

test("일반 질문이면 파손 체크를 풀고 사진 없이 등록", async ({ page }) => {
  await createInquiryStart(page, "파손 교환 규정 (자동 테스트)", "택배 상자가 파손되어 오면 교환되나요? 미리 알고 싶어요.");
  const damage = page.getByLabel(/상품이 파손·불량이거나 잘못 왔어요/);
  await expect(damage).toBeChecked();                                                     // '파손' 표현으로 자동 체크
  await damage.uncheck();                                                                 // 일반 질문이라 풂
  await expect(page.getByLabel("송장 사진 올리기")).toHaveCount(0);                           // 사진 두 칸이 닫힘
  await page.getByRole("button", { name: "문의 등록" }).click();
  await expect(page.getByText("문의가 등록되었습니다")).toBeVisible();
});

test("비회원 문의 표시 · 주문번호 형식이 틀리면 안내하고 등록하지 않음", async ({ page }) => {
  await page.goto("/inquiry");
  await expect(page.getByRole("heading", { name: "1:1 문의하기 비회원" })).toBeVisible();   // 제목 옆 '비회원' 표시
  await expect(page.getByRole("banner").getByRole("link", { name: "로그인", exact: true })).toBeVisible();   // 오른쪽 위 로그인 버튼
  await page.getByLabel(/주문번호/).fill("20261120-022");                          // 뒤가 3자리
  await expect(page.getByText(/숫자 8자리-4자리예요/)).toBeVisible();
  await page.getByLabel(/주문번호/).fill("202611200022");                          // 12자리 숫자는 칸을 벗어나면 8-4 로
  await expect(page.getByText(/숫자 8자리-4자리예요/)).toHaveCount(0);
  await page.getByLabel("제목").click();
  await expect(page.getByLabel(/주문번호/)).toHaveValue("20261120-0022");
});

test("상담원 공유 메모는 고객 대화와 따로, 오른쪽 카드에 남고 [크게 보기]로 넓게 봄", async ({ page }) => {
  const number = await createInquiry(page, `e2e-memo-${Date.now()}@example.com`, "쿠폰 사용 문의 (자동 테스트)", "쿠폰은 할인 상품에도 쓸 수 있나요?");
  await staffLogin(page, "admin");
  await page.getByLabel("문의 검색").focus();
  await page.keyboard.type(number);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "쿠폰 사용 문의 (자동 테스트)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "상담원 공유 메모" })).toHaveCount(0);      // 답변 칸에 메모 탭이 없음

  const notes = page.getByRole("region", { name: "상담원 공유 메모" });
  await notes.getByRole("button", { name: "+ 메모 남기기" }).click();
  await notes.getByLabel("상담원 공유 메모 내용").fill("쿠폰 조건 운영팀에 확인 중 (자동 테스트)");
  await notes.getByRole("button", { name: "메모 남기기" }).click();
  await expect(notes.getByText("쿠폰 조건 운영팀에 확인 중 (자동 테스트)")).toBeVisible();
  await expect(page.getByText("쿠폰 조건 운영팀에 확인 중 (자동 테스트)")).toHaveCount(1);   // 대화에는 섞이지 않음

  // [크게 보기] → 옆 패널에서 전체 메모, Esc 로 닫힘 (새 창 대신)
  await notes.getByRole("button", { name: "크게 보기" }).click();
  const wide = page.getByRole("dialog", { name: "상담원 공유 메모 크게 보기" });
  await expect(wide.getByText("쿠폰 조건 운영팀에 확인 중 (자동 테스트)")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(wide).toHaveCount(0);
});

test("조회 비밀번호가 틀리면 문의가 보이지 않음", async ({ page }) => {
  const email = `e2e-wrong-${Date.now()}@example.com`;
  await createInquiry(page, email, "적립금 문의 (자동 테스트)", "적립금은 언제 들어오나요? 확인 부탁드려요.");

  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill("wrong-password-9");
  await page.getByRole("button", { name: "조회", exact: true }).click();
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

test("답변 없이 완료할 때 사유를 고름 → 고객 조회에 '종료됨'과 안내", async ({ page }) => {
  const email = `e2e-close-${Date.now()}@example.com`;
  const number = await createInquiry(page, email, "같은 내용 다시 문의 (자동 테스트)", "어제 남긴 문의와 같은 내용이에요. 반품 접수는 어디서 하나요?");

  await staffLogin(page, "admin");
  await page.getByLabel("문의 검색").focus();
  await page.keyboard.type(number);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/inquiries\/\d+$/);
  await page.getByRole("button", { name: "완료 처리" }).click();
  const dialog = page.getByRole("dialog", { name: "답변 없이 완료 처리" });
  await expect(dialog.getByRole("button", { name: "완료 처리" })).toBeDisabled();   // 사유를 골라야 누를 수 있음
  await dialog.getByLabel("중복 문의").check();
  await dialog.getByRole("button", { name: "완료 처리" }).click();
  await expect(page.getByRole("button", { name: "다시 열기" })).toBeVisible();      // 완료됨 (사유는 처리 이력에 남음)

  await page.context().clearCookies();
  await page.goto("/inquiry/lookup");
  await page.getByLabel("문의할 때 쓴 이메일").fill(email);
  await page.getByLabel("조회 비밀번호").fill(LOOKUP_PASSWORD);
  await page.getByRole("button", { name: "조회", exact: true }).click();
  await expect(page.getByText("종료됨 1")).toBeVisible();
  await expect(page.getByText(/답변 없이 종료되었어요/)).toBeVisible();
});

test("조회 메뉴: 취소·교환·반품(환불 진행) · 주문·배송 · 고객 조회 · 재고 현황", async ({ page }) => {
  const shots = process.env.E2E_SHOTS;   // 화면 확인용 캡처 폴더 (없으면 캡처하지 않음)
  await staffLogin(page, "admin");

  // 취소·교환·반품: 승인 대기 탭이 기본, 승인 탭에는 앞 테스트에서 승인한 취소 요청
  await page.getByRole("link", { name: "취소·교환·반품" }).click();
  await expect(page.getByRole("heading", { name: "취소·교환·반품" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /승인 대기/ })).toHaveAttribute("aria-selected", "true");
  const approved = page.getByRole("tab", { name: /^승인\s*\d+$/ });
  await approved.click();
  await expect(approved).toHaveAttribute("aria-selected", "true");
  // 앞 테스트에서 승인한 취소 요청이 있으면 줄이, 없으면(이 테스트만 돌릴 때) 빈 안내가 보임
  await expect(page.locator("tbody tr").first().or(page.getByText("이 조건의 요청이 없어요."))).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/tickets.png`, fullPage: true });
  // 환불 진행: 승인 뒤 환불 예정·완료 (위쪽 요약 + 상태 버튼)
  await page.getByRole("tab", { name: /환불 진행/ }).click();
  await expect(page.getByText("예정일 지남").first()).toBeVisible();
  await page.getByRole("button", { name: "전체", exact: true }).click();
  await expect(page.locator("tbody tr").first().or(page.getByText("이 조건의 환불 내역이 없어요."))).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/refunds.png`, fullPage: true });

  // 주문·배송: 주문부터 찾기 → 줄을 누르면 결제·배송이 바로 아래에 펼쳐짐
  await page.getByRole("link", { name: "주문·배송" }).click();
  await expect(page.getByRole("heading", { name: "주문·배송" })).toBeVisible();
  await page.getByRole("tab", { name: /배송 완료/ }).click();
  // 탭 조건이 목록에 적용됨 (빨리 눌러도 앞 요청 결과가 덮어쓰지 않음)
  await expect(page.locator("tbody tr").first()).toContainText("배송 완료");
  await expect(page.locator("tbody tr").filter({ hasText: "상품 준비 중" })).toHaveCount(0);
  await page.locator("tbody tr").first().click();
  await expect(page.getByText("이 주문의 문의", { exact: false })).toBeVisible();
  await expect(page.getByText("고객 정보 전체 보기 →")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/orders.png`, fullPage: true });

  // 고객 조회: 이메일로 찾기 → 한 명 열기 → 주문·문의가 한 화면에
  await page.getByRole("link", { name: "고객 조회" }).click();
  await page.getByLabel("고객 검색").fill("customer08@example.com");
  await page.getByRole("button", { name: "찾기" }).click();
  await expect(page.getByText("총 1명")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/customers.png`, fullPage: true });
  await page.locator("tbody tr").first().click();
  await expect(page).toHaveURL(/\/admin\/customers\/\d+$/);
  await expect(page.getByRole("heading", { name: /주문 \d+건/ })).toBeVisible();
  await expect(page.getByText("쓸 수 있는 쿠폰")).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/customer.png`, fullPage: true });

  // 재고 현황: 품절 탭
  await page.getByRole("link", { name: "재고 현황" }).click();
  await page.getByRole("tab", { name: /품절/ }).click();
  await expect(page.locator("tbody tr").filter({ hasText: /품절/ }).first()).toBeVisible();   // 품절 옵션 줄
  if (shots) await page.screenshot({ path: `${shots}/inventory.png`, fullPage: true });
});

test("비밀번호 확인이 다르면 입력하는 동안 칸 아래에 바로 알려 줌", async ({ page }) => {
  await page.goto("/inquiry");
  await page.getByLabel("조회 비밀번호").fill("abc12345");
  await page.getByLabel("비밀번호 확인").fill("abc1234");
  await expect(page.getByText("위 비밀번호와 달라요.")).toBeVisible();
  await page.getByLabel("비밀번호 확인").fill("abc12345");
  await expect(page.getByText("위 비밀번호와 달라요.")).toHaveCount(0);
});

test("단순 변심 교환 배송비: 상담원이 결제 요청 → 고객이 내 쇼핑에서 결제 → 상담원 화면에 '받음'", async ({ page, browser }) => {
  // 고객(customer14: 시험 데이터에서 방금 배송 완료된 주문이 있음): 배송 완료 주문으로 사이즈 교환 문의
  await page.goto("/shop/login");
  await page.getByLabel("이메일").fill("customer14@example.com");
  await page.getByLabel("비밀번호").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).not.toHaveURL(/\/shop\/login/);
  await page.goto("/my");
  const order = page.locator("li").filter({ hasText: "배송 완료" }).filter({ has: page.getByRole("link", { name: "이 주문 문의하기" }) }).first();
  await order.getByRole("link", { name: "이 주문 문의하기" }).click();
  const title = `사이즈 교환 ${Date.now()} (자동 테스트)`;
  await page.getByLabel("제목").fill(title);
  await page.getByLabel(/문의 내용/).fill("받았는데 생각보다 작아요. 한 치수 큰 걸로 교환하고 싶어요.");
  await page.getByLabel(/개인정보 수집·이용에 동의합니다/).check();
  await page.getByRole("button", { name: "문의 등록" }).click();
  const number = (await page.getByText(/^INQ-\d{8}-\d{4}$/).textContent())!.trim();

  // 상담원: 주문 정보의 바로 처리 [교환 배송비 받기] → [결제 요청 보내기]
  const staff = await (await browser.newContext({ baseURL: "http://127.0.0.1:5174", locale: "ko-KR" })).newPage();
  await staffLogin(staff, "admin");
  await staff.getByLabel("문의 검색").fill(number);
  await staff.keyboard.press("Enter");
  await expect(staff.getByRole("heading", { name: title })).toBeVisible();
  await staff.getByRole("button", { name: "교환 배송비 받기" }).first().click();
  await staff.getByRole("button", { name: "결제 요청 보내기" }).click();
  await staff.getByRole("alertdialog").getByRole("button", { name: "받기" }).click();
  await expect(staff.getByText(/교환 배송비 6,000원: 고객 결제 대기/).first()).toBeVisible();
  if (process.env.E2E_SHOTS) await staff.screenshot({ path: `${process.env.E2E_SHOTS}/exchange-fee-staff.png`, fullPage: true });

  // 고객: 내 쇼핑의 내 문의에 결제 칸 → 신용카드로 결제
  await page.goto("/my");
  const mine = page.locator("section").filter({ hasText: title });
  await expect(mine.getByText("교환 배송비 6,000원 결제가 필요해요")).toBeVisible();
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/exchange-fee-customer.png`, fullPage: true });
  await mine.getByRole("button", { name: "신용카드로 결제" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "결제하기" }).click();
  await expect(mine.getByText(/교환 배송비 6,000원 결제 완료 \(신용카드\)/)).toBeVisible();

  // 상담원: 다시 불러오면 '받음'
  await staff.reload();
  await expect(staff.getByText(/교환 배송비 6,000원 받음 \(신용카드\)/).first()).toBeVisible();
  if (process.env.E2E_SHOTS) await staff.screenshot({ path: `${process.env.E2E_SHOTS}/exchange-fee-paid.png`, fullPage: true });
});
