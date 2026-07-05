import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

export default function Terminal({ containerName, onClose }) {
  const termRef = useRef(null);
  const xtermRef = useRef(null);
  const wsRef = useRef(null);

  useEffect(() => {
    const term = new XTerm({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"IBM Plex Mono", "SF Mono", "Fira Code", "Cascadia Code", monospace',
      theme: {
        background: "#0b0d10",
        foreground: "#edf1f4",
        cursor: "#1bb3c7",
        selectionBackground: "#21262c",
      },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(termRef.current);
    fitAddon.fit();
    xtermRef.current = term;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = import.meta.env.VITE_API_URL
      ? new URL(import.meta.env.VITE_API_URL).host
      : window.location.host;
    const ws = new WebSocket(`${proto}://${host}/ws/console/${containerName}`);
    wsRef.current = ws;

    ws.onopen = () => {
      term.writeln(`\x1b[32mConnected to ${containerName}\x1b[0m\r`);
      ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };

    ws.onmessage = (e) => term.write(e.data);

    ws.onclose = () => term.writeln("\r\n\x1b[31mDisconnected\x1b[0m");
    ws.onerror = () => term.writeln("\r\n\x1b[31mConnection error\x1b[0m");

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    const onResize = () => {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    };
    term.onResize(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    });
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      ws.close();
      term.dispose();
    };
  }, [containerName]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="terminal-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Console: {containerName}</span>
          <button className="btn btn-sm btn-danger" onClick={onClose}>Disconnect</button>
        </div>
        <div className="terminal-body" ref={termRef} />
      </div>
    </div>
  );
}
