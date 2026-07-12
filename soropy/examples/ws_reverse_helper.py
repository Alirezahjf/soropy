"""
Legacy helper: capture WebSocket frames from the web UI via Selenium.

The production WebSocket backend no longer needs frame capture — it uses
MTProto via SPlusthon.  Keep this script only if you want to inspect
LiveKit / secondary sockets used by the web client.
"""

from __future__ import annotations

import json

from soropy import SoroushClient

INJECT_JS = r"""
(function () {
  if (window.__soropy_ws_hooked) return 'already';
  window.__soropy_ws_hooked = true;
  window.__soropy_ws_log = [];
  function push(dir, data) {
    window.__soropy_ws_log.push({
      t: Date.now(),
      dir: dir,
      type: (typeof data === 'string') ? 'text' : 'binary',
      data: (typeof data === 'string')
        ? data.slice(0, 500)
        : (data && data.byteLength !== undefined
            ? '[ArrayBuffer ' + data.byteLength + ']'
            : String(data))
    });
    if (window.__soropy_ws_log.length > 2000) window.__soropy_ws_log.shift();
  }
  var OriginalWS = window.WebSocket;
  function HookedWS(url, protocols) {
    var ws = protocols !== undefined
      ? new OriginalWS(url, protocols)
      : new OriginalWS(url);
    push('meta', 'CONNECT ' + url);
    var origSend = ws.send.bind(ws);
    ws.send = function (data) {
      try { push('out', data); } catch (e) {}
      return origSend(data);
    };
    ws.addEventListener('message', function (ev) {
      try { push('in', ev.data); } catch (e) {}
    });
    return ws;
  }
  HookedWS.prototype = OriginalWS.prototype;
  HookedWS.CONNECTING = OriginalWS.CONNECTING;
  HookedWS.OPEN = OriginalWS.OPEN;
  HookedWS.CLOSING = OriginalWS.CLOSING;
  HookedWS.CLOSED = OriginalWS.CLOSED;
  window.WebSocket = HookedWS;
  return 'hooked';
})();
"""


def main():
    print("NOTE: Production backend uses MTProto (backend='websocket').")
    print("This helper is only for inspecting web-client sockets.\n")
    phone = input("Phone number: ").strip() or "09123456789"
    client = SoroushClient(phone, backend="selenium", headless=False)
    try:
        print(client.login())
        driver = client.backend.get_raw_driver()
        print("hook:", driver.execute_script(INJECT_JS))
        while True:
            cmd = input("[Enter=dump | r=rehook | q=quit] > ").strip().lower()
            if cmd in ("q", "quit", "exit"):
                break
            if cmd in ("r", "rehook"):
                print(driver.execute_script(INJECT_JS))
                continue
            log = driver.execute_script("return window.__soropy_ws_log || [];")
            with open("ws_capture.json", "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(log)} frames → ws_capture.json")
    finally:
        client.close()


if __name__ == "__main__":
    main()
