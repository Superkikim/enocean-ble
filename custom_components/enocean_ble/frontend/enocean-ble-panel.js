/*
 * EnOcean BLE — sidebar page to add PTM 215B/216B switches by scanning the
 * QR code on the module label (contains MAC address + AES-128 security key).
 *
 * Scanning:
 *  - Home Assistant Companion app: native barcode scanner over the external bus
 *    ("bar_code/scan" -> "bar_code/scan_result" / "bar_code/aborted").
 *  - Browsers with the BarcodeDetector API (e.g. Chrome on Android/macOS): live camera.
 *  - Otherwise: paste the QR text (e.g. from the phone's camera app).
 *
 * The page only validates the text locally; the backend config flow
 * (step "user", field "qr_code") parses it and creates the config entry.
 * The security key is never displayed.
 */

const DOMAIN = "enocean_ble";
const QR_MAC_RE = /30S([0-9A-Fa-f]{12})/;
const QR_KEY_RE = /\+Z([0-9A-Fa-f]{32})/;
const FREE_MAC_RE = /([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})/;
const FREE_KEY_RE = /\b([0-9A-Fa-f]{32})\b/;

function parseQr(raw) {
  const text = String(raw || "").trim();
  let mac = null;
  const qrMac = QR_MAC_RE.exec(text);
  if (qrMac && QR_KEY_RE.test(text)) {
    mac = qrMac[1].toUpperCase().match(/../g).join(":");
  } else {
    const freeMac = FREE_MAC_RE.exec(text);
    if (freeMac && FREE_KEY_RE.test(text)) mac = freeMac[1].toUpperCase();
  }
  return mac && mac.startsWith("E2:15:") ? { mac } : null;
}

const STYLE = `
  :host { display: block; background: var(--primary-background-color); min-height: 100%;
    color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display: flex; align-items: center; height: var(--header-height, 56px); padding: 0 12px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff)); font-size: 20px; gap: 8px; }
  .content { max-width: 640px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color, #e0e0e0); padding: 16px; }
  h2 { margin: 0 0 8px; font-size: 18px; font-weight: 500; }
  p { margin: 0 0 12px; color: var(--secondary-text-color); line-height: 1.4; }
  button { font: inherit; cursor: pointer; border: none; border-radius: 8px; padding: 10px 16px;
    background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.secondary { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
  button:disabled { opacity: 0.5; cursor: default; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  textarea { width: 100%; box-sizing: border-box; min-height: 64px; font-family: monospace; font-size: 13px;
    padding: 8px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
    background: var(--card-background-color, #fff); color: var(--primary-text-color); margin-bottom: 8px; }
  .status { padding: 8px 12px; border-radius: 8px; margin-top: 12px; display: none; }
  .status.info, .status.ok, .status.error { display: block; }
  .status.info { background: rgba(3, 169, 244, 0.12); }
  .status.ok { background: rgba(76, 175, 80, 0.15); }
  .status.error { background: rgba(219, 68, 55, 0.15); color: var(--error-color, #db4437); }
  .hint { font-size: 13px; color: var(--secondary-text-color); margin-top: 8px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { display: flex; justify-content: space-between; gap: 8px; padding: 8px 0;
    border-bottom: 1px solid var(--divider-color, #eee); }
  li:last-child { border-bottom: none; }
  .mac { font-family: monospace; color: var(--secondary-text-color); font-size: 13px; }
  .overlay { position: fixed; inset: 0; background: #000; z-index: 10; display: none;
    flex-direction: column; align-items: center; justify-content: center; }
  .overlay.open { display: flex; }
  .overlay video { max-width: 100%; max-height: 75vh; }
  .overlay .bar { display: flex; gap: 8px; padding: 12px; align-items: center; color: #fff; }
`;

class EnOceanBlePanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._rendered = false;
    this._busy = false;
    this._stream = null;
    this._scanTimer = null;
    this._releaseNative = () => {};
    this._browserScan = null; // null = unknown, true/false after detection
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this._rendered) this._render();
    if (this._menuButton) this._menuButton.hass = hass;
    if (first) {
      this._refreshEntries();
      this._detectCapabilities();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  set panel(_panel) {}

  connectedCallback() {
    if (this._hass && !this._rendered) this._render();
  }

  disconnectedCallback() {
    this._stopCamera();
    this._releaseNative();
  }

  // ---------- rendering ----------

  _render() {
    this._rendered = true;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="toolbar"><span class="menu"></span><span>EnOcean BLE</span></div>
      <div class="content">
        <div class="card">
          <h2>Add a switch from its QR code</h2>
          <p>Remove the rocker and scan the QR code on the EnOcean module label
            (PTM 215B / PTM 216B). It contains the switch address and its security key,
            so no radio commissioning is needed.</p>
          <div class="row">
            <button id="scan">Scan QR code</button>
            <button id="photo" class="secondary" hidden>Scan from photo</button>
            <input id="file" type="file" accept="image/*" capture="environment" hidden>
          </div>
          <div id="scanHint" class="hint"></div>
          <div id="status" class="status"></div>
        </div>
        <div class="card">
          <h2>Or paste the QR code text</h2>
          <p>For example from your phone's camera app. It looks like
            <code>30SE215…+Z…+30P…</code>.</p>
          <textarea id="text" autocomplete="off" autocapitalize="off" spellcheck="false"
            placeholder="30SE2150000…+Z…"></textarea>
          <button id="add">Add switch</button>
          <div id="pasteStatus" class="status"></div>
        </div>
        <div class="card">
          <h2>Configured switches</h2>
          <ul id="entries"><li>Loading…</li></ul>
        </div>
      </div>
      <div class="overlay" id="overlay">
        <video id="video" playsinline muted></video>
        <div class="bar"><span id="overlayMsg">Point the camera at the QR code</span>
          <button id="cancel" class="secondary">Cancel</button></div>
      </div>`;

    const menuHost = root.querySelector(".menu");
    if (customElements.get("ha-menu-button")) {
      this._menuButton = document.createElement("ha-menu-button");
      this._menuButton.hass = this._hass;
      this._menuButton.narrow = this._narrow;
      menuHost.appendChild(this._menuButton);
    }

    this._el = (id) => root.getElementById(id);
    this._statusTarget = "scan";
    this._el("scan").addEventListener("click", () => {
      this._statusTarget = "scan";
      this._scan();
    });
    this._el("photo").addEventListener("click", () => {
      this._statusTarget = "scan";
      this._el("file").click();
    });
    this._el("file").addEventListener("change", (ev) => this._scanPhoto(ev));
    this._el("add").addEventListener("click", () => {
      this._statusTarget = "paste";
      this._addFromQr(this._el("text").value);
    });
    this._el("cancel").addEventListener("click", () => this._stopCamera());
  }

  _setStatus(kind, message) {
    // Show the result next to whichever control the user used last.
    const active = this._statusTarget === "paste" ? "pasteStatus" : "status";
    const idle = active === "status" ? "pasteStatus" : "status";
    this._el(idle).className = "status";
    const el = this._el(active);
    el.className = `status ${kind}`;
    el.textContent = message;
  }

  // ---------- capabilities ----------

  _external() {
    const ext = this._hass && this._hass.auth && this._hass.auth.external;
    return ext && ext.config && ext.config.hasBarCodeScanner ? ext : null;
  }

  _nativeAvailable() {
    const ext = this._external();
    return Boolean(ext && typeof ext.fireMessage === "function" && "_commandHandler" in ext);
  }

  async _detectCapabilities() {
    this._browserScan = false;
    try {
      if ("BarcodeDetector" in window && navigator.mediaDevices) {
        const formats = await window.BarcodeDetector.getSupportedFormats();
        this._browserScan = formats.includes("qr_code");
      }
    } catch (_err) {
      this._browserScan = false;
    }
    const scan = this._el("scan");
    const hint = this._el("scanHint");
    if (this._nativeAvailable()) {
      hint.textContent = "Uses the Home Assistant app's scanner.";
    } else if (this._browserScan) {
      this._el("photo").hidden = false;
      hint.textContent = "Uses this browser's camera.";
    } else {
      scan.disabled = true;
      hint.textContent =
        "Camera scanning is not available in this browser. Open this page in the " +
        "Home Assistant app, or paste the QR code text below.";
    }
  }

  _scan() {
    if (this._busy) return;
    if (this._nativeAvailable()) this._scanNative();
    else if (this._browserScan) this._scanCamera();
  }

  // ---------- Companion app scanner ----------

  _scanNative() {
    const ext = this._external();
    const original = ext._commandHandler;
    const wrapped = (msg) => {
      if (msg && msg.type === "command" && msg.command === "bar_code/scan_result") {
        const value = (msg.payload && msg.payload.rawValue) || "";
        if (parseQr(value)) {
          this._releaseNative();
          ext.fireMessage({ type: "bar_code/close" });
          this._addFromQr(value);
        } else {
          ext.fireMessage({
            type: "bar_code/notify",
            payload: { message: "This is not an EnOcean switch QR code. Try again." },
          });
        }
      } else if (msg && msg.type === "command" && msg.command === "bar_code/aborted") {
        this._releaseNative();
        if (msg.payload && msg.payload.reason === "alternative_options") this._el("text").focus();
      }
      return typeof original === "function" ? original.call(ext, msg) : true;
    };
    this._releaseNative = () => {
      if (ext._commandHandler === wrapped) ext._commandHandler = original;
      this._releaseNative = () => {};
    };
    ext._commandHandler = wrapped;
    ext.fireMessage({
      type: "bar_code/scan",
      payload: {
        title: "Scan EnOcean switch",
        description: "Point the camera at the QR code on the switch module label.",
        alternative_option_label: "Enter text instead",
      },
    });
  }

  // ---------- Browser camera (BarcodeDetector) ----------

  async _scanCamera() {
    const overlay = this._el("overlay");
    const video = this._el("video");
    const msg = this._el("overlayMsg");
    msg.textContent = "Point the camera at the QR code";
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
    } catch (err) {
      this._setStatus("error", `Camera not available: ${err && err.message ? err.message : err}`);
      return;
    }
    overlay.classList.add("open");
    video.srcObject = this._stream;
    await video.play().catch(() => {});
    const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    const tick = async () => {
      if (!this._stream) return;
      try {
        const codes = await detector.detect(video);
        for (const code of codes) {
          if (parseQr(code.rawValue)) {
            this._stopCamera();
            this._addFromQr(code.rawValue);
            return;
          }
          msg.textContent = "That is not an EnOcean switch QR code";
        }
      } catch (_err) {
        // video not ready yet
      }
      this._scanTimer = setTimeout(tick, 250);
    };
    tick();
  }

  _stopCamera() {
    clearTimeout(this._scanTimer);
    this._scanTimer = null;
    if (this._stream) {
      this._stream.getTracks().forEach((track) => track.stop());
      this._stream = null;
    }
    if (this._el) {
      this._el("video").srcObject = null;
      this._el("overlay").classList.remove("open");
    }
  }

  async _scanPhoto(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      const codes = await new window.BarcodeDetector({ formats: ["qr_code"] }).detect(bitmap);
      const match = codes.find((code) => parseQr(code.rawValue));
      if (match) this._addFromQr(match.rawValue);
      else this._setStatus("error", "No EnOcean switch QR code found in this photo.");
    } catch (err) {
      this._setStatus("error", `Could not read the photo: ${err && err.message ? err.message : err}`);
    }
  }

  // ---------- config flow ----------

  async _addFromQr(raw) {
    const info = parseQr(raw);
    if (!info) {
      this._setStatus(
        "error",
        "No EnOcean address (30SE215…) and 32-character key (+Z…) found in this text."
      );
      return;
    }
    if (this._busy) return;
    this._busy = true;
    this._el("add").disabled = true;
    this._setStatus("info", `Adding ${info.mac}…`);
    let flowId = null;
    try {
      const start = await this._hass.callApi("POST", "config/config_entries/flow", {
        handler: DOMAIN,
        show_advanced_options: false,
      });
      flowId = start.flow_id;
      if (start.type !== "form" || start.step_id !== "user") {
        throw new Error(`unexpected setup step "${start.step_id || start.type}"`);
      }
      const result = await this._hass.callApi("POST", `config/config_entries/flow/${flowId}`, {
        qr_code: String(raw).trim(),
      });
      if (result.type === "create_entry") {
        flowId = null;
        this._el("text").value = "";
        this._setStatus("ok", `Added switch ${info.mac}. Press a button on it to test.`);
        this._refreshEntries();
      } else if (result.type === "abort") {
        flowId = null;
        this._setStatus(
          result.reason === "already_configured" ? "info" : "error",
          result.reason === "already_configured"
            ? `Switch ${info.mac} is already added.`
            : `Not added: ${result.reason}`
        );
      } else {
        this._setStatus("error", "The QR code text was not accepted.");
      }
    } catch (err) {
      this._setStatus("error", `Could not add the switch: ${err && err.message ? err.message : err}`);
    } finally {
      if (flowId) {
        this._hass.callApi("DELETE", `config/config_entries/flow/${flowId}`).catch(() => {});
      }
      this._busy = false;
      this._el("add").disabled = false;
    }
  }

  async _refreshEntries() {
    const list = this._el("entries");
    try {
      const entries = await this._hass.callWS({ type: "config_entries/get", domain: DOMAIN });
      list.replaceChildren();
      if (!entries.length) {
        const li = document.createElement("li");
        li.textContent = "No switches yet.";
        list.appendChild(li);
        return;
      }
      const devices = Object.values(this._hass.devices || {});
      for (const entry of entries) {
        const device = devices.find((dev) => (dev.config_entries || []).includes(entry.entry_id));
        const connection =
          device && (device.connections || []).find((conn) => conn[0] === "bluetooth");
        const li = document.createElement("li");
        const name = document.createElement(device ? "a" : "span");
        name.textContent = entry.title;
        if (device) {
          name.href = `/config/devices/device/${device.id}`;
          name.style.color = "var(--primary-color)";
        }
        const mac = document.createElement("span");
        mac.className = "mac";
        mac.textContent = entry.state === "loaded" ? (connection ? connection[1] : "") : entry.state;
        li.append(name, mac);
        list.appendChild(li);
      }
    } catch (err) {
      list.textContent = `Could not load switches: ${err && err.message ? err.message : err}`;
    }
  }
}

if (!customElements.get("enocean-ble-panel")) {
  customElements.define("enocean-ble-panel", EnOceanBlePanel);
}
