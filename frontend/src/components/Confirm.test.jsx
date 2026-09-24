import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ConfirmProvider, useConfirm } from "./Confirm";
import { Details } from "./Details";

function Asker({ options, onAnswer }) {
  const confirm = useConfirm();
  return <button onClick={async () => onAnswer(await confirm(options))}>Delete it</button>;
}

function setup(options) {
  const answers = [];
  render(<ConfirmProvider><Asker options={options} onAnswer={(a) => answers.push(a)} /></ConfirmProvider>);
  return answers;
}

describe("confirmation dialog", () => {
  it("is a labelled modal dialog that answers yes or no, and returns focus", async () => {
    const answers = setup({ title: "Delete group red?", message: "Its containers stay.", confirmLabel: "Delete group", danger: true });
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Delete it" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Delete group red?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Its containers stay.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus(); // the safe choice first
    await user.click(screen.getByRole("button", { name: "Delete group" }));
    expect(answers).toEqual([true]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("Escape cancels", async () => {
    const answers = setup({ title: "Sure?" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete it" }));
    await user.keyboard("{Escape}");
    expect(answers).toEqual([false]);
  });

  it("can require typing a word for big deletions", async () => {
    const answers = setup({ title: "Delete 40 containers?", requireText: "delete", confirmLabel: "Delete", danger: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete it" }));
    const go = screen.getByRole("button", { name: "Delete" });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText(/Type “delete” to confirm/), "delete");
    await user.click(go);
    expect(answers).toEqual([true]);
  });

  it("keeps Tab inside the dialog", async () => {
    setup({ title: "Sure?" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete it" }));
    const dialog = screen.getByRole("dialog");
    for (let i = 0; i < 5; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});

describe("details view", () => {
  it("shows API data as labelled values instead of JSON", () => {
    render(<Details data={{ agent_name: "web-0001", siem_ip: "10.0.0.5", running: true, cpu_shares: 1024,
      created_at: "2026-09-24T10:00:00+00:00", tags: ["a", "b"], results: [{ agent_id: "x", success: false }] }} />);
    expect(screen.getByText("Agent name")).toBeInTheDocument();
    expect(screen.getByText("SIEM IP")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("a, b")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Agent ID" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("{");
  });
});
