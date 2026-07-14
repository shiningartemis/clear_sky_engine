import { expect, type Locator, type Page, test } from "@playwright/test";

interface AttributeValues {
  level: number;
  money: number;
}

const weekdayLabels: ReadonlyArray<string> = [
  "星期一",
  "星期二",
  "星期三",
  "星期四",
  "星期五",
  "星期六",
  "星期日",
];

async function fillAttribute(
  form: Locator,
  index: number,
  key: keyof AttributeValues,
  value: number,
): Promise<void> {
  await form.getByRole("button", { name: "添加属性" }).click();
  const fieldset = form.getByRole("group", { name: `属性 ${index + 1}` });
  await fieldset.getByLabel("属性 key").fill(key);
  await fieldset.getByLabel("显示名称").fill(key === "level" ? "等级" : "金钱");
  await fieldset.getByLabel("属性类型").selectOption("integer");
  await fieldset.getByLabel("基础值").fill(String(value));
  await fieldset
    .getByLabel("属性说明")
    .fill(key === "level" ? "角色当前等级" : "角色持有金钱");
  await fieldset
    .getByLabel("更新规则")
    .fill(key === "level" ? "仅在明确升级或降级时更新" : "仅在明确收支时更新");
  await fieldset.getByLabel("允许增加").check();
  await fieldset.getByLabel("允许减少").check();
}

async function configureAttributes(
  form: Locator,
  attributes: AttributeValues,
): Promise<void> {
  await fillAttribute(form, 0, "level", attributes.level);
  await fillAttribute(form, 1, "money", attributes.money);
}

async function createRole(
  page: Page,
  name: string,
  persona: string,
  attributes: AttributeValues,
): Promise<void> {
  await page.getByRole("button", { name: "创建角色" }).click();
  const form = page.locator("form");
  await form.getByLabel("角色素材").selectOption(name);
  await form.getByLabel("基础人设").fill(persona);
  await configureAttributes(form, attributes);
  await form.getByRole("button", { name: "保存角色" }).click();
  await expect(
    page.getByRole("article", { name: `角色 ${name}` }),
  ).toContainText("2 个属性");
}

async function configureProtagonist(
  page: Page,
  attributes: AttributeValues,
): Promise<void> {
  await page.getByRole("button", { name: "编辑角色 天" }).click();
  const form = page.locator("form");
  await configureAttributes(form, attributes);
  await form.getByRole("button", { name: "保存角色" }).click();
  await expect(page.getByRole("article", { name: "角色 天" })).toContainText(
    "2 个属性",
  );
}

async function addNpc(page: Page, name: string): Promise<void> {
  await page.getByLabel("选择 NPC").selectOption({ label: name });
  await page.getByRole("button", { name: "加入 NPC" }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();

  await page.getByRole("button", { name: `配置位置规则 ${name}` }).click();
  const editor = page.getByRole("region", { name: "位置规则编辑器" });
  const rule = editor.getByRole("group", { name: "规则 1" });
  await expect(rule.getByLabel("星期一")).toBeChecked();
  for (const weekday of weekdayLabels.slice(1)) {
    await expect(rule.getByLabel(weekday)).not.toBeChecked();
  }
  await rule.getByLabel("时间段").selectOption("morning");
  await rule.getByLabel("模式").selectOption("fixed");
  await rule
    .locator("label", { hasText: "候选地点 1" })
    .locator("select")
    .selectOption("the_dungeon");
  await editor.getByRole("button", { name: "保存全部位置规则" }).click();
  await expect(page.getByRole("status")).toContainText("位置规则已原子替换");
  await editor.getByRole("button", { name: "关闭" }).click();
}

async function pressAndWaitForLocationSelection(
  page: Page,
  key: "ArrowLeft" | "ArrowRight",
): Promise<void> {
  const response = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      /\/api\/worlds\/\d+\/location$/.test(new URL(candidate.url()).pathname),
  );
  await page.keyboard.press(key);
  expect((await response).ok()).toBe(true);
  await expect(page.getByLabel("游戏地图")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}

async function assertCanvasChanged(
  canvas: Locator,
  before: Buffer,
): Promise<Buffer> {
  let current = before;
  await expect
    .poll(async () => {
      current = await canvas.screenshot();
      return current.equals(before);
    })
    .toBe(false);
  return current;
}

test.use({ viewport: { width: 1280, height: 720 } });

test("configures roles and renders three real portraits on a location map", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("link", { name: "角色库" }).click();
  await createRole(page, "莫莉莉", "开朗的学生", { level: 2, money: 100 });
  await createRole(page, "安可儿", "温柔的冒险者", { level: 3, money: 80 });

  await page.getByRole("link", { name: "返回世界" }).click();
  await page.getByRole("button", { name: "创建世界" }).click();
  await expect(page.getByLabel("世界名称", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("星期", { exact: true })).toHaveCount(0);
  await page.getByLabel("主角名称").selectOption("天");
  await page.getByLabel("基础人设").fill("谨慎的主角");
  await page.getByRole("button", { name: "确认创建" }).click();
  await expect(page).toHaveURL(/\/worlds\/\d+\/roles$/);
  const worldUrl = new URL(page.url());
  const worldId = worldUrl.pathname.match(/^\/worlds\/(\d+)\/roles$/)?.[1];
  expect(worldId).toBeTruthy();

  await page.getByRole("link", { name: "全局角色库" }).click();
  await configureProtagonist(page, { level: 1, money: 50 });
  await page.getByRole("link", { name: "返回世界" }).click();
  const worldCard = page
    .getByRole("article")
    .filter({ hasText: `世界 ${worldId}` });
  await worldCard.getByRole("link", { name: "管理角色" }).click();

  await addNpc(page, "莫莉莉");
  await addNpc(page, "安可儿");
  await expect(
    page.getByRole("region", { name: "世界角色列表" }),
  ).toContainText("等级 1");
  await page.getByRole("link", { name: "进入世界" }).click();

  const canvas = page.locator("canvas");
  await expect(canvas).toBeVisible();
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).not.toBeNull();
  if (!canvasBox) throw new Error("Phaser canvas has no bounding box");
  expect(canvasBox.width / canvasBox.height).toBeCloseTo(16 / 9, 2);

  await pressAndWaitForLocationSelection(page, "ArrowRight");
  await pressAndWaitForLocationSelection(page, "ArrowLeft");
  await pressAndWaitForLocationSelection(page, "ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "地图" })).toBeVisible();

  const time = page.getByLabel("世界时间");
  await expect(time).toHaveText("Day 1 · 星期一 · 晨间");
  const timeBeforeMove = await time.textContent();
  const beforeMove = await canvas.screenshot();
  await page.keyboard.press("ArrowRight");
  await assertCanvasChanged(canvas, beforeMove);
  await expect(time).toHaveText(timeBeforeMove ?? "");

  const frames = page.getByTestId("portrait-frame");
  await expect(frames).toHaveCount(3);
  await expect(page.locator("figure figcaption")).toHaveText([
    "天",
    "莫莉莉",
    "安可儿",
  ]);
  for (const frame of await frames.all()) {
    const frameBox = await frame.boundingBox();
    expect(frameBox).not.toBeNull();
    if (!frameBox) throw new Error("Portrait frame has no bounding box");
    expect(Math.abs(frameBox.width - frameBox.height)).toBeLessThanOrEqual(1);
  }
  for (const image of await frames.getByRole("img").all()) {
    await expect(image).toHaveJSProperty("complete", true);
    expect(
      await image.evaluate((node: HTMLImageElement) => node.naturalWidth),
    ).toBeGreaterThan(0);
    expect(
      await image.evaluate((node: HTMLImageElement) => node.naturalHeight),
    ).toBeGreaterThan(0);
  }

  await page.getByRole("button", { name: "地图" }).click();
  await expect(page.getByRole("button", { name: "地图" })).toHaveCount(0);
  await expect(time).toHaveText("Day 1 · 星期一 · 晨间");
  await pressAndWaitForLocationSelection(page, "ArrowLeft");

  const worldMapBeforePointer = await canvas.screenshot();
  const currentCanvasBox = await canvas.boundingBox();
  if (!currentCanvasBox) throw new Error("Phaser canvas has no bounding box");
  const dungeon = {
    x: currentCanvasBox.x + currentCanvasBox.width * 0.3,
    y: currentCanvasBox.y + currentCanvasBox.height * 0.55,
  };
  const selectionResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      /\/api\/worlds\/\d+\/location$/.test(new URL(candidate.url()).pathname),
  );
  await page.mouse.click(dungeon.x, dungeon.y);
  expect((await selectionResponse).ok()).toBe(true);
  await assertCanvasChanged(canvas, worldMapBeforePointer);

  await page.mouse.click(dungeon.x, dungeon.y);
  await expect(page.getByRole("button", { name: "地图" })).toBeVisible();
  await expect(time).toHaveText("Day 1 · 星期一 · 晨间");
});
