/* ==========================================================================
   SEINFRA UFG — Painel de Obras
   app.js
   ========================================================================== */

const STATUS_META = {
  "Em Andamento": { classe: "andamento", cor: "#4ea8ff" },
  "Concluída":    { classe: "concluida", cor: "#4ade80" },
  "Atrasada":     { classe: "atrasada",  cor: "#ff5d6c" },
  "Paralisada":   { classe: "paralisada", cor: "#7c8aa5" },
};

const RECURSO_CORES = {
  "Próprio UFG": "#23e5c9",
  "Terceirizado/PAC": "#ffb545",
};
const RECURSO_COR_FALLBACK = ["#9b8cff", "#4ea8ff", "#ff5d6c"];

let TODAS_OBRAS = [];
let map = null;
let markersLayer = null;
let chartRecurso = null;
let chartFiscal = null;

/* --------------------------------------------------------------------
   Bootstrap
   -------------------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", async () => {
  iniciarRelogio();
  await carregarDados();
  popularFiltros(TODAS_OBRAS);
  inicializarMapa();
  inicializarGraficos();
  aplicarFiltros();

  document.querySelectorAll(".header__filters select").forEach((select) => {
    select.addEventListener("change", aplicarFiltros);
  });
  document.getElementById("btn-reset").addEventListener("click", () => {
    document.querySelectorAll(".header__filters select").forEach((s) => (s.value = ""));
    aplicarFiltros();
  });

  // Reavalia o tamanho do mapa após o layout estabilizar (evita tiles cinzas).
  window.addEventListener("resize", () => map && map.invalidateSize());
  setTimeout(() => map && map.invalidateSize(), 300);
});

/* --------------------------------------------------------------------
   Relógio em tempo real
   -------------------------------------------------------------------- */
function iniciarRelogio() {
  const atualizar = () => {
    const agora = new Date();
    document.getElementById("clock-time").textContent = agora.toLocaleTimeString("pt-BR");
    document.getElementById("clock-date").textContent = agora.toLocaleDateString("pt-BR", {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  };
  atualizar();
  setInterval(atualizar, 1000);
}

/* --------------------------------------------------------------------
   Carregamento de dados.json
   -------------------------------------------------------------------- */
async function carregarDados() {
  const badge = document.getElementById("sync-badge");
  try {
    const resp = await fetch("dados.json", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    TODAS_OBRAS = Array.isArray(json.obras) ? json.obras : [];

    const atualizadoEm = json.atualizado_em
      ? new Date(json.atualizado_em).toLocaleString("pt-BR")
      : "--";
    document.getElementById("footer-updated").textContent = `Última sincronização: ${atualizadoEm}`;

    badge.classList.remove("sync-badge--erro");
  } catch (err) {
    console.error("Falha ao carregar dados.json:", err);
    TODAS_OBRAS = [];
    badge.querySelector(":scope").innerHTML = '<span class="sync-dot"></span> FALHA NA SINC.';
    badge.style.color = "#ff5d6c";
  }
}

/* --------------------------------------------------------------------
   Filtros dinâmicos
   -------------------------------------------------------------------- */
function popularFiltros(obras) {
  const nomesUnicos = (campo, transform) => {
    const set = new Set();
    obras.forEach((o) => {
      const v = transform ? transform(o[campo]) : o[campo];
      if (Array.isArray(v)) v.forEach((x) => x && set.add(x));
      else if (v) set.add(v);
    });
    return [...set].sort((a, b) => a.localeCompare(b, "pt-BR"));
  };

  preencherSelect("f-obra", nomesUnicos("obra"));
  preencherSelect("f-fiscal", nomesUnicos("fiscais"));
  preencherSelect("f-status", nomesUnicos("status"));
  preencherSelect("f-recurso", nomesUnicos("recurso"));
}

function preencherSelect(id, valores) {
  const select = document.getElementById(id);
  const atual = select.value;
  select.querySelectorAll("option:not(:first-child)").forEach((o) => o.remove());
  valores.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  });
  if (valores.includes(atual)) select.value = atual;
}

function obrasFiltradas() {
  const fObra = document.getElementById("f-obra").value;
  const fFiscal = document.getElementById("f-fiscal").value;
  const fStatus = document.getElementById("f-status").value;
  const fRecurso = document.getElementById("f-recurso").value;

  return TODAS_OBRAS.filter((o) => {
    if (fObra && o.obra !== fObra) return false;
    if (fStatus && o.status !== fStatus) return false;
    if (fRecurso && o.recurso !== fRecurso) return false;
    if (fFiscal && !(o.fiscais || []).includes(fFiscal)) return false;
    return true;
  });
}

function aplicarFiltros() {
  const obras = obrasFiltradas();
  atualizarKPIs(obras);
  atualizarMapa(obras);
  atualizarGraficoRecurso(obras);
  atualizarGraficoFiscal(obras);
  atualizarTabela(obras);
}

/* --------------------------------------------------------------------
   Formatação
   -------------------------------------------------------------------- */
const formatoMoeda = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});

function formatarData(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return "—";
  return d.toLocaleDateString("pt-BR");
}

/* --------------------------------------------------------------------
   KPIs
   -------------------------------------------------------------------- */
function atualizarKPIs(obras) {
  const total = obras.length;
  const valorTotal = obras.reduce((acc, o) => acc + (o.valor_total || 0), 0);
  const media = total ? valorTotal / total : 0;

  const hoje = new Date();
  const noPrazo = obras.filter((o) => {
    if (o.status === "Concluída") return true;
    if (!o.previsao_termino) return true;
    const termino = new Date(o.previsao_termino + "T00:00:00");
    return termino >= hoje;
  }).length;
  const pctPrazo = total ? Math.round((noPrazo / total) * 100) : 0;

  document.getElementById("kpi-valor").textContent = formatoMoeda.format(valorTotal);
  document.getElementById("kpi-total").textContent = total;
  document.getElementById("kpi-media").textContent = formatoMoeda.format(media);
  document.getElementById("kpi-prazo").textContent = `${pctPrazo}%`;
}

/* --------------------------------------------------------------------
   Mapa (Leaflet + CartoDB Dark Matter)
   -------------------------------------------------------------------- */
function inicializarMapa() {
  map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
  }).setView([-16.6047, -49.2647], 11);

  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
    }
  ).addTo(map);

  markersLayer = L.layerGroup().addTo(map);
}

function atualizarMapa(obras) {
  if (!map) return;
  markersLayer.clearLayers();

  const pontos = obras.filter((o) => o.latitude && o.longitude);
  document.getElementById("map-count").textContent = `${pontos.length} pontos`;

  pontos.forEach((o) => {
    const meta = STATUS_META[o.status] || { cor: "#7c8aa5" };
    const marker = L.circleMarker([o.latitude, o.longitude], {
      radius: 8,
      color: meta.cor,
      weight: 2,
      fillColor: meta.cor,
      fillOpacity: 0.55,
    });

    const fiscais = (o.fiscais || []).join(", ") || "—";
    marker.bindPopup(`
      <div class="popup-obra">
        <strong>${escapeHtml(o.obra)}</strong>
        <span>Fiscal: ${escapeHtml(fiscais)}</span>
        <span>Valor: ${formatoMoeda.format(o.valor_total || 0)}</span>
        <span>Status: ${escapeHtml(o.status || "—")}</span>
      </div>
    `);

    markersLayer.addLayer(marker);
  });

  if (pontos.length) {
    const bounds = L.latLngBounds(pontos.map((p) => [p.latitude, p.longitude]));
    map.fitBounds(bounds.pad(0.25));
  }
  requestAnimationFrame(() => map.invalidateSize());
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* --------------------------------------------------------------------
   Gráfico de Rosca — Distribuição por Recurso
   -------------------------------------------------------------------- */
function inicializarGraficos() {
  const ctxDonut = document.getElementById("chart-recurso").getContext("2d");
  chartRecurso = new Chart(ctxDonut, {
    type: "doughnut",
    data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderWidth: 0 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: { display: false },
        datalabels: {
          color: "#ffffff",
          font: { family: "Inter", weight: "700", size: 13 },
          formatter: (value, ctx) => {
            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
            if (!total) return "";
            const pct = (value / total) * 100;
            return pct >= 4 ? `${pct.toFixed(1)}%` : "";
          },
        },
        tooltip: {
          backgroundColor: "#111928",
          borderColor: "#29405c",
          borderWidth: 1,
          titleFont: { family: "Inter", weight: "700" },
          bodyFont: { family: "JetBrains Mono" },
        },
      },
    },
    plugins: [ChartDataLabels],
  });

  const ctxBars = document.getElementById("chart-fiscal").getContext("2d");
  chartFiscal = new Chart(ctxBars, {
    type: "bar",
    data: {
      labels: [],
      datasets: [{
        label: "Obras",
        data: [],
        backgroundColor: "#23e5c9",
        borderRadius: 6,
        maxBarThickness: 28,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        datalabels: {
          color: "#e8edf5",
          anchor: "end",
          align: "right",
          font: { family: "JetBrains Mono", weight: "600", size: 11 },
        },
        tooltip: {
          backgroundColor: "#111928",
          borderColor: "#29405c",
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          ticks: { color: "#56657f", font: { family: "JetBrains Mono", size: 10 }, precision: 0 },
          grid: { color: "rgba(30,41,59,0.6)" },
        },
        y: {
          ticks: { color: "#8b9bb4", font: { family: "Inter", size: 11 } },
          grid: { display: false },
        },
      },
    },
    plugins: [ChartDataLabels],
  });
}

function atualizarGraficoRecurso(obras) {
  const contagem = {};
  obras.forEach((o) => {
    const chave = o.recurso || "Não informado";
    contagem[chave] = (contagem[chave] || 0) + 1;
  });

  const labels = Object.keys(contagem);
  const dados = Object.values(contagem);
  const cores = labels.map(
    (l, i) => RECURSO_CORES[l] || RECURSO_COR_FALLBACK[i % RECURSO_COR_FALLBACK.length]
  );

  chartRecurso.data.labels = labels;
  chartRecurso.data.datasets[0].data = dados;
  chartRecurso.data.datasets[0].backgroundColor = cores;
  chartRecurso.update();

  const legendEl = document.getElementById("legend-recurso");
  legendEl.innerHTML = "";
  labels.forEach((l, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="dot" style="background:${cores[i]}"></span>${l}`;
    legendEl.appendChild(li);
  });
}

function atualizarGraficoFiscal(obras) {
  const contagem = {};
  obras.forEach((o) => {
    (o.fiscais || []).forEach((f) => {
      contagem[f] = (contagem[f] || 0) + 1;
    });
  });

  const entradas = Object.entries(contagem).sort((a, b) => b[1] - a[1]);

  chartFiscal.data.labels = entradas.map((e) => e[0]);
  chartFiscal.data.datasets[0].data = entradas.map((e) => e[1]);
  chartFiscal.update();
}

/* --------------------------------------------------------------------
   Tabela resumo
   -------------------------------------------------------------------- */
function atualizarTabela(obras) {
  const tbody = document.getElementById("tabela-body");
  tbody.innerHTML = "";

  document.getElementById("table-count").textContent = `${obras.length} registros`;

  obras
    .slice()
    .sort((a, b) => (b.valor_total || 0) - (a.valor_total || 0))
    .forEach((o) => {
      const meta = STATUS_META[o.status] || { classe: "paralisada" };
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(o.obra)}</td>
        <td class="col-fiscais">${escapeHtml((o.fiscais || []).join(", ") || "—")}</td>
        <td>${escapeHtml(o.recurso || "—")}</td>
        <td class="col-valor">${formatoMoeda.format(o.valor_total || 0)}</td>
        <td>${formatarData(o.previsao_termino)}</td>
        <td><span class="badge badge--${meta.classe}">${escapeHtml(o.status || "—")}</span></td>
      `;
      tbody.appendChild(tr);
    });
}
