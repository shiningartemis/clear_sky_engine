import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorldRoleResponse } from "../../api/worlds";
import styles from "./GamePage.module.css";
import { PortraitStrip } from "./PortraitStrip";

function role(
  roleId: number,
  kind: WorldRoleResponse["kind"],
  portraitUrl: string,
): WorldRoleResponse {
  return {
    world_id: 4,
    role_id: roleId,
    name: `角色 ${roleId}`,
    kind,
    enabled: true,
    effective_attributes: {},
    portrait_url: portraitUrl,
    version: 1,
    updated_at: "2026-07-14T00:00:00Z",
  };
}

function visibleRoles(): WorldRoleResponse[] {
  return [
    role(8, "npc", "/portraits/wide.jpg"),
    role(9, "player", "/portraits/tall.png"),
    role(3, "npc", "/portraits/square.webp"),
  ];
}

describe("PortraitStrip", () => {
  it("renders different aspect ratios inside square contain frames", () => {
    render(<PortraitStrip roles={visibleRoles()} viewportWidth={1440} />);

    const frames = screen.getAllByTestId("portrait-frame");
    expect(frames).toHaveLength(3);
    for (const frame of frames) {
      expect(frame).toHaveStyle({ aspectRatio: "1 / 1" });
    }
    for (const image of screen.getAllByRole("img")) {
      expect(image).toHaveClass(styles.portraitImage);
    }
  });

  it("orders the player first and NPCs by stable role ID", () => {
    render(<PortraitStrip roles={visibleRoles()} viewportWidth={1440} />);

    expect(
      screen.getAllByRole("img").map((image) => image.getAttribute("alt")),
    ).toEqual(["角色 9", "角色 3", "角色 8"]);
  });

  it("renders at most six backend-provided roles", () => {
    const roles = [role(10, "player", "/10.png")];
    for (let roleId = 1; roleId <= 7; roleId += 1) {
      roles.push(role(roleId, "npc", `/${roleId}.png`));
    }

    render(<PortraitStrip roles={roles} viewportWidth={1800} />);

    expect(screen.getAllByRole("img")).toHaveLength(6);
  });

  it("shows a resize warning when frames would be narrower than 128 pixels", () => {
    render(<PortraitStrip roles={visibleRoles()} viewportWidth={450} />);

    expect(screen.getByRole("status")).toHaveTextContent("请加宽窗口");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows role-specific error text when a portrait cannot load", () => {
    render(
      <PortraitStrip
        roles={[role(4, "player", "/broken.png")]}
        viewportWidth={800}
      />,
    );

    fireEvent.error(screen.getByRole("img", { name: "角色 4" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "角色 4 的立绘无法显示",
    );
  });

  it("passes GIF URLs through unchanged", () => {
    render(
      <PortraitStrip
        roles={[role(4, "player", "/portraits/角色.gif")]}
        viewportWidth={800}
      />,
    );

    expect(screen.getByRole("img", { name: "角色 4" })).toHaveAttribute(
      "src",
      "/portraits/角色.gif",
    );
  });
});
