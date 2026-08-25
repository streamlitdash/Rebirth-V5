/* Shared browser shell: theme, Plotly palette, cube motion, and refresh loader. */
(() => {
  "use strict";

  const app = window.__cubeV5Assets = window.__cubeV5Assets || {};
  let plotlyThemeTimer = null;
  let pendingPlotlyTheme = null;
  let pendingPlotlyThemeAll = false;
  const pendingPlotlyThemeGraphs = new Set();
  const plotlyThemeRetries = new WeakMap();
  const THEME_KEY = "cube-theme-v1";

  const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches || false;

  const CUBE_ROLL_POINTS = Object.freeze([
    [0, -1],
    [0.8660254, -0.5],
    [0.8660254, 0.5],
    [0, 1],
    [-0.8660254, 0.5],
    [-0.8660254, -0.5],
    [0, -1],
  ]);
  const CUBE_ROLL_STEP_MS = 1200;
  const CUBE_ROLL_FRAME_MS = 1000 / 30;
  const CUBE_ROLL_ACTIVE_FRACTION = 1;
  const CUBE_ROLL_MAX_LIFT = 0.2071068;
  const cubeRollStates = new Map();
  let cubeRollFrame = null;
  let cubeRollWakeTimer = null;
  let cubeRollStopped = false;

  const multiplyQuaternion = (left, right) => ({
    w: left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z,
    x: left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y,
    y: left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x,
    z: left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w,
  });

  const normalizedQuaternion = (quaternion) => {
    const length = Math.hypot(quaternion.w, quaternion.x, quaternion.y, quaternion.z) || 1;
    return {
      w: quaternion.w / length,
      x: quaternion.x / length,
      y: quaternion.y / length,
      z: quaternion.z / length,
    };
  };

  const quaternionPower = (quaternion, exponent) => {
    let result = { w: 1, x: 0, y: 0, z: 0 };
    let factor = normalizedQuaternion(quaternion);
    let remaining = Math.max(0, Math.floor(exponent));
    while (remaining > 0) {
      if (remaining % 2 === 1) result = normalizedQuaternion(multiplyQuaternion(factor, result));
      factor = normalizedQuaternion(multiplyQuaternion(factor, factor));
      remaining = Math.floor(remaining / 2);
    }

    return result;
  };

  const axisQuaternion = (axis, angle) => {
    const length = Math.hypot(axis[0], axis[1], axis[2]) || 1;
    const half = angle / 2;
    const sine = Math.sin(half) / length;
    return {
      w: Math.cos(half),
      x: axis[0] * sine,
      y: axis[1] * sine,
      z: axis[2] * sine,
    };
  };

  const cubeRollSteps = CUBE_ROLL_POINTS.slice(0, -1).map((start, index) => {
    const end = CUBE_ROLL_POINTS[index + 1];
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    return Object.freeze({ start, end, dx, dy, axis: Object.freeze([-dy, dx, 0]) });
  });

  const cubeRollBoundaries = [Object.freeze({ w: 1, x: 0, y: 0, z: 0 })];
  cubeRollSteps.forEach((step, index) => {
    cubeRollBoundaries.push(Object.freeze(normalizedQuaternion(multiplyQuaternion(
      axisQuaternion(step.axis, Math.PI / 2),
      cubeRollBoundaries[index],
    ))));
  });
  Object.freeze(cubeRollBoundaries);
  const cubeRollCircuitOrientation = cubeRollBoundaries[cubeRollBoundaries.length - 1];

  const quaternionMatrix = (quaternion) => {
    const { w, x, y, z } = normalizedQuaternion(quaternion);
    const values = [
      1 - 2 * (y * y + z * z),
      2 * (x * y + w * z),
      2 * (x * z - w * y),
      0,
      2 * (x * y - w * z),
      1 - 2 * (x * x + z * z),
      2 * (y * z + w * x),
      0,
      2 * (x * z + w * y),
      2 * (y * z - w * x),
      1 - 2 * (x * x + y * y),
      0,
      0,
      0,
      0,
      1,
    ];
    return `matrix3d(${values.map((value) => Math.abs(value) < 1e-9 ? 0 : value.toFixed(7)).join(",")})`;
  };

  const cubeRootIsVisible = (root) => {
    if (!root.isConnected || root.closest("[hidden]")) return false;
    if (root.closest("#refresh-progress.is-complete, #refresh-progress.is-error")) return false;
    const style = window.getComputedStyle(root);
    return style.display !== "none" && style.visibility !== "hidden" && root.getClientRects().length > 0;
  };

  const applyStaticCube = (state) => {
    state.traveller.style.transform = "translate3d(0, 0, 0)";
    state.lift.style.transform = "translate3d(0, 0, 0)";
    state.roller.style.transform = quaternionMatrix(cubeRollBoundaries[0]);
    state.shadow.style.opacity = "0.42";
    state.shadow.style.transform = "translateX(-50%) scale(1)";
    state.staticApplied = true;
  };

  const applyCubeRollFrame = (state, elapsed) => {
    const stepMs = CUBE_ROLL_STEP_MS;
    const circuits = stepMs * cubeRollSteps.length;
    const completedCircuits = Math.floor(elapsed / circuits);
    const circuitElapsed = elapsed % circuits;
    const stepPosition = circuitElapsed / stepMs;
    const stepIndex = Math.min(cubeRollSteps.length - 1, Math.floor(stepPosition));
    const stepFraction = stepPosition - stepIndex;
    const active = Math.min(stepFraction / CUBE_ROLL_ACTIVE_FRACTION, 1);
    const eased = active * active * (3 - 2 * active);
    const theta = eased * Math.PI / 2;
    const along = 0.5 * (1 - Math.cos(theta) + Math.sin(theta));
    const lift = 0.5 * (Math.cos(theta) + Math.sin(theta) - 1);
    const step = cubeRollSteps[stepIndex];

    const size = state.size;
    const x = (step.start[0] + step.dx * along) * size;
    const y = (step.start[1] + step.dy * along) * size;
    const orientation = multiplyQuaternion(
      axisQuaternion(step.axis, theta),
      multiplyQuaternion(
        cubeRollBoundaries[stepIndex],
        quaternionPower(cubeRollCircuitOrientation, completedCircuits),
      ),
    );

    state.traveller.style.transform = `translate3d(${x.toFixed(3)}px, ${y.toFixed(3)}px, 0)`;
    state.lift.style.transform = `translate3d(0, ${(-lift * size).toFixed(3)}px, 0)`;
    state.roller.style.transform = quaternionMatrix(orientation);
    const liftRatio = Math.max(0, Math.min(1, lift / CUBE_ROLL_MAX_LIFT));
    state.shadow.style.opacity = (0.42 - liftRatio * 0.18).toFixed(3);
    state.shadow.style.transform = `translateX(-50%) scale(${(1 - liftRatio * 0.28).toFixed(3)})`;

    state.staticApplied = false;
  };

  const registerCubeRollers = (scope = document) => {
    scope.querySelectorAll?.(".cube-motion").forEach((root) => {
      if (cubeRollStates.has(root)) return;
      const state = {
        root,
        traveller: root.querySelector(".cube-motion__traveller"),
        lift: root.querySelector(".cube-motion__lift"),
        roller: root.querySelector(".cube-motion__roller"),
        shadow: root.querySelector(".cube-motion__shadow"),
        elapsed: 0,
        lastTimestamp: null,
        lastPaintTimestamp: null,
        visible: false,
        staticApplied: false,
        size: parseFloat(window.getComputedStyle(root).getPropertyValue("--cube-size")) || 18,
      };
      if (!state.traveller || !state.lift || !state.roller || !state.shadow) return;
      cubeRollStates.set(root, state);
      applyCubeRollFrame(state, 0);
    });
    if (!cubeRollStopped && cubeRollFrame === null && cubeRollWakeTimer === null) {
      cubeRollFrame = requestAnimationFrame(runCubeRollers);
    }
  };

  function runCubeRollers(timestamp) {
    cubeRollFrame = null;
    let activeRoots = 0;
    const reduced = prefersReducedMotion();
    cubeRollStates.forEach((state, root) => {
      if (!root.isConnected) {
        cubeRollStates.delete(root);
        return;
      }

      const visible = cubeRootIsVisible(root);
      if (!visible) {
        state.visible = false;
        state.elapsed = 0;
        state.lastTimestamp = null;
        state.lastPaintTimestamp = null;
        return;
      }

      if (reduced) {
        if (!state.staticApplied) applyStaticCube(state);
        state.visible = false;
        state.elapsed = 0;
        state.lastTimestamp = null;
        state.lastPaintTimestamp = null;
        return;
      }
      activeRoots += 1;
      if (!state.visible) {
        state.visible = true;
        state.elapsed = 0;
        state.lastTimestamp = timestamp;
        state.lastPaintTimestamp = null;
        state.size = parseFloat(window.getComputedStyle(root).getPropertyValue("--cube-size")) || 18;
      } else {
        const delta = Math.min(100, Math.max(0, timestamp - (state.lastTimestamp ?? timestamp)));
        state.elapsed += delta;
        state.lastTimestamp = timestamp;
      }
      if (
        state.lastPaintTimestamp === null
        || timestamp - state.lastPaintTimestamp >= CUBE_ROLL_FRAME_MS
      ) {
        applyCubeRollFrame(state, state.elapsed);
        state.lastPaintTimestamp = timestamp;
      }
    });

    if (cubeRollStopped) return;
    if (activeRoots) {
      cubeRollFrame = requestAnimationFrame(runCubeRollers);
    } else {
      cubeRollWakeTimer = setTimeout(() => {
        cubeRollWakeTimer = null;
        registerCubeRollers();
      }, 250);
    }
  }

  const refreshCubeRollSizes = () => {
    cubeRollStates.forEach((state, root) => {
      if (!root.isConnected) return;
      const size = parseFloat(window.getComputedStyle(root).getPropertyValue("--cube-size")) || 18;
      if (size === state.size) return;
      state.size = size;
      if (state.visible && !prefersReducedMotion()) applyCubeRollFrame(state, state.elapsed);
    });
  };

  const savedTheme = () => {
    try {
      const value = window.localStorage.getItem(THEME_KEY);
      return value === "dark" || value === "light" ? value : null;
    } catch (_error) {
      return null;
    }
  };

  const themePalette = (theme) => theme === "dark"
    ? { background: "#0b1c13", ink: "#f1f9f3", grid: "#355642", line: "#6f8f7c" }
    : { background: "#ffffff", ink: "#111111", grid: "#e2e6ea", line: "#c7cdd4" };

  const syncPlotlyTheme = (theme, graphs) => {
    if (!window.Plotly?.relayout) return [];
    const palette = themePalette(theme);
    const retryGraphs = [];
    const themedAxis = (axis = {}) => {
      const currentTitle = typeof axis.title === "string" ? { text: axis.title } : (axis.title || {});
      return {
        ...axis,
        gridcolor: palette.grid,
        linecolor: palette.line,
        zerolinecolor: palette.line,
        tickfont: { ...(axis.tickfont || {}), color: palette.ink },
        title: { ...currentTitle, font: { ...(currentTitle.font || {}), color: palette.ink } },
      };
    };
    Array.from(graphs || []).forEach((graph) => {
      if (!graph?.isConnected) return;
      if (!graph.data || !graph.layout) {
        const retryCount = (plotlyThemeRetries.get(graph) || 0) + 1;
        if (retryCount <= 5) {
          plotlyThemeRetries.set(graph, retryCount);
          retryGraphs.push(graph);
        } else {
          plotlyThemeRetries.delete(graph);
        }
        return;
      }
      plotlyThemeRetries.delete(graph);
      const layoutUpdate = {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: palette.background,
        "font.color": palette.ink,
        xaxis: themedAxis(graph.layout.xaxis),
        yaxis: themedAxis(graph.layout.yaxis),
        "legend.bgcolor": "rgba(0,0,0,0)",
        "legend.bordercolor": palette.line,
        "legend.font.color": palette.ink,
      };
      if (graph.layout.yaxis2) layoutUpdate.yaxis2 = themedAxis(graph.layout.yaxis2);
      Object.keys(graph.layout).filter((key) => /^scene\d*$/.test(key)).forEach((key) => {
        const scene = graph.layout[key] || {};
        layoutUpdate[key] = {
          ...scene,
          bgcolor: palette.background,
          xaxis: themedAxis(scene.xaxis),
          yaxis: themedAxis(scene.yaxis),
          zaxis: themedAxis(scene.zaxis),
        };
      });
      const update = window.Plotly.relayout(graph, layoutUpdate);
      update?.catch?.(() => {});
    });
    return retryGraphs;
  };

  const schedulePlotlyTheme = (theme, graphs = null, delay = 40) => {
    pendingPlotlyTheme = theme;
    if (graphs === null) {
      pendingPlotlyThemeAll = true;
      pendingPlotlyThemeGraphs.clear();
    } else if (!pendingPlotlyThemeAll) {
      Array.from(graphs).forEach((graph) => {
        if (graph?.isConnected) pendingPlotlyThemeGraphs.add(graph);
      });
    }
    if (plotlyThemeTimer) clearTimeout(plotlyThemeTimer);
    plotlyThemeTimer = setTimeout(() => {
      plotlyThemeTimer = null;
      const nextTheme = pendingPlotlyTheme || theme;
      const targets = pendingPlotlyThemeAll
        ? document.querySelectorAll(".js-plotly-plot")
        : Array.from(pendingPlotlyThemeGraphs);
      pendingPlotlyTheme = null;
      pendingPlotlyThemeAll = false;
      pendingPlotlyThemeGraphs.clear();
      const retryGraphs = syncPlotlyTheme(nextTheme, targets);
      if (retryGraphs.length) schedulePlotlyTheme(nextTheme, retryGraphs, 100);
    }, delay);
  };

  const updateThemeButton = (theme) => {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    const dark = theme === "dark";
    const symbol = dark ? "☀" : "☾";
    if (button.textContent !== symbol) button.textContent = symbol;
    button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    button.title = dark ? "Switch to light mode" : "Switch to dark mode";
    button.setAttribute("aria-pressed", String(dark));
  };

  const applyTheme = (theme, persist = false, relayoutAllPlots = false) => {
    const nextTheme = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    if (document.body) document.body.dataset.theme = nextTheme;
    if (persist) {
      try {
        window.localStorage.setItem(THEME_KEY, nextTheme);
      } catch (_error) {
        // Storage can be unavailable in privacy-restricted browser sessions.
      }
    }
    updateThemeButton(nextTheme);
    if (relayoutAllPlots) schedulePlotlyTheme(nextTheme);
    return nextTheme;
  };

  let activeTheme = applyTheme(savedTheme() || (window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light"));

  const ensureGlobalLoader = () => {
    let loader = document.getElementById("cube-global-loader");
    if (loader || !document.body) return loader;
    loader = document.createElement("div");
    loader.id = "cube-global-loader";
    loader.className = "cube-risk-loader cube-global-loader";
    loader.hidden = true;
    loader.setAttribute("role", "status");
    loader.setAttribute("aria-live", "polite");
    const faces = ["front", "back", "right", "left", "top", "bottom"]
      .map((face) => `<i class="cube-motion__face cube-motion__face--${face}"></i>`)
      .join("");
    loader.innerHTML = `<span class="cube-motion cube-motion--loader" aria-hidden="true"><span class="cube-motion__scene"><span class="cube-motion__traveller"><span class="cube-motion__shadow"></span><span class="cube-motion__lift"><span class="cube-motion__roller"><span class="cube-motion__view"><span class="cube-motion__solid">${faces}</span></span></span></span></span></span></span><span class="cube-loader-label">Loading Cube&hellip;</span>`;
    document.body.appendChild(loader);
    registerCubeRollers(loader);
    return loader;
  };

  const dashIsLoading = () => Boolean(document.querySelector('[data-dash-is-loading="true"]'));

  const setGlobalLoaderVisible = (visible) => {
    // The global cube is refresh feedback, not generic Dash callback
    // feedback. Creating it for a tab/filter callback both obscures
    // the current table and starts a requestAnimationFrame loop while
    // React is replacing a large hierarchy.
    const loader = visible
      ? ensureGlobalLoader()
      : document.getElementById("cube-global-loader");
    if (!loader) return;
    if (!visible) {
      loader.hidden = true;
      loader.classList.remove("is-visible");
      document.body.classList.remove("cube-is-loading");
      return;
    }

    const customLoader = Array.from(document.querySelectorAll(".cube-risk-loader:not(#cube-global-loader)")).find((candidate) => {
      if (candidate.closest("#refresh-progress[hidden], [hidden]")) return false;
      const style = window.getComputedStyle(candidate);
      return style.display !== "none" && style.visibility !== "hidden" && candidate.getClientRects().length > 0;
    });
    const shouldShow = !customLoader;
    loader.hidden = !shouldShow;
    loader.classList.toggle("is-visible", shouldShow);
    document.body.classList.add("cube-is-loading");
  };

  const resetCubeRollers = () => {
    cubeRollStates.forEach((state) => {
      state.lastTimestamp = null;
      state.lastPaintTimestamp = null;
    });
    registerCubeRollers();
  };

  const stopCubeMotion = () => {
    cubeRollStopped = true;
    if (cubeRollFrame !== null) cancelAnimationFrame(cubeRollFrame);
    if (cubeRollWakeTimer !== null) clearTimeout(cubeRollWakeTimer);
  };

  const stopPlotlyTheme = () => {
    if (plotlyThemeTimer) clearTimeout(plotlyThemeTimer);
  };

  Object.defineProperty(app, "activeTheme", {
    configurable: true,
    get: () => activeTheme,
    set: (theme) => { activeTheme = theme; },
  });
  Object.assign(app, {
    applyTheme,
    dashIsLoading,
    refreshCubeRollSizes,
    registerCubeRollers,
    resetCubeRollers,
    savedTheme,
    schedulePlotlyTheme,
    setGlobalLoaderVisible,
    stopCubeMotion,
    stopPlotlyTheme,
    updateThemeButton,
  });
})();
