// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";

interface Row {
  name: string;
  tokens: number | null;
}

const ROWS: Row[] = [
  { name: "alpha", tokens: 50 },
  { name: "bravo", tokens: null },
  { name: "charlie", tokens: 200 },
];

const COLUMNS: DataTableColumn<Row>[] = [
  { key: "name", header: "Name", sortable: true },
  { key: "tokens", header: "Tokens", sortable: true, align: "right", mono: true },
];

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function columnTexts(container: HTMLElement, colIndex: number): string[] {
  return Array.from(container.querySelectorAll("tbody tr")).map(
    (tr) => tr.children[colIndex]?.textContent ?? "",
  );
}

function headerButton(container: HTMLElement, label: string): HTMLButtonElement {
  const button = Array.from(
    container.querySelectorAll<HTMLButtonElement>("thead button"),
  ).find((b) => b.textContent?.includes(label));
  if (!button) throw new Error(`no sortable header labeled ${label}`);
  return button;
}

describe("DataTable", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it("applies the default sort descending with nulls last", async () => {
    await act(async () => {
      root.render(
        <DataTable
          columns={COLUMNS}
          rows={ROWS}
          rowKey={(r) => r.name}
          defaultSortKey="tokens"
        />,
      );
    });

    expect(columnTexts(container, 0)).toEqual(["charlie", "alpha", "bravo"]);
    const tokensTh = container.querySelectorAll("th")[1];
    expect(tokensTh.getAttribute("aria-sort")).toBe("descending");
  });

  it("flips direction when the active header is clicked again, keeping nulls last", async () => {
    await act(async () => {
      root.render(
        <DataTable
          columns={COLUMNS}
          rows={ROWS}
          rowKey={(r) => r.name}
          defaultSortKey="tokens"
        />,
      );
    });

    await act(async () => headerButton(container, "Tokens").click());

    expect(columnTexts(container, 0)).toEqual(["alpha", "charlie", "bravo"]);
    expect(
      container.querySelectorAll("th")[1].getAttribute("aria-sort"),
    ).toBe("ascending");
  });

  it("switching to another column resets the direction to descending", async () => {
    await act(async () => {
      root.render(
        <DataTable
          columns={COLUMNS}
          rows={ROWS}
          rowKey={(r) => r.name}
          defaultSortKey="tokens"
        />,
      );
    });

    // Flip tokens to ascending first so the reset is observable.
    await act(async () => headerButton(container, "Tokens").click());
    await act(async () => headerButton(container, "Name").click());

    expect(columnTexts(container, 0)).toEqual(["charlie", "bravo", "alpha"]);
    const [nameTh, tokensTh] = Array.from(container.querySelectorAll("th"));
    expect(nameTh.getAttribute("aria-sort")).toBe("descending");
    expect(tokensTh.getAttribute("aria-sort")).toBeNull();
  });

  it("preserves the given row order until a sort key is chosen", async () => {
    await act(async () => {
      root.render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.name} />);
    });

    expect(columnTexts(container, 0)).toEqual(["alpha", "bravo", "charlie"]);
  });

  it("renders nullish cells as an em dash and mono cells in the mono stack", async () => {
    await act(async () => {
      root.render(
        <DataTable
          columns={COLUMNS}
          rows={ROWS}
          rowKey={(r) => r.name}
          defaultSortKey="tokens"
        />,
      );
    });

    expect(columnTexts(container, 1)).toEqual(["200", "50", "—"]);
    const monoCell = container.querySelector("tbody td.font-mono-ui");
    expect(monoCell).not.toBeNull();
  });

  it("renders the empty slot across all columns when there are no rows", async () => {
    await act(async () => {
      root.render(
        <DataTable
          columns={COLUMNS}
          rows={[]}
          empty={<EmptyState title="no usage data" description="start a session" />}
        />,
      );
    });

    const td = container.querySelector("tbody td");
    expect(td?.getAttribute("colspan")).toBe("2");
    expect(container.textContent).toContain("no usage data");
    expect(container.textContent).toContain("start a session");
  });
});
