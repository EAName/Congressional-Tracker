/* Chart bootstrapping for the static tracker pages. */
(function () {
  function boot(id, config) {
    var el = document.getElementById(id);
    if (!el || typeof Chart === "undefined") return;
    var raw = el.getAttribute("data-chart");
    if (!raw) return;
    var payload = JSON.parse(raw);
    new Chart(el, config(payload));
  }

  var palette = [
    "#143a5c",
    "#c45c26",
    "#1f6b4a",
    "#8b2942",
    "#4a6074",
    "#9a6b2f",
    "#2f6f8f",
    "#6b4c9a",
  ];

  boot("categoryChart", function (payload) {
    return {
      type: "doughnut",
      data: {
        labels: payload.labels,
        datasets: [
          {
            data: payload.values,
            backgroundColor: palette,
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
      },
    };
  });

  boot("impactChart", function (payload) {
    return {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: [
          {
            data: payload.values,
            backgroundColor: "#143a5c",
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxRotation: 45, minRotation: 0, font: { size: 10 } } },
          y: { beginAtZero: true, ticks: { precision: 0 } },
        },
      },
    };
  });
})();
