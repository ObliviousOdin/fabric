import { describe, expect, it } from "vitest";

import {
  LinkControllerWebStore,
  LinkControllerWebStoreCorrupt,
  LinkControllerWebStoreUnavailable,
} from "./link-controller-store";

describe("LinkControllerWebStore", () => {
  it("rejects invalid controller identifiers before touching browser storage", async () => {
    await expect(new LinkControllerWebStore().load("../controller")).rejects.toBeInstanceOf(
      LinkControllerWebStoreCorrupt,
    );
  });

  it("refuses to fall back when secure browser storage is unavailable", async () => {
    await expect(new LinkControllerWebStore().load("controller-1")).rejects.toBeInstanceOf(
      LinkControllerWebStoreUnavailable,
    );
  });

  it("rejects an empty opaque state before it can be persisted", async () => {
    await expect(
      new LinkControllerWebStore().store("controller-1", new Uint8Array()),
    ).rejects.toBeInstanceOf(LinkControllerWebStoreCorrupt);
  });
});
