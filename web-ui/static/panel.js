let chEvents=null, chMix=null, chTypes=null, chFunnel=null, chActions=null, chTS=null, chRevTS=null;

function money(v){
  if (v === null || v === undefined || isNaN(v)) return "0 ₽";
  return new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 0}).format(v) + " ₽";
}
function pct(v){
  if (v === null || v === undefined || isNaN(v)) return "0.00%";
  return (v*100).toFixed(2) + "%";
}
function set(id, val){
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function chartDefaults(){
  if (!window.Chart) return;
  Chart.defaults.color = "rgba(241,244,255,.78)";
  Chart.defaults.borderColor = "rgba(255,255,255,.12)";
  Chart.defaults.font.family = "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial";
  Chart.defaults.font.size = 11;
}

function destroyChart(ch){
  if (ch && ch.destroy) ch.destroy();
}

async function loadObzor(){
  chartDefaults();
  const minutes = Number(document.getElementById("o_minutes")?.value || 60);

  const r = await fetch(`/api/obzor?minutes=${minutes}`);
  const d = await r.json();

  set("o_upd", d.generated_at);

  set("k_total", d.total_events);
  set("k_views", d.views);
  set("k_atc", pct(d.add_to_cart_rate));
  set("k_cr", pct(d.conversion));

  set("k_rev", money(d.shop_revenue));
  set("k_aov", money(d.aov));
  set("k_ref", money(d.refunds_sum));
  set("k_net", money(d.net_shop_revenue));

  set("k_don", money(d.donations_sum));
  set("k_char", money(d.charity_item_revenue));
  set("k_fail_rate", pct(d.pay_fail_rate));
  set("k_fail_don", d.fail_donations || 0);

  // line: events per minute
  const L = (d.per_min || []).map(x=>x.t);
  const V = (d.per_min || []).map(x=>x.c);
  const c1 = document.getElementById("c_events");
  if (c1){
    destroyChart(chEvents);
    chEvents = new Chart(c1, {
      type:"line",
      data:{
        labels:L,
        datasets:[{
          label:"events",
          data:V,
          borderColor:"#39D6FF",
          backgroundColor:"rgba(57,214,255,.10)",
          fill:true,
          tension:.32,
          borderWidth:2
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{ x:{display:false}, y:{beginAtZero:true} }
      }
    });
  }

  // doughnut: revenue mix
  const c2 = document.getElementById("c_mix");
  if (c2){
    destroyChart(chMix);

    const shopRev = d.shop_revenue || 0;
    const charityRev = d.charity_item_revenue || 0;
    const donRev = d.donations_sum || 0;
    const total = shopRev + charityRev + donRev;

    if (total > 0){
      chMix = new Chart(c2, {
        type:"doughnut",
        data:{
          labels:["Магазин","Корм для приюта","Донаты"],
          datasets:[{
            data:[shopRev, charityRev, donRev],
            backgroundColor:["#22F2A6","#FF4AD8","#39D6FF"],
            borderWidth:0
          }]
        },
        options:{
          responsive:true,
          maintainAspectRatio:false,
          cutout:"70%",
          plugins:{
            legend:{position:"bottom"},
            tooltip:{
              callbacks:{
                label: (ctx) => {
                  const label = ctx.label || "";
                  const value = ctx.parsed || 0;
                  const p = total ? ((value/total)*100).toFixed(1) : "0.0";
                  return `${label}: ${money(value)} (${p}%)`;
                }
              }
            }
          }
        }
      });
    }
  }

  // bar: event types
  const c3 = document.getElementById("c_types");
  if (c3){
    destroyChart(chTypes);

    const top = (d.by_event || []).slice(0, 10);
    const l2 = top.map(x=>x.k);
    const v2 = top.map(x=>x.c);

    chTypes = new Chart(c3, {
      type:"bar",
      data:{
        labels:l2,
        datasets:[{
          data:v2,
          backgroundColor:"rgba(34,242,166,.18)",
          borderColor:"rgba(34,242,166,.55)",
          borderWidth:1
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        indexAxis:'y',
        plugins:{legend:{display:false}},
        scales:{ x:{beginAtZero:true} }
      }
    });
  }
}

async function loadVoronka(){
  chartDefaults();
  const minutes = Number(document.getElementById("f_minutes")?.value || 120);

  const r = await fetch(`/api/voronka?minutes=${minutes}`);
  const d = await r.json();

  set("f_upd", d.generated_at);

  set("f_views", d.views);
  set("f_atc", d.add_to_cart);
  set("f_coupon", d.coupon_applied);
  set("f_delivery", d.delivery_selected);
  set("f_paid", d.paid);
  set("f_failed", d.failed);
  set("f_ref", d.refunded);
  set("f_rates", `${pct(d.conversion)} / ${pct(d.fail_rate)} / ${pct(d.refund_rate_paid)}`);

  const c = document.getElementById("c_funnel");
  if (c){
    destroyChart(chFunnel);

    chFunnel = new Chart(c, {
      type:"bar",
      data:{
        labels:["Просмотры","Корзина","Купон","Доставка","Оплачено","Возвраты"],
        datasets:[{
          data:[d.views, d.add_to_cart, d.coupon_applied, d.delivery_selected, d.paid, d.refunded],
          backgroundColor:[
            "rgba(57,214,255,.16)","rgba(34,242,166,.16)","rgba(255,74,216,.16)",
            "rgba(255,176,32,.16)","rgba(34,242,166,.28)","rgba(255,77,109,.22)"
          ],
          borderColor:["#39D6FF","#22F2A6","#FF4AD8","#FFB020","#22F2A6","#FF4D6D"],
          borderWidth:1
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{ y:{beginAtZero:true} }
      }
    });
  }
}

async function loadTovarList(){
  const sel = document.getElementById("p_product");
  if (!sel) return;

  const r = await fetch(`/api/tovary/list?minutes=4320`);
  const d = await r.json();

  sel.innerHTML = "";
  for (const name of (d.items || [])){
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  }
  if ((d.items || []).length > 0) sel.value = d.items[0];
}

async function loadTovar(){
  chartDefaults();
  const product = document.getElementById("p_product")?.value;
  const minutes = Number(document.getElementById("p_minutes")?.value || 180);
  const activity = document.getElementById("p_activity")?.value || "all";
  if (!product) return;

  const url = `/api/tovar/stat?product=${encodeURIComponent(product)}&minutes=${minutes}&activity=${encodeURIComponent(activity)}`;
  const r = await fetch(url);
  const d = await r.json();

  set("p_upd", d.generated_at);
  set("p_total", d.total_events);
  set("p_rev", money(d.revenue_total));

  const topE = (d.top_users_events || [])[0];
  const topR = (d.top_users_revenue || [])[0];
  set("p_top_e", topE ? `${topE.user_id} (${topE.events})` : "—");
  set("p_top_r", topR ? `${topR.user_id} (${money(topR.revenue)})` : "—");

  // actions bar
  const aL = (d.by_action || []).map(x=>x.k);
  const aV = (d.by_action || []).map(x=>x.c);
  const c1 = document.getElementById("c_actions");
  if (c1){
    destroyChart(chActions);
    chActions = new Chart(c1, {
      type:"bar",
      data:{ labels:aL, datasets:[{ data:aV, backgroundColor:"rgba(255,74,216,.16)", borderColor:"rgba(255,74,216,.50)", borderWidth:1 }]},
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{ y:{beginAtZero:true} } }
    });
  }

  // events time series
  const eL = (d.events_per_min || []).map(x=>x.t);
  const eV = (d.events_per_min || []).map(x=>x.c);
  const c2 = document.getElementById("c_ts");
  if (c2){
    destroyChart(chTS);
    chTS = new Chart(c2, {
      type:"line",
      data:{ labels:eL, datasets:[{ data:eV, borderColor:"#39D6FF", backgroundColor:"rgba(57,214,255,.10)", fill:true, tension:.32, borderWidth:2 }]},
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{ x:{display:false}, y:{beginAtZero:true} } }
    });
  }

  // revenue time series
  const rL = (d.revenue_per_min || []).map(x=>x.t);
  const rV = (d.revenue_per_min || []).map(x=>x.v);
  const c3 = document.getElementById("c_rev_ts");
  if (c3){
    destroyChart(chRevTS);
    chRevTS = new Chart(c3, {
      type:"line",
      data:{ labels:rL, datasets:[{ data:rV, borderColor:"#22F2A6", backgroundColor:"rgba(34,242,166,.10)", fill:true, tension:.32, borderWidth:2 }]},
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{ x:{display:false}, y:{beginAtZero:true} } }
    });
  }

  // users table
  const map = new Map();
  for (const u of (d.top_users_events || [])) map.set(String(u.user_id), {events:u.events, revenue:0});
  for (const u of (d.top_users_revenue || [])){
    const k = String(u.user_id);
    const cur = map.get(k) || {events:0, revenue:0};
    cur.revenue = u.revenue;
    map.set(k, cur);
  }

  const rows = Array.from(map.entries())
    .map(([user, v]) => ({user, events:v.events||0, revenue:v.revenue||0}))
    .sort((a,b)=> (b.revenue - a.revenue) || (b.events - a.events))
    .slice(0, 10);

  const tbody = document.getElementById("u_rows");
  if (tbody){
    tbody.innerHTML = "";
    for (const row of rows){
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="mono">${row.user}</td><td class="mono">${row.events}</td><td class="mono">${Math.round(row.revenue)} ₽</td>`;
      tbody.appendChild(tr);
    }
  }
}

function setActiveNavLink(){
  const path = window.location.pathname;
  const links = document.querySelectorAll('.menu .m');
  links.forEach(link => {
    link.classList.remove('active');
    if (link.getAttribute('href') === path) link.classList.add('active');
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setActiveNavLink();

  if (document.getElementById("o_minutes")) loadObzor();
  if (document.getElementById("f_minutes")) loadVoronka();
  if (document.getElementById("p_product")) {
    loadTovarList().then(() => {
      if (document.getElementById("p_product").value) loadTovar();
    });
  }
});