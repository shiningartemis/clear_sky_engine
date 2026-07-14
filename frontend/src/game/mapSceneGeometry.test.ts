import { describe, expect, it } from "vitest";

import {
  calculateLocationOverlayGeometry,
  hitTestLocationOverlay,
} from "./mapSceneGeometry";
import { calculateCoverTransform } from "./types";

const image = { width: 1920, height: 1080 };
const anchor = { x: 0.5, y: 0.5 };

describe("location overlay geometry", () => {
  it("keeps the visible marker and label hittable on a small viewport", () => {
    const transform = calculateCoverTransform(1920, 1080, 320, 180);
    const geometry = calculateLocationOverlayGeometry(
      anchor,
      image,
      transform,
      320,
      180,
      "学校",
    );

    expect(geometry.viewportScale).toBe(0.5);
    expect(geometry.marker).toEqual({ x: 160, y: 90, radius: 8 });
    expect(geometry.label.y).toBe(119);
    expect(
      hitTestLocationOverlay(
        { x: geometry.marker.x + geometry.marker.radius - 0.1, y: 90 },
        geometry,
      ),
    ).toBe(true);
    expect(
      hitTestLocationOverlay(
        {
          x: geometry.label.x + geometry.label.width / 2 - 0.1,
          y: geometry.label.y,
        },
        geometry,
      ),
    ).toBe(true);
    expect(
      hitTestLocationOverlay(
        { x: geometry.label.x, y: geometry.label.y },
        geometry,
      ),
    ).toBe(true);
  });

  it("reprojects marker, label offset, and hit geometry with the same scale after resize", () => {
    const small = calculateLocationOverlayGeometry(
      anchor,
      image,
      calculateCoverTransform(1920, 1080, 320, 180),
      320,
      180,
      "学校",
    );
    const large = calculateLocationOverlayGeometry(
      anchor,
      image,
      calculateCoverTransform(1920, 1080, 1920, 1080),
      1920,
      1080,
      "学校",
    );

    expect(large.viewportScale).toBe(1);
    expect(large.marker).toEqual({ x: 960, y: 540, radius: 16 });
    expect(large.label.y - large.marker.y).toBe(58);
    expect(large.marker.radius / small.marker.radius).toBe(
      large.viewportScale / small.viewportScale,
    );
    expect(
      hitTestLocationOverlay({ x: large.label.x, y: large.label.y }, large),
    ).toBe(true);
    expect(hitTestLocationOverlay({ x: 0, y: 0 }, large)).toBe(false);
  });
});
