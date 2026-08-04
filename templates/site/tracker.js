/* Chart bootstrapping + soft reveal for the press-facing tracker. */
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
    "#0f2f52",
    "#c45c26",
    "#1b6b48",
    "#9a2f46",
    "#4a5d70",
    "#8a6528",
    "#2f6f8f",
    "#5c6b7a",
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
        cutout: "58%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 10, font: { size: 11, family: "Sora" } },
          },
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
            backgroundColor: "#0f2f52",
            borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: {
              maxRotation: 40,
              minRotation: 0,
              font: { size: 10, family: "Sora" },
            },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0, font: { family: "Sora" } },
            grid: { color: "rgba(15, 47, 82, 0.08)" },
          },
        },
      },
    };
  });
})();
