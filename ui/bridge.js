// The wire between this page and the Mac app: engine calls, engine events, and native helpers
// (folder picker, opening files, reading the clipboard). The app calls TajmeeaBridge.receive().
(function () {
  const handlers = window.webkit && window.webkit.messageHandlers;
  const pending = new Map();
  const listeners = {};
  let nextId = 1;

  const bridge = {
    available: Boolean(handlers && handlers.engine),

    call(method, params) {
      return new Promise((resolve, reject) => {
        const id = nextId++;
        pending.set(id, { resolve, reject });
        bridge.send({ id, method, params: params || {} });
      });
    },

    native(action, args) {
      return new Promise((resolve, reject) => {
        const id = nextId++;
        pending.set(id, { resolve, reject });
        bridge.sendNative({ id, action, args: args || {} });
      });
    },

    on(event, fn) {
      (listeners[event] = listeners[event] || []).push(fn);
    },

    receive(message) {
      if (message && Object.prototype.hasOwnProperty.call(message, "id")) {
        const waiter = pending.get(message.id);
        if (!waiter) return;
        pending.delete(message.id);
        if (message.error) {
          const error = new Error(message.error.message);
          error.code = message.error.code;
          waiter.reject(error);
        } else {
          waiter.resolve(message.result);
        }
        return;
      }
      if (message && message.event) {
        (listeners[message.event] || []).forEach((fn) => fn(message.data || {}));
        (listeners["*"] || []).forEach((fn) => fn(message.event, message.data || {}));
      }
    },

    send(message) {
      handlers.engine.postMessage(JSON.stringify(message));
    },

    sendNative(message) {
      handlers.native.postMessage(JSON.stringify(message));
    },

    // The app hands ⌘V / ⌘C / ⌘X / ⌘A over here, so they work on any keyboard layout.
    paste(text) {
      const field = editable(document.activeElement);
      if (!field) return;
      if (!document.execCommand("insertText", false, text)) {
        field.setRangeText(text, field.selectionStart, field.selectionEnd, "end");
        field.dispatchEvent(new Event("input", { bubbles: true }));
      }
      field.dispatchEvent(new Event("paste", { bubbles: true }));
    },

    copySelection(mode) {
      const field = editable(document.activeElement);
      if (!field) return String(window.getSelection() || "");
      if (field.type === "password") return "";
      const text = field.value.slice(field.selectionStart, field.selectionEnd);
      if (mode === "cut" && text) document.execCommand("delete");
      return text;
    },

    selectAll() {
      const field = editable(document.activeElement);
      if (field) field.select();
      else document.execCommand("selectAll");
    },
  };

  function editable(el) {
    if (!el || el.disabled || el.readOnly) return null;
    if (el.tagName === "TEXTAREA") return el;
    if (el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit"].includes(el.type)) return el;
    return null;
  }

  window.TajmeeaBridge = bridge;
})();
