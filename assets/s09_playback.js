/* Data-page ProductSpec projections and isolated history playback. */
(() => {
  "use strict";

  const CAMERA = { eye: { x: 1.55, y: 1.65, z: 1.25 } };
  const ASPECT = { x: 1.30, y: 1.08, z: 0.78 };

  const dataProjectionOptions = (axisCount) => {
    if (axisCount === 0) {
      return [{ label: "Timeline", value: "zero_timeline" }];
    }
    if (axisCount === 1) {
      return [
        { label: "Tenor × date", value: "one_surface" },
        { label: "Specific tenor", value: "one_tenor" },
        { label: "Date A / B / Δ", value: "one_compare" },
      ];
    }
    if (axisCount === 2) {
      return [
        { label: "Selected-date surface", value: "two_surface" },
        { label: "Swap history", value: "two_swap" },
        { label: "Option history", value: "two_option" },
        { label: "Date A / B / Δ", value: "two_compare" },
      ];
    }
    return [];
  };

  const dataAxes = (bundle) => Array.isArray(bundle?.axes) ? bundle.axes : [];
  const dataDates = (bundle) => Array.isArray(bundle?.dates)
    ? bundle.dates.map(String)
    : [];
  const dataLabels = (axis) => Array.isArray(axis?.labels)
    ? axis.labels.map(String)
    : [];
  const retainedValue = (values, current, fallback = null) => {
    const selected = String(current ?? "");
    return values.includes(selected) ? selected : fallback;
  };
  const dropdownOptions = (values) => values.map((value) => ({
    label: value,
    value,
  }));

  const dataProjectionBase = (bundle, currentProjection, currentA, currentB) => {
    const dates = dataDates(bundle);
    const options = dataProjectionOptions(dataAxes(bundle).length);
    const values = options.map((option) => option.value);
    const projection = retainedValue(values, currentProjection, values[0] ?? null);
    const dateOptions = dropdownOptions(dates);
    return [options, projection, !dates.length || !options.length, dateOptions,
      retainedValue(dates, currentA, dates[0] ?? null), dateOptions,
      retainedValue(dates, currentB, dates.at(-1) ?? null)];
  };

  const dataSliceDefinition = (bundle, projection) => {
    const axes = dataAxes(bundle);
    if (axes.length === 1 && projection === "one_tenor") {
      return { label: axes[0]?.column || "Tenor", values: dataLabels(axes[0]) };
    }
    if (axes.length === 2 && projection === "two_swap") {
      return {
        label: `Fixed ${axes[1]?.column || "Tenor Option"}`,
        values: dataLabels(axes[1]),
      };
    }
    if (axes.length === 2 && projection === "two_option") {
      return {
        label: `Fixed ${axes[0]?.column || "Tenor Swap"}`,
        values: dataLabels(axes[0]),
      };
    }
    return { label: "Slice", values: [] };
  };

  const dataProjectionSlice = (bundle, projection, currentSlice) => {
    const definition = dataSliceDefinition(bundle, String(projection || ""));
    const compare = projection === "one_compare" || projection === "two_compare";
    return [definition.label, dropdownOptions(definition.values),
      retainedValue(definition.values, currentSlice, definition.values[0] ?? null),
      !definition.values.length,
      definition.values.length ? {} : { display: "none" },
      compare ? {} : { display: "none" }];
  };

  const dataHistoryEmptyFigure = (message) => ({
    data: [],
    layout: {
      annotations: [{
        text: String(message),
        x: 0.5,
        y: 0.5,
        xref: "paper",
        yref: "paper",
        showarrow: false,
      }],
      margin: { l: 48, r: 24, t: 48, b: 48 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      uirevision: "data-empty",
    },
  });

  const finiteNumber = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const selected = Number(value);
    return Number.isFinite(selected) ? selected : null;
  };

  const dataBoundsForValues = (values) => {
    const finite = values.map(finiteNumber).filter((value) => value !== null);
    if (!finite.length) return null;
    const lower = Math.min(...finite);
    const upper = Math.max(...finite);
    if (lower !== upper) return [lower, upper];
    const padding = Math.max(Math.abs(lower) * 0.01, 1);
    return [lower - padding, upper + padding];
  };

  const dataHistoryBounds = (records, metric) => dataBoundsForValues(
    (Array.isArray(records) ? records : []).map((record) => record?.[metric]),
  );

  const dataSymmetricBounds = (values) => {
    const bounds = dataBoundsForValues(values);
    if (!bounds) return null;
    const maximum = Math.max(Math.abs(bounds[0]), Math.abs(bounds[1]), 1);
    return [-maximum, maximum];
  };

  const dataHistoryPointMap = (records, keys, metric) => {
    const points = new Map();
    (Array.isArray(records) ? records : []).forEach((record) => {
      if (!record || typeof record !== "object") return;
      points.set(
        JSON.stringify(keys.map((key) => record[key] ?? null)),
        record[metric] ?? null,
      );
    });
    return points;
  };

  const dataHistoryPoint = (points, values) => {
    const key = JSON.stringify(values);
    return points.has(key) ? points.get(key) : null;
  };

  const dataDifference = (left, right) => {
    const a = finiteNumber(left);
    const b = finiteNumber(right);
    return a === null || b === null ? null : b - a;
  };

  const categoricalAxis = (title, labels) => ({
    title: { text: title },
    type: "category",
    categoryorder: "array",
    categoryarray: labels,
    automargin: true,
  });

  const dataScene = (xTitle, xLabels, yTitle, yLabels, metric, bounds) => ({
    xaxis: categoricalAxis(xTitle, xLabels),
    yaxis: categoricalAxis(yTitle, yLabels),
    zaxis: {
      title: { text: metric },
      ...(bounds ? { range: bounds } : {}),
    },
    camera: CAMERA,
    aspectmode: "manual",
    aspectratio: ASPECT,
  });

  const dataSurface = (x, y, z, name, bounds, extra = {}) => ({
    type: "surface",
    x,
    y,
    z,
    name,
    connectgaps: false,
    ...(bounds ? { cmin: bounds[0], cmax: bounds[1] } : {}),
    ...extra,
  });

  const oneAxisFigure = (context) => {
    const {
      axis, bounds, dateA, dateB, dateColumn, dates, metric, points,
      projection, selectedDate, slice,
    } = context;
    const column = String(axis?.column || "Tenor");
    const labels = dataLabels(axis);
    if (projection === "one_tenor") {
      const selected = retainedValue(labels, slice, labels[0] ?? null);
      return {
        data: [{
          type: "scatter",
          x: dates,
          y: dates.map((value) => dataHistoryPoint(points, [value, selected])),
          mode: "lines+markers",
          name: selected,
          connectgaps: false,
        }],
        layout: {
          xaxis: categoricalAxis("Date", dates),
          yaxis: { title: { text: metric }, range: bounds || undefined },
        },
        title: `${metric} · ${selected}`,
      };
    }
    if (projection === "one_compare") {
      const first = retainedValue(dates, dateA, dates[0]);
      const second = retainedValue(dates, dateB, dates.at(-1));
      const valuesA = labels.map((label) => dataHistoryPoint(points, [first, label]));
      const valuesB = labels.map((label) => dataHistoryPoint(points, [second, label]));
      const difference = valuesA.map((value, index) => dataDifference(
        value,
        valuesB[index],
      ));
      const range = dataBoundsForValues([...valuesA, ...valuesB, ...difference]);
      return {
        data: [
          { x: labels, y: valuesA, name: `Date A · ${first}` },
          { x: labels, y: valuesB, name: `Date B · ${second}` },
          { x: labels, y: difference, name: "B − A" },
        ].map((trace) => ({
          type: "scatter",
          mode: "lines+markers",
          connectgaps: false,
          ...trace,
        })),
        layout: {
          xaxis: categoricalAxis(column, labels),
          yaxis: { title: { text: metric }, range: range || undefined },
        },
        title: `${metric} · ${first} / ${second} / B − A`,
      };
    }
    return {
      data: [
        dataSurface(
          labels,
          dates,
          dates.map((value) => labels.map(
            (label) => dataHistoryPoint(points, [value, label]),
          )),
          "History",
          bounds,
          { colorbar: { title: { text: metric } } },
        ),
        {
          type: "scatter3d",
          x: labels,
          y: labels.map(() => selectedDate),
          z: labels.map((label) => dataHistoryPoint(points, [selectedDate, label])),
          mode: "lines+markers",
          name: selectedDate,
          connectgaps: false,
          line: { color: "#101828", width: 6 },
        },
      ],
      layout: { scene: dataScene(column, labels, "Date", dates, metric, bounds) },
      title: `${metric} · ${selectedDate}`,
    };
  };

  const twoAxisComparison = (context) => {
    const {
      bounds, dateA, dateB, dates, firstColumn, firstLabels, metric,
      points, secondColumn, secondLabels,
    } = context;
    const first = retainedValue(dates, dateA, dates[0]);
    const second = retainedValue(dates, dateB, dates.at(-1));
    const grid = (selectedDate) => secondLabels.map((secondLabel) => (
      firstLabels.map((firstLabel) => dataHistoryPoint(
        points,
        [selectedDate, firstLabel, secondLabel],
      ))
    ));
    const gridA = grid(first);
    const gridB = grid(second);
    const difference = gridA.map((row, rowIndex) => row.map(
      (value, columnIndex) => dataDifference(value, gridB[rowIndex][columnIndex]),
    ));
    const differenceBounds = dataSymmetricBounds(difference.flat());
    const scene = (domain) => ({
      ...dataScene(
        firstColumn,
        firstLabels,
        secondColumn,
        secondLabels,
        metric,
        bounds,
      ),
      domain: { x: domain, y: [0, 1] },
    });
    return {
      data: [
        dataSurface(firstLabels, secondLabels, gridA, `Date A · ${first}`, bounds, {
          scene: "scene",
          showscale: false,
        }),
        dataSurface(firstLabels, secondLabels, gridB, `Date B · ${second}`, bounds, {
          scene: "scene2",
          showscale: false,
        }),
        dataSurface(firstLabels, secondLabels, difference, "B − A", differenceBounds, {
          scene: "scene3",
          colorscale: "RdBu",
          reversescale: true,
          colorbar: { title: { text: "B − A" }, thickness: 12 },
        }),
      ],
      layout: {
        scene: scene([0, 0.31]),
        scene2: scene([0.345, 0.655]),
        scene3: {
          ...scene([0.69, 1]),
          zaxis: {
            title: { text: "B − A" },
            ...(differenceBounds ? { range: differenceBounds } : {}),
          },
        },
        annotations: [
          { text: `Date A · ${first}`, x: 0.155, y: 1.05 },
          { text: `Date B · ${second}`, x: 0.50, y: 1.05 },
          { text: "B − A", x: 0.845, y: 1.05 },
        ].map((item) => ({
          ...item,
          xref: "paper",
          yref: "paper",
          showarrow: false,
        })),
      },
      title: `${metric} · ${first} / ${second} / B − A`,
    };
  };

  const twoAxisFigure = (context) => {
    const {
      axes, bounds, dateA, dateB, dateColumn, dates, metric, points,
      projection, selectedDate, slice,
    } = context;
    const firstColumn = String(axes[0]?.column || "Tenor Swap");
    const secondColumn = String(axes[1]?.column || "Tenor Option");
    const firstLabels = dataLabels(axes[0]);
    const secondLabels = dataLabels(axes[1]);
    const shared = {
      bounds, dateA, dateB, dateColumn, dates, firstColumn, firstLabels,
      metric, points, secondColumn, secondLabels,
    };
    if (projection === "two_compare") return twoAxisComparison(shared);
    if (projection === "two_swap") {
      const selected = retainedValue(secondLabels, slice, secondLabels[0] ?? null);
      return {
        data: [dataSurface(
          firstLabels,
          dates,
          dates.map((value) => firstLabels.map(
            (label) => dataHistoryPoint(points, [value, label, selected]),
          )),
          `Fixed ${secondColumn} · ${selected}`,
          bounds,
          { colorbar: { title: { text: metric } } },
        )],
        layout: {
          scene: dataScene(firstColumn, firstLabels, "Date", dates, metric, bounds),
        },
        title: `${metric} · fixed ${secondColumn} ${selected}`,
      };
    }
    if (projection === "two_option") {
      const selected = retainedValue(firstLabels, slice, firstLabels[0] ?? null);
      return {
        data: [dataSurface(
          secondLabels,
          dates,
          dates.map((value) => secondLabels.map(
            (label) => dataHistoryPoint(points, [value, selected, label]),
          )),
          `Fixed ${firstColumn} · ${selected}`,
          bounds,
          { colorbar: { title: { text: metric } } },
        )],
        layout: {
          scene: dataScene(secondColumn, secondLabels, "Date", dates, metric, bounds),
        },
        title: `${metric} · fixed ${firstColumn} ${selected}`,
      };
    }
    return {
      data: [dataSurface(
        firstLabels,
        secondLabels,
        secondLabels.map((secondLabel) => firstLabels.map(
          (firstLabel) => dataHistoryPoint(
            points,
            [selectedDate, firstLabel, secondLabel],
          ),
        )),
        selectedDate,
        bounds,
        { colorbar: { title: { text: metric } } },
      )],
      layout: {
        scene: dataScene(
          firstColumn,
          firstLabels,
          secondColumn,
          secondLabels,
          metric,
          bounds,
        ),
      },
      title: `${metric} · ${selectedDate}`,
    };
  };

  const dataHistoryFigure = (
    bundle, selectedIndex, projection, slice, dateA, dateB, playerKey,
  ) => {
    const dates = dataDates(bundle);
    if (!dates.length) {
      return dataHistoryEmptyFigure("No archived rows match this request.");
    }
    const axes = dataAxes(bundle);
    const allowed = dataProjectionOptions(axes.length).map((option) => option.value);
    const selectedProjection = retainedValue(allowed, projection, allowed[0]);
    const index = Math.max(0, Math.min(Number(selectedIndex) || 0, dates.length - 1));
    const selectedDate = dates[index];
    const metric = String(bundle.metric_column || "Value");
    const dateColumn = String(bundle.date_column || "Date");
    const records = Array.isArray(bundle.values) ? bundle.values : [];
    const bounds = dataHistoryBounds(records, metric);
    const keys = [dateColumn, ...axes.map((axis) => String(axis.column))];
    const points = dataHistoryPointMap(records, keys, metric);
    let result;
    if (!axes.length) {
      result = {
        data: [{
          type: "scatter",
          x: dates,
          y: dates.map((value) => dataHistoryPoint(points, [value])),
          mode: "lines+markers",
          name: metric,
          connectgaps: false,
        }],
        layout: {
          xaxis: categoricalAxis("Date", dates),
          yaxis: { title: { text: metric }, range: bounds || undefined },
        },
        title: `${metric} history`,
      };
    } else if (axes.length === 1) {
      result = oneAxisFigure({
        axis: axes[0], bounds, dateA, dateB, dateColumn, dates, metric, points,
        projection: selectedProjection, selectedDate, slice,
      });
    } else if (axes.length === 2) {
      result = twoAxisFigure({
        axes, bounds, dateA, dateB, dateColumn, dates, metric, points,
        projection: selectedProjection, selectedDate, slice,
      });
    } else {
      return dataHistoryEmptyFigure("This ProductSpec has too many plot axes.");
    }
    return {
      data: result.data,
      layout: {
        ...result.layout,
        autosize: true,
        hoverlabel: { align: "left", namelength: -1 },
        legend: { orientation: "h", y: -0.14 },
        margin: { l: 48, r: 24, t: 64, b: 64 },
        paper_bgcolor: "#ffffff",
        plot_bgcolor: "#ffffff",
        title: { text: result.title, x: 0.01 },
        uirevision: playerKey,
      },
    };
  };

  const dataSliderMarks = (dates) => {
    if (!dates.length) return {};
    const indexes = dates.length <= 8
      ? dates.map((_value, index) => index)
      : [...new Set([0, Math.floor(dates.length / 3),
        Math.floor(2 * dates.length / 3), dates.length - 1])]
        .sort((left, right) => left - right);
    return Object.fromEntries(indexes.map((index) => [index, dates[index]]));
  };

  const emptyDataPlayback = (message, pill = "No date") => [
    dataHistoryEmptyFigure(message),
    [],
    [],
    0,
    0,
    {},
    0,
    true,
    pill,
    "Play",
    true,
    true,
    { playing: false, index: 0, key: null },
    { display: "none" },
  ];

  const dataPlayback = (
    bundle, projection, slice, dateA, dateB, buttonClicks, intervalTicks,
    sliderValue, resetGeneration, cacheState, visibilityState, playerState,
  ) => {
    if (!bundle || typeof bundle !== "object") {
      return emptyDataPlayback("Open an identity to load its history.");
    }
    const currentReset = Number(resetGeneration ?? 0);
    const bundleReset = Number(bundle.reset_generation);
    const currentGeneration = cacheState?.generation;
    if (
      !Number.isInteger(currentReset)
      || !Number.isInteger(bundleReset)
      || currentReset !== bundleReset
      || bundle.generation !== currentGeneration
    ) {
      return emptyDataPlayback(
        "History changed. Reopen this identity to continue.",
        "History reset",
      );
    }

    const dates = dataDates(bundle);
    if (!dates.length) {
      const empty = emptyDataPlayback("No archived rows match this request.");
      empty[12] = { playing: false, index: 0, key: String(bundle.key || "") };
      return empty;
    }
    const axes = dataAxes(bundle);
    const allowed = dataProjectionOptions(axes.length).map((option) => option.value);
    const selectedProjection = retainedValue(allowed, projection, allowed[0]);
    const definition = dataSliceDefinition(bundle, selectedProjection);
    const selectedSlice = retainedValue(
      definition.values,
      slice,
      definition.values[0] ?? null,
    );
    const selectedA = retainedValue(dates, dateA, dates[0]);
    const selectedB = retainedValue(dates, dateB, dates.at(-1));
    const key = JSON.stringify(["data-history-chart", String(bundle.key || ""),
      selectedProjection, selectedSlice, selectedA, selectedB]);
    const prior = playerState && typeof playerState === "object" ? playerState : {};
    const clicks = Math.max(0, Number(buttonClicks) || 0);
    const ticks = Math.max(0, Number(intervalTicks) || 0);
    const changedIdentity = prior.key !== key;
    let index = Number.isInteger(Number(prior.index))
      ? Number(prior.index)
      : dates.length - 1;
    index = Math.max(0, Math.min(index, dates.length - 1));
    let playing = Boolean(prior.playing) && !changedIdentity;
    const hidden = Boolean(visibilityState?.hidden) || document.hidden;

    if (changedIdentity) {
      index = dates.length - 1;
      playing = false;
    } else if (hidden) {
      playing = false;
    } else if (clicks !== Number(prior.button_clicks ?? clicks)) {
      playing = !playing;
    } else if (ticks !== Number(prior.interval_ticks ?? ticks) && playing) {
      index = (index + 1) % dates.length;
    } else {
      const requestedIndex = Number(sliderValue);
      if (Number.isInteger(requestedIndex) && requestedIndex !== index) {
        index = Math.max(0, Math.min(requestedIndex, dates.length - 1));
        playing = false;
      }
    }

    const hasPlayer = dates.length > 1 && (
      (axes.length === 1 && selectedProjection === "one_surface")
      || (axes.length === 2 && selectedProjection === "two_surface")
    );
    if (!hasPlayer) playing = false;
    const compare = selectedProjection === "one_compare"
      || selectedProjection === "two_compare";
    const selectedDate = compare ? selectedB : dates[index];
    const dateColumn = String(bundle.date_column || "");
    const records = Array.isArray(bundle.values) ? bundle.values : [];
    const selectedRows = records.filter(
      (record) => record && String(record[dateColumn] ?? "") === selectedDate,
    );
    const selectedColumns = Object.keys(records[0] || {}).map((column) => ({
      name: column,
      id: column,
    }));
    const state = {
      playing, index, key, projection: selectedProjection, slice: selectedSlice,
      date_a: selectedA, date_b: selectedB, button_clicks: clicks,
      interval_ticks: ticks,
    };
    return [
      dataHistoryFigure(
        bundle,
        index,
        selectedProjection,
        selectedSlice,
        selectedA,
        selectedB,
        key,
      ),
      selectedRows,
      selectedColumns,
      0,
      dates.length - 1,
      dataSliderMarks(dates),
      index,
      !hasPlayer,
      selectedDate,
      playing ? "Pause" : "Play",
      !hasPlayer,
      !playing,
      state,
      hasPlayer ? {} : { display: "none" },
    ];
  };

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    cube: Object.assign({}, window.dash_clientside?.cube, {
      dataPlayback,
      dataProjectionBase,
      dataProjectionSlice,
    }),
  });

})();
