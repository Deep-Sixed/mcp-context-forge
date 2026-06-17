/**
 * Unit tests for components/app-root.js
 * Tests: appRoot factory, init lifecycle, darkMode persistence
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { appRoot } from "../../../mcpgateway/admin_ui/components/app-root.js";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeComponent() {
  const component = appRoot();
  const watchCallbacks = {};
  component.$watch = vi.fn((prop, cb) => {
    watchCallbacks[prop] = cb;
  });
  return { component, watchCallbacks };
}

// ─── Setup / teardown ─────────────────────────────────────────────────────────

let localStorageMock;

beforeEach(() => {
  // Create a fresh localStorage mock for each test
  localStorageMock = (() => {
    let store = {};
    return {
      getItem: (key) => store[key] || null,
      setItem: (key, value) => {
        store[key] = String(value);
      },
      removeItem: (key) => {
        delete store[key];
      },
      clear: () => {
        store = {};
      },
    };
  })();

  // Stub global localStorage
  vi.stubGlobal("localStorage", localStorageMock);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete window.Admin;
});

// ─── Factory ──────────────────────────────────────────────────────────────────

describe("appRoot factory", () => {
  test("returns darkMode as false initially", () => {
    const { component } = makeComponent();
    expect(component.darkMode).toBe(false);
  });

  test("exposes an init method", () => {
    const { component } = makeComponent();
    expect(typeof component.init).toBe("function");
  });

  test("does not throw on construction", () => {
    expect(() => appRoot()).not.toThrow();
  });
});

// ─── init ─────────────────────────────────────────────────────────────────────

describe("init", () => {
  test("sets darkMode to true when localStorage has 'true'", () => {
    localStorage.setItem("darkMode", "true");
    const { component } = makeComponent();
    component.init();
    expect(component.darkMode).toBe(true);
  });

  test("sets darkMode to false when localStorage has 'false'", () => {
    localStorage.setItem("darkMode", "false");
    const { component } = makeComponent();
    component.init();
    expect(component.darkMode).toBe(false);
  });

  test("defaults to false when localStorage has no darkMode entry", () => {
    const { component } = makeComponent();
    component.init();
    expect(component.darkMode).toBe(false);
  });

  test("registers a $watch on darkMode", () => {
    const { component } = makeComponent();
    component.init();
    expect(component.$watch).toHaveBeenCalledWith("darkMode", expect.any(Function));
  });

  test("calls Admin.logRestrictedContext when localStorage value is invalid JSON", () => {
    localStorage.setItem("darkMode", "{not-valid-json");
    const logRestrictedContext = vi.fn();
    window.Admin = { logRestrictedContext };
    const { component } = makeComponent();
    component.init();
    expect(logRestrictedContext).toHaveBeenCalledOnce();
  });

  test("does not throw on JSON parse error when Admin is absent", () => {
    localStorage.setItem("darkMode", "not-json");
    delete window.Admin;
    const { component } = makeComponent();
    expect(() => component.init()).not.toThrow();
  });

  test("does not call Admin.logRestrictedContext when value is valid JSON", () => {
    localStorage.setItem("darkMode", "true");
    const logRestrictedContext = vi.fn();
    window.Admin = { logRestrictedContext };
    const { component } = makeComponent();
    component.init();
    expect(logRestrictedContext).not.toHaveBeenCalled();
  });
});

// ─── darkMode $watch callback ─────────────────────────────────────────────────

describe("darkMode $watch callback", () => {
  test("writes 'true' to localStorage when darkMode becomes true", () => {
    const { component, watchCallbacks } = makeComponent();
    component.init();
    watchCallbacks.darkMode(true);
    expect(localStorage.getItem("darkMode")).toBe("true");
  });

  test("writes 'false' to localStorage when darkMode becomes false", () => {
    const { component, watchCallbacks } = makeComponent();
    component.init();
    watchCallbacks.darkMode(false);
    expect(localStorage.getItem("darkMode")).toBe("false");
  });

  test("calls Admin.logRestrictedContext when localStorage.setItem throws", () => {
    // Spy on the mocked localStorage's setItem method
    vi.spyOn(localStorageMock, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    const logRestrictedContext = vi.fn();
    window.Admin = { logRestrictedContext };
    const { component, watchCallbacks } = makeComponent();
    component.init();
    watchCallbacks.darkMode(true);
    expect(logRestrictedContext).toHaveBeenCalledOnce();
  });

  test("does not throw on write error when Admin is absent", () => {
    // Spy on the mocked localStorage's setItem method
    vi.spyOn(localStorageMock, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    delete window.Admin;
    const { component, watchCallbacks } = makeComponent();
    component.init();
    expect(() => watchCallbacks.darkMode(true)).not.toThrow();
  });
});
