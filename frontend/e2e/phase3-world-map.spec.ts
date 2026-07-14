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
  const portrait = page
    .getByRole("article", { name: `角色 ${name}` })
    .getByRole("img", { name: `${name} 默认立绘` });
  await expect(portrait).toHaveJSProperty("complete", true);
  expect(
    await portrait.evaluate((node: HTMLImageElement) => node.naturalWidth),
  ).toBeGreaterThan(0);
  expect(
    await portrait.evaluate((node: HTMLImageElement) => node.naturalHeight),
  ).toBeGreaterThan(0);
  expect(
    await portrait.evaluate(
      (node: HTMLImageElement) => getComputedStyle(node).objectFit,
    ),
  ).toBe("contain");
}

async function addNpc(page: Page, name: string): Promise<void> {
  await page.getByLabel("选择 NPC").selectOption({ label: name });
  await page.getByRole("button", { name: "加入 NPC" }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
}

async function configureNpcLocation(page: Page, name: string): Promise<void> {
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

async function enterSelectedLocation(page: Page): Promise<void> {
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "地图" })).toBeVisible();
}

async function returnToWorldMap(page: Page): Promise<void> {
  await page.getByRole("button", { name: "地图" }).click();
  await expect(page.getByRole("button", { name: "地图" })).toHaveCount(0);
  await expect(page.getByLabel("游戏地图")).toHaveAttribute(
    "aria-busy",
    "false",
  );
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

test("completes the phase 3 world, role, and map flow in a real browser", async ({
  page,
}) => {
  test.setTimeout(120_000);

  await test.step("create all three global roles and attributes through the UI", async () => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "还没有世界" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "角色库" }).click();
    await createRole(page, "天", "谨慎的冒险者", { level: 1, money: 50 });
    await createRole(page, "莫莉莉", "开朗的学生", { level: 2, money: 100 });
    await createRole(page, "安可儿", "温柔的冒险者", { level: 3, money: 80 });
  });

  const worldId =
    await test.step("create a world by referencing the existing protagonist", async () => {
      await page.getByRole("link", { name: "返回世界" }).click();
      await page.getByRole("button", { name: "创建世界" }).click();
      await expect(page.getByLabel("世界名称", { exact: true })).toHaveCount(0);
      await expect(page.getByLabel("星期", { exact: true })).toHaveCount(0);
      await expect(page.getByLabel("基础人设", { exact: true })).toHaveCount(0);
      await page.getByLabel("主角角色").selectOption({ label: "天" });
      await expect(
        page.getByRole("region", { name: "已选主角 天" }),
      ).toContainText("谨慎的冒险者");
      const createResponse = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === "/api/worlds",
      );
      await page.getByRole("button", { name: "确认创建" }).click();
      const response = await createResponse;
      expect(response.status()).toBe(201);
      expect(response.request().postDataJSON()).toEqual({
        protagonist_role_id: expect.any(Number),
      });
      await expect(page).toHaveURL(/\/worlds\/\d+\/roles$/);
      const matched = new URL(page.url()).pathname.match(
        /^\/worlds\/(\d+)\/roles$/,
      )?.[1];
      if (!matched) throw new Error("world id missing from role page URL");
      return matched;
    });

  await test.step("keep the protagonist read-only and protect the referenced role", async () => {
    const playerCard = page.getByRole("article").filter({ hasText: "天" });
    await expect(playerCard).toContainText("主角");
    await expect(playerCard).toContainText("等级 1");
    await expect(playerCard).toContainText("金钱 50");
    await expect(playerCard.getByRole("button")).toHaveCount(0);

    await page.getByRole("link", { name: "全局角色库" }).click();
    const libraryPlayer = page.getByRole("article", { name: "角色 天" });
    await expect(libraryPlayer).toContainText(
      `该角色仍被世界 ${worldId} 引用，不能删除。`,
    );
    await expect(
      libraryPlayer.getByRole("button", { name: "删除角色 天" }),
    ).toBeDisabled();
    await page.getByRole("link", { name: "返回世界" }).click();
    const worldCard = page
      .getByRole("article")
      .filter({ hasText: `世界 ${worldId}` });
    await worldCard.getByRole("link", { name: "管理角色" }).click();
  });

  await test.step("add, toggle, remove, re-add, and configure NPCs", async () => {
    await addNpc(page, "莫莉莉");
    await addNpc(page, "安可儿");
    const ankerCard = page.getByRole("article").filter({ hasText: "安可儿" });
    await ankerCard.getByRole("button", { name: "停用 NPC 安可儿" }).click();
    await expect(ankerCard).toContainText("已停用");
    await ankerCard.getByRole("button", { name: "启用 NPC 安可儿" }).click();
    await expect(ankerCard).toContainText("已启用");
    await ankerCard.getByRole("button", { name: "移除 NPC 安可儿" }).click();
    await ankerCard.getByRole("button", { name: "确认移除 安可儿" }).click();
    await expect(
      page.getByRole("heading", { name: "安可儿", exact: true }),
    ).toHaveCount(0);
    await addNpc(page, "安可儿");
    await configureNpcLocation(page, "莫莉莉");
    await configureNpcLocation(page, "安可儿");
  });

  const canvas = page.locator("canvas");
  const time = page.getByLabel("世界时间");
  await test.step("enter a location with the keyboard and render real portraits", async () => {
    await page.getByRole("link", { name: "进入世界" }).click();
    await expect(canvas).toBeVisible();
    const canvasBox = await canvas.boundingBox();
    if (!canvasBox) throw new Error("Phaser canvas has no bounding box");
    expect(canvasBox.width / canvasBox.height).toBeCloseTo(16 / 9, 2);
    await expect(time).toHaveText("Day 1 · 星期一 · 晨间");

    await pressAndWaitForLocationSelection(page, "ArrowRight");
    await pressAndWaitForLocationSelection(page, "ArrowLeft");
    await pressAndWaitForLocationSelection(page, "ArrowRight");
    await enterSelectedLocation(page);

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
      expect(
        await image.evaluate(
          (node: HTMLImageElement) => getComputedStyle(node).objectFit,
        ),
      ).toBe("contain");
    }
  });

  await test.step("enter every location and return without advancing time", async () => {
    await returnToWorldMap(page);
    await pressAndWaitForLocationSelection(page, "ArrowLeft");
    for (let index = 0; index < 6; index += 1) {
      if (index > 0) await pressAndWaitForLocationSelection(page, "ArrowRight");
      await enterSelectedLocation(page);
      await expect(time).toHaveText("Day 1 · 星期一 · 晨间");
      await returnToWorldMap(page);
    }
  });

  await test.step("select and enter a location with the mouse", async () => {
    const worldMapBeforePointer = await canvas.screenshot();
    const canvasBox = await canvas.boundingBox();
    if (!canvasBox) throw new Error("Phaser canvas has no bounding box");
    const dungeon = {
      x: canvasBox.x + canvasBox.width * 0.3,
      y: canvasBox.y + canvasBox.height * 0.55,
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

  await test.step("delete the world while keeping every global role", async () => {
    await page.goto("/");
    const worldCard = page
      .getByRole("article")
      .filter({ hasText: `世界 ${worldId}` });
    await worldCard
      .getByRole("button", { name: `删除世界 世界 ${worldId}` })
      .click();
    await worldCard
      .getByRole("button", { name: `确认删除 世界 ${worldId}` })
      .click();
    await expect(
      page.getByRole("heading", { name: `世界 ${worldId}` }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "角色库" }).click();
    for (const name of ["天", "莫莉莉", "安可儿"]) {
      const roleCard = page.getByRole("article", { name: `角色 ${name}` });
      await expect(roleCard).toContainText("尚未被世界引用");
      await expect(
        roleCard.getByRole("button", { name: `删除角色 ${name}` }),
      ).toBeEnabled();
    }
  });
});
