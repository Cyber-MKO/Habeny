import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MetricsProvider, useMetricsSocket } from "./ws";

class FakeSocket {
  static all = [];
  constructor(url) {
    this.url = url;
    this.closed = false;
    FakeSocket.all.push(this);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }
}

function Probe() {
  const { metrics, connected } = useMetricsSocket();
  return <p>{connected ? "connected" : "offline"} {metrics ? metrics.cpu : "-"}</p>;
}

describe("metrics socket", () => {
  beforeEach(() => {
    FakeSocket.all = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shares one connection and passes messages on", () => {
    render(<MetricsProvider><Probe /><Probe /></MetricsProvider>);
    expect(FakeSocket.all).toHaveLength(1);
    expect(FakeSocket.all[0].url).toMatch(/^ws:\/\/.+\/ws\/metrics$/);
    const ws = FakeSocket.all[0];
    act(() => ws.onopen());
    act(() => ws.onmessage({ data: JSON.stringify({ cpu: 42 }) }));
    expect(screen.getAllByText("connected 42")).toHaveLength(2);
    act(() => ws.onmessage({ data: "not json" })); // ignored
    expect(screen.getAllByText("connected 42")).toHaveLength(2);
  });

  it("reconnects with backoff after the connection drops", () => {
    render(<MetricsProvider><Probe /></MetricsProvider>);
    act(() => FakeSocket.all[0].close());
    expect(screen.getByText("offline -")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(999));
    expect(FakeSocket.all).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeSocket.all).toHaveLength(2);
    act(() => FakeSocket.all[1].close()); // second failure: waits 2 s
    act(() => vi.advanceTimersByTime(1999));
    expect(FakeSocket.all).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeSocket.all).toHaveLength(3);
    act(() => FakeSocket.all[2].onopen()); // success resets the backoff
    act(() => FakeSocket.all[2].close());
    act(() => vi.advanceTimersByTime(1000));
    expect(FakeSocket.all).toHaveLength(4);
  });

  it("closes the socket and stops reconnecting when unmounted", () => {
    const { unmount } = render(<MetricsProvider><Probe /></MetricsProvider>);
    unmount();
    expect(FakeSocket.all[0].closed).toBe(true);
    act(() => vi.advanceTimersByTime(60000));
    expect(FakeSocket.all).toHaveLength(1);
  });
});
