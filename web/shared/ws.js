// Shared WebSocket wrapper: envelope, heartbeat, auto-reconnect (§7.1).
export class GameSocket {
  /**
   * @param {string} path - e.g. "/ws/board/ABCD" or "/ws/play"
   * @param {object} handlers - { onMessage(type, data), onOpen(), onClose() }
   */
  constructor(path, handlers = {}) {
    this.path = path;
    this.handlers = handlers;
    this.ws = null;
    this.backoff = 1000;
    this.maxBackoff = 10000;
    this.heartbeatTimer = null;
    this.closedByUser = false;
    this._connect();
  }

  _url() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}${this.path}`;
  }

  _connect() {
    const ws = new WebSocket(this._url());
    this.ws = ws;

    ws.addEventListener("open", () => {
      this.backoff = 1000;
      this._startHeartbeat();
      this.handlers.onOpen?.();
    });

    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      this.handlers.onMessage?.(msg.type, msg.data || {});
    });

    ws.addEventListener("close", () => {
      this._stopHeartbeat();
      this.handlers.onClose?.();
      if (!this.closedByUser) {
        setTimeout(() => this._connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 2, this.maxBackoff);
      }
    });

    ws.addEventListener("error", () => {
      ws.close();
    });
  }

  _startHeartbeat() {
    this._stopHeartbeat();
    this.heartbeatTimer = setInterval(() => this.send("ping", {}), 20000);
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  send(type, data = {}) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    }
  }

  close() {
    this.closedByUser = true;
    this._stopHeartbeat();
    this.ws?.close();
  }
}
