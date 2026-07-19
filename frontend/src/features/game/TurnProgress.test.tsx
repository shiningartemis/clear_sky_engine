import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TurnProgress } from "./TurnProgress";

describe("TurnProgress", () => {
  it("按地图展示节点、自动重试、完成数和总耗时", () => {
    render(
      <TurnProgress
        locations={[
          { sceneId: "the_home", displayName: "家", order: 0 },
          { sceneId: "the_school", displayName: "学校", order: 1 },
        ]}
        mapProgress={{
          the_home: {
            node: "location_simulation",
            attempt: 2,
            maxAttempts: 3,
            retrying: true,
            completed: false,
          },
          the_school: {
            node: "attribute_memory_analysis",
            attempt: 1,
            maxAttempts: 3,
            retrying: false,
            completed: true,
          },
        }}
        completedMaps={1}
        totalMaps={2}
        elapsedMs={1_250}
        isCancelling={false}
        cancelError={null}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/家 · 地点推演 · 尝试 2\/3/)).toHaveTextContent(
      "自动重试",
    );
    expect(
      screen.getByText(/学校 · 属性与记忆分析 · 尝试 1\/3/),
    ).toHaveTextContent("已完成");
    expect(
      screen.getByText("已完成 1/2 张地图 · 总耗时 1.3 秒"),
    ).toBeInTheDocument();
  });

  it("提供明确的等待、取消中和取消失败状态", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { rerender } = render(
      <TurnProgress
        locations={[]}
        mapProgress={{}}
        completedMaps={0}
        totalMaps={0}
        elapsedMs={0}
        isCancelling={false}
        cancelError={null}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByText("正在准备轮次节点…")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "取消轮次" }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(
      <TurnProgress
        locations={[]}
        mapProgress={{}}
        completedMaps={0}
        totalMaps={0}
        elapsedMs={0}
        isCancelling
        cancelError="取消请求失败，请重试。"
        onCancel={onCancel}
      />,
    );
    expect(screen.getByRole("button", { name: "正在取消…" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "取消请求失败，请重试。",
    );
  });
});
