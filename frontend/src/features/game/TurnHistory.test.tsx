import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TurnResponse } from "../../api/turns";
import type { WorldRoleResponse } from "../../api/worlds";
import { TurnHistory } from "./TurnHistory";

const roles: WorldRoleResponse[] = [
  {
    world_id: 4,
    role_id: 10,
    name: "莫莉莉",
    kind: "npc",
    enabled: true,
    effective_attributes: {},
    portrait_url: "/portraits/moli.png",
    version: 1,
    updated_at: "2026-07-18T00:00:00Z",
  },
  {
    world_id: 4,
    role_id: 9,
    name: "天",
    kind: "player",
    enabled: true,
    effective_attributes: {},
    portrait_url: "/portraits/player.png",
    version: 1,
    updated_at: "2026-07-18T00:00:00Z",
  },
  {
    world_id: 4,
    role_id: 11,
    name: "安可儿",
    kind: "npc",
    enabled: true,
    effective_attributes: {},
    portrait_url: "/portraits/anko.png",
    version: 1,
    updated_at: "2026-07-18T00:00:00Z",
  },
];

function turn(turnId: number): TurnResponse {
  return {
    turn_id: turnId,
    day: 1,
    time_slot: "midday",
    player_intent: `第 ${turnId} 轮意图`,
    roles: [
      { role_id: 10, content: "莫莉莉看向窗外。", offline: false },
      { role_id: 11, content: "不得显示这段离屏模型文本。", offline: true },
      { role_id: 9, content: "天推开教室门。", offline: false },
    ],
    events: [
      {
        event_id: turnId,
        location_id: "the_school",
        event_type: "arrival",
        fact: { summary: "天抵达学校" },
      },
    ],
    state_changes: [
      {
        role_id: 9,
        attribute_key: "energy",
        operation: "decrement",
        old_value: 10,
        operand: 1,
        new_value: 9,
        reason: "步行消耗",
      },
    ],
  };
}

describe("TurnHistory", () => {
  it("最新轮展开、旧轮折叠，并按固定顺序展示完整角色纪事", () => {
    render(
      <TurnHistory
        status="ready"
        turns={[turn(2), turn(1)]}
        worldRoles={roles}
        error={null}
        onRetry={vi.fn()}
        scrollToTurnId={null}
      />,
    );

    const cards = screen.getAllByTestId("turn-card");
    expect(cards[0]).toHaveAttribute("open");
    expect(cards[1]).not.toHaveAttribute("open");
    const headings = within(cards[0])
      .getAllByRole("heading")
      .map((node) => node.textContent);
    expect(headings).toEqual([
      "主角独立纪事 · 天",
      "其他角色独立纪事 · 莫莉莉",
      "其他角色独立纪事 · 安可儿",
      "客观事件",
      "属性变化",
    ]);
    expect(
      within(cards[0]).getByText("该角色本轮处于离屏状态，未生成独立纪事。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("不得显示这段离屏模型文本。"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /筛选|分页|快照|分支/ }),
    ).not.toBeInTheDocument();
  });

  it("显示 loading、empty、error 和 retry 状态", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(
      <TurnHistory
        status="loading"
        turns={[]}
        worldRoles={[]}
        error={null}
        onRetry={onRetry}
        scrollToTurnId={null}
      />,
    );
    expect(screen.getByText("正在加载历轮故事…")).toBeInTheDocument();

    rerender(
      <TurnHistory
        status="ready"
        turns={[]}
        worldRoles={[]}
        error={null}
        onRetry={onRetry}
        scrollToTurnId={null}
      />,
    );
    expect(screen.getByText("还没有成功轮次")).toBeInTheDocument();

    rerender(
      <TurnHistory
        status="error"
        turns={[]}
        worldRoles={[]}
        error="无法加载历轮故事。"
        onRetry={onRetry}
        scrollToTurnId={null}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("无法加载历轮故事。");
    await user.click(screen.getByRole("button", { name: "重试加载历轮故事" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("已有轮次时 loading/error 只作为附加状态，并在卡片出现后滚动", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const { rerender } = render(
      <TurnHistory
        status="loading"
        turns={[]}
        worldRoles={roles}
        error={null}
        onRetry={onRetry}
        scrollToTurnId={2}
      />,
    );
    expect(scrollIntoView).not.toHaveBeenCalled();

    rerender(
      <TurnHistory
        status="loading"
        turns={[turn(2)]}
        worldRoles={roles}
        error={null}
        onRetry={onRetry}
        scrollToTurnId={2}
      />,
    );
    expect(screen.getByTestId("turn-card")).toBeInTheDocument();
    expect(screen.getByText("正在加载历轮故事…")).toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    rerender(
      <TurnHistory
        status="error"
        turns={[turn(2)]}
        worldRoles={roles}
        error="无法加载历轮故事。"
        onRetry={onRetry}
        scrollToTurnId={2}
      />,
    );
    expect(screen.getByTestId("turn-card")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("无法加载历轮故事。");
    await user.click(screen.getByRole("button", { name: "重试加载历轮故事" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
