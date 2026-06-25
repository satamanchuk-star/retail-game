// Клиент показывает живой срез мира и делает результат симуляции видимым.
const formatRub = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 });
const metricRoot = document.querySelector('#metrics');
const mapRoot = document.querySelector('#map');
const productsRoot = document.querySelector('#products');
const inventoryBatchesRoot = document.querySelector('#inventory-batches');
const rawMaterialsRoot = document.querySelector('#raw-materials');
const assetsRoot = document.querySelector('#assets');
const newsRoot = document.querySelector('#news');
const companiesRoot = document.querySelector('#companies');
const regionSelect = document.querySelector('#region-select');
const companySelect = document.querySelector('#company-select');
const simulateButton = document.querySelector('#simulate');
const runDemoButton = document.querySelector('#run-demo');
const resetButton = document.querySelector('#reset');
const companyForm = document.querySelector('#company-form');
const decisionForm = document.querySelector('#decision-form');
const contractForm = document.querySelector('#contract-form');
const loanForm = document.querySelector('#loan-form');
const sellerSelect = document.querySelector('#seller-select');
const buyerSelect = document.querySelector('#buyer-select');
const productSelect = document.querySelector('#product-select');
const dueDayInput = document.querySelector('#due-day');
const ratingsRoot = document.querySelector('#ratings');
const contractsRoot = document.querySelector('#contracts');
const banksRoot = document.querySelector('#banks');
const loansRoot = document.querySelector('#loans');
const financesRoot = document.querySelector('#finances');
const bankSelect = document.querySelector('#bank-select');
const loanCompanySelect = document.querySelector('#loan-company-select');
const storeForm = document.querySelector('#store-form');
const storeCompanySelect = document.querySelector('#store-company-select');
const storeFormatSelect = document.querySelector('#store-format-select');
const storeFormatsRoot = document.querySelector('#store-formats');
const storeListRoot = document.querySelector('#store-list');
const facilityForm = document.querySelector('#facility-form');
const facilityCompanySelect = document.querySelector('#facility-company-select');
const facilityFormatSelect = document.querySelector('#facility-format-select');
const facilityFormatsRoot = document.querySelector('#facility-formats');
const facilityListRoot = document.querySelector('#facility-list');
let lastState = null;
let lastStoreFormats = [];
let lastFacilityFormats = [];
// Новые панели (итерации 3–4)
const marketEventsRoot = document.querySelector('#market-events');
const eventsCountRoot = document.querySelector('#events-count');
const priceHistoryRoot = document.querySelector('#price-history');
const priceProductFilter = document.querySelector('#price-product-filter');
const priceRegionFilter = document.querySelector('#price-region-filter');
const deliveryOrdersListRoot = document.querySelector('#delivery-orders-list');
const deliveryOrderForm = document.querySelector('#delivery-order-form');
const doShipperSelect = document.querySelector('#do-shipper-select');
const doDistributorSelect = document.querySelector('#do-distributor-select');
const doReceiverSelect = document.querySelector('#do-receiver-select');
const doProductSelect = document.querySelector('#do-product-select');
const doDueDayInput = document.querySelector('#do-due-day');
let lastMarketEvents = [];
let lastPriceHistory = [];
const demoSummary = document.querySelector('#demo-summary');
const profitChart = document.querySelector('#profit-chart');
const demoTable = document.querySelector('#demo-table');
const persistenceStatusRoot = document.querySelector('#persistence-status');
const databaseStatusRoot = document.querySelector('#database-status');
const dayClosuresRoot = document.querySelector('#day-closures');
const projectProgressRoot = document.querySelector('#project-progress');
const projectFocusRoot = document.querySelector('#project-focus');
const projectRoadmapRoot = document.querySelector('#project-roadmap');
const authForm = document.querySelector('#auth-form');
const authStatusRoot = document.querySelector('#auth-status');
const logoutButton = document.querySelector('#logout');
const seasonIndicator = document.querySelector('#season-indicator');
const gameBanner = document.querySelector('#game-banner');
const leaderboardRoot = document.querySelector('#leaderboard');
let accessToken = localStorage.getItem('profitChainAccessToken');
let currentUser = JSON.parse(localStorage.getItem('profitChainUser') || 'null');

async function api(path, options = {}) {
  const authHeaders = accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: 'Ошибка API' }));
    throw new Error(payload.detail || 'Ошибка API');
  }
  return response.json();
}

function roleLabel(role) {
  return { retailer: 'Ритейлер', producer: 'Производитель', distributor: 'Дистрибьютор' }[role] || role;
}

async function fetchState() {
  return api('/api/state');
}

async function fetchPersistenceStatus() {
  return api('/api/persistence');
}

async function fetchDatabaseStatus() {
  return api('/api/database/status');
}

async function fetchGameStatus() {
  return api('/api/game-status');
}

async function fetchLeaderboard() {
  return api('/api/leaderboard');
}

async function fetchProjectStatus() {
  return api('/api/project/status');
}

async function fetchFinances() {
  return api('/api/finances');
}

async function fetchDayClosures() {
  return api('/api/day-closures');
}

function renderAuthStatus() {
  authStatusRoot.textContent = currentUser
    ? `Вход выполнен: ${currentUser.username}. Новые компании будут закреплены за этим игроком.`
    : 'Вы играете без входа. Для защиты компании зарегистрируйтесь или войдите.';
}

function renderPersistenceStatus(status) {
  const mode = status.enabled ? `JSON включён · ${status.path}` : 'JSON выключен';
  persistenceStatusRoot.textContent = `Файловое сохранение: ${mode}. День ${status.day}, компаний ${status.companies}.`;
}

function renderDatabaseStatus(status) {
  const mode = status.active ? `DB активна · ${status.dialect}` : status.enabled ? 'DB настроена, но не подключена' : 'DB выключена';
  databaseStatusRoot.textContent = `Durable-хранилище: ${mode}. Контрактов ${status.contracts}, кредитов ${status.loans}.`;
}

function renderDayClosures(closures) {
  dayClosuresRoot.innerHTML = closures.length ? closures.slice(0, 4).map((closure) => `<div class="closure"><b>${closure.closure_id}</b><small>День ${closure.result.day} · операций ${closure.result.operations.length}</small><span>${closure.result.news[0] || 'День закрыт'}</span></div>`).join('') : '<p class="muted">Закрытий с ключом пока нет.</p>';
}

function renderProjectStatus(status) {
  projectProgressRoot.textContent = `${status.status} · ${status.progress_percent}%`;
  projectFocusRoot.textContent = `Текущий фокус: ${status.current_focus}`;
  projectRoadmapRoot.innerHTML = status.milestones.map((milestone) => `<div class="roadmap-item ${milestone.status}"><b>${milestone.title}</b><small>${milestone.status}</small><span>${milestone.description}</span></div>`).join('');
}

function renderMetrics(state) {
  const player = state.companies.find((company) => company.id === 'player') || state.companies[0];
  metricRoot.innerHTML = [
    ['День', state.day],
    ['Деньги игрока', formatRub.format(player.cash_rub)],
    ['Компании', state.companies.length],
    ['Контракты', state.contracts.length],
  ].map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`).join('');
}

function renderSelectors(state) {
  const companyOptions = state.companies.map((company) => `<option value="${company.id}">${company.name} · ${roleLabel(company.role)}</option>`).join('');
  regionSelect.innerHTML = state.regions.map((region) => `<option value="${region.id}">${region.name}</option>`).join('');
  companySelect.innerHTML = companyOptions;
  sellerSelect.innerHTML = companyOptions;
  buyerSelect.innerHTML = companyOptions;
  loanCompanySelect.innerHTML = companyOptions;
  productSelect.innerHTML = state.products.map((product) => `<option value="${product.id}">${product.name}</option>`).join('');
  dueDayInput.value = state.day + 1;
  dueDayInput.min = state.day + 1;
}

function renderMap(regions) {
  const positions = [[60, 42], [420, 65], [235, 155], [670, 185], [130, 255]];
  mapRoot.innerHTML = '<div class="road" style="left:150px;top:180px;width:690px;transform:rotate(7deg)"></div><div class="truck" style="left:150px;top:158px">🚚</div>';
  regions.forEach((region, index) => {
    const [left, top] = positions[index];
    mapRoot.insertAdjacentHTML('beforeend', `<div class="region" style="left:${left}px;top:${top}px"><b>${region.name}</b><small>${region.description}</small></div>`);
  });
}

function renderProducts(products) {
  productsRoot.innerHTML = products.map((product) => `<div class="product"><b>${product.name}</b><br><small>${product.storage} · ${product.shelf_life_days} дн. · ${formatRub.format(product.base_price_rub)}</small></div>`).join('');
}


function assetTypeLabel(assetType) {
  return { store: 'Магазин', factory: 'Завод', warehouse: 'Склад' }[assetType] || assetType;
}

function renderAssets(state) {
  const companies = new Map(state.companies.map((company) => [company.id, company]));
  assetsRoot.innerHTML = (state.assets || []).map((asset) => {
    const company = companies.get(asset.company_id);
    return `<div class="asset"><b>${asset.name}</b><small>${assetTypeLabel(asset.asset_type)} · ${company?.name || asset.company_id}</small><span>Мощность: ${asset.capacity_units_per_day} ед./день · расходы: ${formatRub.format(asset.fixed_cost_rub_per_day)} · хранение: ${asset.storage_type}</span></div>`;
  }).join('') || '<p class="muted">Операционные объекты появятся у компаний.</p>';
}

function renderInventoryBatches(state) {
  const products = new Map(state.products.map((product) => [product.id, product]));
  const companies = new Map(state.companies.map((company) => [company.id, company]));
  const batches = [...(state.inventory_batches || [])]
    .sort((left, right) => left.expires_day - right.expires_day)
    .slice(0, 8);
  inventoryBatchesRoot.innerHTML = batches.length ? batches.map((batch) => {
    const product = products.get(batch.product_id);
    const company = companies.get(batch.company_id);
    const daysLeft = batch.expires_day - state.day;
    return `<div class="batch"><b>${product?.name || batch.product_id} · ${batch.quantity} ед.</b><small>${company?.name || batch.company_id}</small><span>Истекает: день ${batch.expires_day} (${daysLeft} дн.) · качество ${Math.round(batch.quality * 100)}%</span></div>`;
  }).join('') : '<p class="muted">Партии появятся после производства или закупки товара.</p>';
}

function renderRawMaterials(state) {
  const rawById = new Map((state.raw_materials || []).map((material) => [material.id, material]));
  const recipeCards = (state.production_recipes || []).map((recipe) => {
    const product = state.products.find((item) => item.id === recipe.product_id);
    const inputs = recipe.inputs.map((input) => {
      const material = rawById.get(input.raw_material_id);
      return `${material?.name || input.raw_material_id}: ${input.quantity_per_unit}`;
    }).join(' · ');
    return `<div class="raw-card"><b>${product?.name || recipe.product_id}</b><small>${inputs}</small><span>Конверсия: ${formatRub.format(recipe.conversion_cost_rub)} / ед.</span></div>`;
  });
  const inventoryCards = Object.entries(state.raw_inventories || {}).map(([companyId, inventory]) => {
    const company = state.companies.find((item) => item.id === companyId);
    const values = Object.entries(inventory).map(([rawId, quantity]) => `${rawById.get(rawId)?.name || rawId}: ${Math.round(quantity)}`).join(' · ');
    return `<div class="raw-card"><b>${company?.name || companyId}</b><small>${values}</small><span>Сырьевой склад производителя</span></div>`;
  });
  rawMaterialsRoot.innerHTML = recipeCards.concat(inventoryCards).join('') || '<p class="muted">Сырьё появится у производителей.</p>';
}

const SEASON_EMOJI = { 'Весна': '🌱', 'Лето': '☀️', 'Осень': '🍂', 'Зима': '❄️' };

function renderGameStatus(status) {
  if (seasonIndicator) {
    const emoji = SEASON_EMOJI[status.season_name] || '';
    const dayPart = lastState?.day != null ? ` · день ${lastState.day}` : '';
    seasonIndicator.hidden = false;
    seasonIndicator.textContent = `${emoji} ${status.season_name}${dayPart}`;
  }
  // Завершённую партию нельзя продолжать — блокируем закрытие дня
  if (simulateButton) {
    simulateButton.disabled = !!status.game_over;
    simulateButton.title = status.game_over ? 'Партия завершена — нажмите «Сбросить» для новой игры' : '';
  }
  if (!gameBanner) return;
  if (status.game_over) {
    const who = status.winner_name ? `«${status.winner_name}»` : 'Никто';
    gameBanner.className = 'game-banner victory';
    gameBanner.innerHTML = `<strong>🏆 Игра окончена.</strong> Победитель: ${who}.${renderStandingsTable(status.final_standings)}`;
    gameBanner.hidden = false;
  } else if (status.bankrupt_companies && status.bankrupt_companies.length) {
    gameBanner.className = 'game-banner alert';
    gameBanner.innerHTML = `<strong>⚠️ Банкротства на рынке:</strong> компаний выбыло — ${status.bankrupt_companies.length}.`;
    gameBanner.hidden = false;
  } else {
    gameBanner.hidden = true;
    gameBanner.innerHTML = '';
  }
}

function renderLeaderboard(entries) {
  if (!leaderboardRoot) return;
  if (!entries || !entries.length) {
    leaderboardRoot.innerHTML = '<p class="muted">Пока нет завершённых партий. Доведите игру до победы или последнего выжившего.</p>';
    return;
  }
  leaderboardRoot.innerHTML = entries.map((e) => {
    const who = e.winner_name ? `${e.winner_name}${e.winner_role ? ` · ${roleLabel(e.winner_role)}` : ''}` : 'Без победителя';
    const when = (e.recorded_at || '').replace('T', ' ');
    const source = e.source ? ` · ${e.source}` : '';
    return `<div class="leader"><b>🏅 Партия #${e.game_no}</b><span>${who}</span><small>Капитал ${formatRub.format(e.winner_cash_rub)} · ${e.days_played} дн. · ${e.total_companies} компаний${source} · ${when}</small></div>`;
  }).join('');
}

function renderStandingsTable(standings) {
  if (!standings || !standings.length) return '';
  const rows = standings.map((s) => {
    const medal = s.is_winner ? '🏆' : (s.status === 'bankrupt' ? '💀' : `${s.rank}.`);
    return `<tr class="${s.is_winner ? 'winner' : ''}"><td>${medal}</td><td>${s.name}</td><td>${roleLabel(s.role)}</td><td>${formatRub.format(s.cash_rub)}</td></tr>`;
  }).join('');
  return `<table class="standings"><thead><tr><th>#</th><th>Компания</th><th>Роль</th><th>Капитал</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderCompanies(state) {
  const reports = new Map(state.last_reports.map((report) => [report.company_id, report]));
  companiesRoot.innerHTML = state.companies.map((company) => {
    const report = reports.get(company.id);
    const reportLine = report ? `Прибыль дня: ${formatRub.format(report.profit_rub)} · Продано: ${report.sold_units} · Доставлено: ${report.delivered_units}` : 'Отчёта за день пока нет';
    const bankrupt = company.status === 'bankrupt';
    const icon = bankrupt ? '💀 ' : (company.is_npc ? '🤖 ' : '');
    const cls = bankrupt ? 'company bankrupt' : 'company';
    return `<div class="${cls}"><b>${icon}${company.name}</b><small>${roleLabel(company.role)} · ${formatRub.format(company.cash_rub)} · репутация ${company.reputation}</small><span>${reportLine}</span></div>`;
  }).join('');
}

function renderNews(news) {
  newsRoot.innerHTML = news.map((item) => `<li>${item}</li>`).join('');
}

function renderContracts(state) {
  contractsRoot.innerHTML = state.contracts.length ? state.contracts.slice(-6).reverse().map((contract) => `<div class="contract"><b>${contract.product_id} · ${contract.quantity} ед.</b><small>${contract.seller_id} → ${contract.buyer_id}</small><span>${formatRub.format(contract.unit_price_rub)} · день ${contract.due_day} · ${contract.status}</span></div>`).join('') : '<p class="muted">Контрактов пока нет.</p>';
}

function renderBanks(state) {
  bankSelect.innerHTML = state.banks.map((bank) => `<option value="${bank.id}">${bank.name} · ${Math.round(bank.annual_rate * 100)}%</option>`).join('');
  banksRoot.innerHTML = state.banks.map((bank) => `<div class="bank"><b>${bank.name}</b><small>${bank.description}</small><span>Ставка ${Math.round(bank.annual_rate * 100)}% · лимит ${formatRub.format(bank.max_loan_rub)}</span></div>`).join('');
}


function renderFinances(finances) {
  financesRoot.innerHTML = finances.length ? finances.slice(0, 5).map((report) => `<div class="finance"><b>${report.company_name}</b><small>Cash ${formatRub.format(report.cash_rub)} · чистая прибыль ${formatRub.format(report.net_profit_rub)}</small><span>НДС к уплате: ${formatRub.format(report.vat_payable_rub)} · долг: ${formatRub.format(report.loan_principal_rub)} · проводок: ${report.ledger_entries.length}</span></div>`).join('') : '<p class="muted">Финансовые отчёты появятся после закрытия дня.</p>';
}

function renderLoans(state) {
  loansRoot.innerHTML = state.loans.length ? state.loans.slice(-5).reverse().map((loan) => `<div class="loan"><b>${loan.company_id}</b><small>${loan.bank_id} · ${formatRub.format(loan.outstanding_rub)}</small><span>Начислено: ${formatRub.format(loan.accrued_interest_rub)} · ${loan.is_defaulted ? 'дефолт' : 'активен'}</span></div>`).join('') : '<p class="muted">Кредитов пока нет.</p>';
}

function renderRatings(board) {
  ratingsRoot.innerHTML = board.overall.slice(0, 5).map((entry) => `<div class="rating-row"><strong>#${entry.rank}</strong><span>${entry.company_name}<small>${roleLabel(entry.role)} · ${formatRub.format(entry.last_profit_rub)}</small></span><b>${entry.score}</b></div>`).join('');
}

function renderDemo(result) {
  demoSummary.textContent = result.summary;
  const maxProfit = Math.max(...result.days.map((day) => Math.abs(day.total_profit_rub)), 1);
  profitChart.innerHTML = result.days.map((day) => {
    const height = Math.max(8, Math.round(Math.abs(day.total_profit_rub) / maxProfit * 130));
    const className = day.total_profit_rub >= 0 ? 'bar positive' : 'bar negative';
    return `<div class="bar-wrap"><div class="${className}" style="height:${height}px" title="${formatRub.format(day.total_profit_rub)}"></div><small>Д${day.day}</small></div>`;
  }).join('');
  demoTable.innerHTML = `<table><thead><tr><th>День</th><th>Прибыль</th><th>Продано</th><th>Произведено</th><th>Доставлено</th><th>Контракты</th></tr></thead><tbody>${result.days.map((day) => `<tr><td>${day.day}</td><td>${formatRub.format(day.total_profit_rub)}</td><td>${day.sold_units}</td><td>${day.produced_units}</td><td>${day.delivered_units}</td><td>${day.fulfilled_contracts}/${day.breached_contracts}</td></tr>`).join('')}</tbody></table>`;
}

async function fetchRatings() {
  return api('/api/ratings');
}

async function fetchStoreFormats() {
  return api('/api/store-formats');
}

async function fetchFacilityFormats() {
  return api('/api/facility-formats');
}

const FACILITY_ASSET_BY_ROLE = { producer: 'factory', distributor: 'warehouse' };

function renderFacilityControls(state, formats) {
  lastFacilityFormats = formats;
  const builders = state.companies.filter((company) => FACILITY_ASSET_BY_ROLE[company.role]);
  const previous = facilityCompanySelect.value;
  facilityCompanySelect.innerHTML = builders.length
    ? builders.map((company) => `<option value="${company.id}">${company.name} · ${roleLabel(company.role)} · ${formatRub.format(company.cash_rub)}</option>`).join('')
    : '<option value="">Нет производителей или дистрибьюторов</option>';
  if (previous && builders.some((company) => company.id === previous)) {
    facilityCompanySelect.value = previous;
  }
  renderFacilityFormatOptions();
  renderFacilityList();
}

function selectedFacilityCompany() {
  if (!lastState) {
    return null;
  }
  return lastState.companies.find((company) => company.id === facilityCompanySelect.value) || null;
}

function renderFacilityFormatOptions() {
  const company = selectedFacilityCompany();
  const assetType = company ? FACILITY_ASSET_BY_ROLE[company.role] : null;
  const options = lastFacilityFormats.filter((format) => format.asset_type === assetType);
  facilityFormatSelect.innerHTML = options.map((format) => `<option value="${format.tier}">${format.name} · ${formatRub.format(format.build_cost_rub)}</option>`).join('');
  const multLabel = (format) => format.asset_type === 'factory' ? `выход ×${format.output_multiplier.toFixed(2)}` : `ставка ×${format.output_multiplier.toFixed(2)}`;
  facilityFormatsRoot.innerHTML = options.map((format) => `<div class="store-format"><b>${format.name}</b><small>Постройка: ${formatRub.format(format.build_cost_rub)}</small><span>Мощность: ${format.capacity_units_per_day} ед./день · расходы: ${formatRub.format(format.fixed_cost_rub_per_day)}/день · <span class="mult">${multLabel(format)}</span></span></div>`).join('') || '<p class="muted">Выберите производителя или дистрибьютора.</p>';
}

function nextFacilityFormat(assetType, currentTier) {
  const order = lastFacilityFormats.filter((format) => format.asset_type === assetType).sort((left, right) => left.build_cost_rub - right.build_cost_rub);
  const currentCost = order.find((format) => format.tier === currentTier)?.build_cost_rub ?? -1;
  return order.find((format) => format.build_cost_rub > currentCost) || null;
}

function renderFacilityList() {
  if (!lastState) {
    return;
  }
  const company = selectedFacilityCompany();
  if (!company) {
    facilityListRoot.innerHTML = '<p class="muted">У выбранной компании нет объектов.</p>';
    return;
  }
  const assetType = FACILITY_ASSET_BY_ROLE[company.role];
  const facilities = (lastState.assets || []).filter((asset) => asset.company_id === company.id && asset.asset_type === assetType);
  if (!facilities.length) {
    facilityListRoot.innerHTML = '<p class="muted">У выбранной компании нет объектов.</p>';
    return;
  }
  const canClose = facilities.length > 1;
  facilityListRoot.innerHTML = facilities.map((facility) => {
    const upgrade = nextFacilityFormat(assetType, facility.facility_format);
    const currentFmt = lastFacilityFormats.find((f) => f.tier === facility.facility_format);
    const currentMultLabel = currentFmt
      ? (assetType === 'factory' ? `выход ×${currentFmt.output_multiplier.toFixed(2)}` : `ставка ×${currentFmt.output_multiplier.toFixed(2)}`)
      : '';
    const upgradeButton = upgrade
      ? `<button type="button" class="secondary" data-action="upgrade" data-company="${company.id}" data-asset="${facility.id}" data-tier="${upgrade.tier}">До «${upgrade.name}» (+${formatRub.format(upgrade.build_cost_rub - (currentFmt?.build_cost_rub ?? 0))}, ${assetType === 'factory' ? 'выход' : 'ставка'} ×${upgrade.output_multiplier.toFixed(2)})</button>`
      : '<span class="muted">Максимальный формат</span>';
    const closeButton = canClose
      ? `<button type="button" class="ghost" data-action="close" data-company="${company.id}" data-asset="${facility.id}">Закрыть</button>`
      : '';
    return `<div class="store-row"><div><b>${facility.name}</b><small>Мощность: ${facility.capacity_units_per_day} ед./день · расходы: ${formatRub.format(facility.fixed_cost_rub_per_day)}/день${currentMultLabel ? ` · <span class="mult">${currentMultLabel}</span>` : ''}</small></div><div class="store-row-actions">${upgradeButton}${closeButton}</div></div>`;
  }).join('');
}

function renderStoreControls(state, formats) {
  lastState = state;
  lastStoreFormats = formats;
  const retailers = state.companies.filter((company) => company.role === 'retailer');
  const previous = storeCompanySelect.value;
  storeCompanySelect.innerHTML = retailers.length
    ? retailers.map((company) => `<option value="${company.id}">${company.name} · ${formatRub.format(company.cash_rub)}</option>`).join('')
    : '<option value="">Нет ритейлеров — создайте компанию-ритейлера</option>';
  if (previous && retailers.some((company) => company.id === previous)) {
    storeCompanySelect.value = previous;
  }
  storeFormatSelect.innerHTML = formats.map((format) => `<option value="${format.store_format}">${format.name} · ${formatRub.format(format.build_cost_rub)}</option>`).join('');
  storeFormatsRoot.innerHTML = formats.map((format) => `<div class="store-format"><b>${format.name}</b><small>Постройка: ${formatRub.format(format.build_cost_rub)}</small><span>Мощность: ${format.capacity_units_per_day} ед./день · расходы: ${formatRub.format(format.fixed_cost_rub_per_day)}/день · <span class="mult">спрос ×${format.demand_multiplier.toFixed(2)}</span></span></div>`).join('');
  renderStoreList();
}

function nextStoreFormat(currentFormat) {
  const order = lastStoreFormats.slice().sort((left, right) => left.build_cost_rub - right.build_cost_rub);
  const currentCost = lastStoreFormats.find((format) => format.store_format === currentFormat)?.build_cost_rub ?? -1;
  return order.find((format) => format.build_cost_rub > currentCost) || null;
}

function renderStoreList() {
  if (!lastState) {
    return;
  }
  const companyId = storeCompanySelect.value;
  const stores = (lastState.assets || []).filter((asset) => asset.company_id === companyId && asset.asset_type === 'store');
  if (!companyId || !stores.length) {
    storeListRoot.innerHTML = '<p class="muted">У выбранной компании нет магазинов.</p>';
    return;
  }
  const canClose = stores.length > 1;
  storeListRoot.innerHTML = stores.map((store) => {
    const upgrade = nextStoreFormat(store.store_format);
    const currentFmt = lastStoreFormats.find((f) => f.store_format === store.store_format);
    const upgradeButton = upgrade
      ? `<button type="button" class="secondary" data-action="upgrade" data-company="${companyId}" data-asset="${store.id}" data-format="${upgrade.store_format}">До «${upgrade.name}» (+${formatRub.format(upgrade.build_cost_rub - (currentFmt?.build_cost_rub ?? 0))}, спрос ×${upgrade.demand_multiplier.toFixed(2)})</button>`
      : '<span class="muted">Максимальный формат</span>';
    const closeButton = canClose
      ? `<button type="button" class="ghost" data-action="close" data-company="${companyId}" data-asset="${store.id}">Закрыть</button>`
      : '';
    const demandLabel = currentFmt ? `спрос ×${currentFmt.demand_multiplier.toFixed(2)}` : '';
    return `<div class="store-row"><div><b>${store.name}</b><small>Мощность: ${store.capacity_units_per_day} ед./день · расходы: ${formatRub.format(store.fixed_cost_rub_per_day)}/день${demandLabel ? ` · <span class="mult">${demandLabel}</span>` : ''}</small></div><div class="store-row-actions">${upgradeButton}${closeButton}</div></div>`;
  }).join('');
}

// ─── Рыночные события ────────────────────────────────────────────────────────

function renderMarketEvents(events, currentDay) {
  const active = events.filter((e) => e.expires_day >= currentDay);
  const expired = events.filter((e) => e.expires_day < currentDay);
  eventsCountRoot.textContent = `активных: ${active.length} · истекших: ${expired.length}`;
  if (!events.length) {
    marketEventsRoot.innerHTML = '<p class="muted">Рыночных событий пока нет. Они появляются с вероятностью 15% при закрытии дня.</p>';
    return;
  }
  const eventTypeLabel = { demand_shock: 'Шок спроса', supply_disruption: 'Сбой поставок' };
  marketEventsRoot.innerHTML = [...active, ...expired].map((event) => {
    const isActive = event.expires_day >= currentDay;
    const badge = isActive ? '<span class="badge active">активно</span>' : '<span class="badge expired">истекло</span>';
    const scope = [event.region_id, event.product_id].filter(Boolean).join(' · ') || 'весь рынок';
    return `<div class="market-event ${isActive ? '' : 'dimmed'}"><div class="event-header">${badge}<b>${eventTypeLabel[event.event_type] || event.event_type}</b><small>День ${event.day}–${event.expires_day} · ${scope}</small></div><span class="event-magnitude">${event.magnitude >= 1 ? '+' : ''}${Math.round((event.magnitude - 1) * 100)}%</span><p>${event.description}</p></div>`;
  }).join('');
}

// ─── История цен ─────────────────────────────────────────────────────────────

function renderPriceHistory(pts, state) {
  const productFilter = priceProductFilter.value;
  const regionFilter = priceRegionFilter.value;
  const filtered = pts
    .filter((p) => (!productFilter || p.product_id === productFilter) && (!regionFilter || p.region_id === regionFilter))
    .slice()
    .sort((a, b) => b.day - a.day || a.region_id.localeCompare(b.region_id));

  // Заполняем фильтры при первом рендере
  if (!priceProductFilter.options.length || priceProductFilter.options[0].value === '') {
    const products = [...new Set(pts.map((p) => p.product_id))].sort();
    priceProductFilter.innerHTML = '<option value="">Все товары</option>' +
      products.map((id) => {
        const name = state.products.find((pr) => pr.id === id)?.name || id;
        return `<option value="${id}">${name}</option>`;
      }).join('');
    const regions = [...new Set(pts.map((p) => p.region_id))].sort();
    priceRegionFilter.innerHTML = '<option value="">Все регионы</option>' +
      regions.map((id) => {
        const name = state.regions.find((r) => r.id === id)?.name || id;
        return `<option value="${id}">${name}</option>`;
      }).join('');
  }

  if (!filtered.length) {
    priceHistoryRoot.innerHTML = '<p class="muted">История цен появится после первого закрытия дня.</p>';
    return;
  }
  priceHistoryRoot.innerHTML = `<table class="price-table"><thead><tr><th>День</th><th>Регион</th><th>Товар</th><th>Ср. цена</th><th>Продано</th></tr></thead><tbody>${
    filtered.slice(0, 30).map((p) => {
      const productName = state.products.find((pr) => pr.id === p.product_id)?.name || p.product_id;
      const regionName = state.regions.find((r) => r.id === p.region_id)?.name || p.region_id;
      return `<tr><td>${p.day}</td><td>${regionName}</td><td>${productName}</td><td>${formatRub.format(p.avg_price_rub)}</td><td>${p.total_units_sold}</td></tr>`;
    }).join('')
  }</tbody></table>`;
}

// ─── Заявки дистрибьютора ────────────────────────────────────────────────────

function renderDeliveryOrderSelectors(state) {
  const all = state.companies.map((c) => `<option value="${c.id}">${c.name} · ${roleLabel(c.role)}</option>`).join('');
  const distributors = state.companies.filter((c) => c.role === 'distributor')
    .map((c) => `<option value="${c.id}">${c.name}</option>`).join('');
  doShipperSelect.innerHTML = all;
  doDistributorSelect.innerHTML = distributors || '<option value="">Нет дистрибьюторов</option>';
  doReceiverSelect.innerHTML = all;
  doProductSelect.innerHTML = state.products.map((p) => `<option value="${p.id}">${p.name}</option>`).join('');
  doDueDayInput.value = state.day + 1;
  doDueDayInput.min = state.day + 1;
}

function renderDeliveryOrders(orders, state) {
  if (!orders.length) {
    deliveryOrdersListRoot.innerHTML = '<p class="muted">Заявок пока нет.</p>';
    return;
  }
  const companies = new Map(state.companies.map((c) => [c.id, c]));
  const products = new Map(state.products.map((p) => [p.id, p]));
  const statusLabel = { pending: 'ожидает', accepted: 'принята', fulfilled: 'выполнена', cancelled: 'отменена' };
  const sorted = [...orders].sort((a, b) => b.created_day - a.created_day);
  deliveryOrdersListRoot.innerHTML = sorted.map((order) => {
    const productName = products.get(order.product_id)?.name || order.product_id;
    const shipperName = companies.get(order.shipper_id)?.name || order.shipper_id;
    const distName = companies.get(order.distributor_id)?.name || order.distributor_id;
    const receiverName = companies.get(order.receiver_id)?.name || order.receiver_id;
    const canAccept = order.status === 'pending';
    const canCancel = order.status === 'pending' || order.status === 'accepted';
    const acceptBtn = canAccept
      ? `<button type="button" class="secondary" data-do-action="accept" data-order-id="${order.id}" data-dist-id="${order.distributor_id}">Принять</button>`
      : '';
    const cancelBtn = canCancel
      ? `<button type="button" class="ghost" data-do-action="cancel" data-order-id="${order.id}" data-shipper-id="${order.shipper_id}">Отменить</button>`
      : '';
    return `<div class="delivery-order status-${order.status}">
      <div class="do-header"><b>${productName} · ${order.quantity} ед.</b><span class="badge status-${order.status}">${statusLabel[order.status] || order.status}</span></div>
      <small>${shipperName} → <em>${distName}</em> → ${receiverName}</small>
      <span>${formatRub.format(order.fee_rub_per_unit)}/ед. · день исп.: ${order.due_day} · создана: день ${order.created_day}</span>
      <div class="do-actions">${acceptBtn}${cancelBtn}</div>
    </div>`;
  }).join('');
}

async function render() {
  const [state, ratings, persistenceStatus, databaseStatus, projectStatus, dayClosures, finances, storeFormats, facilityFormats, marketEvents, priceHistory, gameStatus, leaderboard] = await Promise.all([
    fetchState(),
    fetchRatings(),
    fetchPersistenceStatus(),
    fetchDatabaseStatus(),
    fetchProjectStatus(),
    fetchDayClosures(),
    fetchFinances(),
    fetchStoreFormats(),
    fetchFacilityFormats(),
    api('/api/market-events'),
    api('/api/prices'),
    fetchGameStatus(),
    fetchLeaderboard(),
  ]);
  lastState = state;
  lastMarketEvents = marketEvents;
  lastPriceHistory = priceHistory;
  renderMetrics(state);
  renderSelectors(state);
  renderStoreControls(state, storeFormats);
  renderFacilityControls(state, facilityFormats);
  renderDeliveryOrderSelectors(state);
  renderMap(state.regions);
  renderProducts(state.products);
  renderAssets(state);
  renderInventoryBatches(state);
  renderRawMaterials(state);
  renderCompanies(state);
  renderGameStatus(gameStatus);
  renderLeaderboard(leaderboard);
  renderContracts(state);
  renderBanks(state);
  renderLoans(state);
  renderFinances(finances);
  renderRatings(ratings);
  renderPersistenceStatus(persistenceStatus);
  renderDatabaseStatus(databaseStatus);
  renderProjectStatus(projectStatus);
  renderDayClosures(dayClosures);
  renderMarketEvents(marketEvents, state.day + 1);
  renderPriceHistory(priceHistory, state);
  renderDeliveryOrders(state.delivery_orders || [], state);
  renderAuthStatus();
  renderNews(state.news);
}

authForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submitter = event.submitter;
  const form = new FormData(authForm);
  const action = submitter?.value || 'login';
  const payload = { username: form.get('username'), password: form.get('password') };
  const token = await api(`/api/auth/${action}`, { method: 'POST', body: JSON.stringify(payload) });
  accessToken = token.access_token;
  currentUser = token.user;
  localStorage.setItem('profitChainAccessToken', accessToken);
  localStorage.setItem('profitChainUser', JSON.stringify(currentUser));
  await render();
});

logoutButton.addEventListener('click', async () => {
  accessToken = null;
  currentUser = null;
  localStorage.removeItem('profitChainAccessToken');
  localStorage.removeItem('profitChainUser');
  renderAuthStatus();
});

companyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(companyForm);
  await api('/api/companies', {
    method: 'POST',
    body: JSON.stringify(Object.fromEntries(form.entries())),
  });
  await render();
});

storeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(storeForm);
  const companyId = form.get('company_id');
  if (!companyId) {
    newsRoot.innerHTML = '<li>Сначала создайте компанию-ритейлера, чтобы строить магазины.</li>';
    return;
  }
  const payload = { store_format: form.get('store_format') };
  const name = (form.get('name') || '').trim();
  if (name) {
    payload.name = name;
  }
  try {
    await api(`/api/companies/${companyId}/stores`, { method: 'POST', body: JSON.stringify(payload) });
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

storeCompanySelect.addEventListener('change', renderStoreList);

facilityCompanySelect.addEventListener('change', () => {
  renderFacilityFormatOptions();
  renderFacilityList();
});

facilityForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(facilityForm);
  const companyId = form.get('company_id');
  const tier = form.get('tier');
  if (!companyId || !tier) {
    newsRoot.innerHTML = '<li>Выберите производителя или дистрибьютора и формат объекта.</li>';
    return;
  }
  const payload = { tier };
  const name = (form.get('name') || '').trim();
  if (name) {
    payload.name = name;
  }
  try {
    await api(`/api/companies/${companyId}/facilities`, { method: 'POST', body: JSON.stringify(payload) });
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

facilityListRoot.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  const { action, company, asset, tier } = button.dataset;
  try {
    if (action === 'upgrade') {
      await api(`/api/companies/${company}/facilities/${asset}/upgrade`, { method: 'POST', body: JSON.stringify({ new_tier: tier }) });
    } else if (action === 'close') {
      await api(`/api/companies/${company}/facilities/${asset}`, { method: 'DELETE' });
    }
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

storeListRoot.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  const { action, company, asset, format } = button.dataset;
  try {
    if (action === 'upgrade') {
      await api(`/api/companies/${company}/stores/${asset}/upgrade`, { method: 'POST', body: JSON.stringify({ new_format: format }) });
    } else if (action === 'close') {
      await api(`/api/companies/${company}/stores/${asset}`, { method: 'DELETE' });
    }
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

loanForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(loanForm);
  const payload = Object.fromEntries(form.entries());
  payload.principal_rub = Number(payload.principal_rub);
  payload.term_days = Number(payload.term_days);
  await api('/api/loans', { method: 'POST', body: JSON.stringify(payload) });
  await render();
});

contractForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(contractForm);
  const payload = Object.fromEntries(form.entries());
  payload.contract_type = 'supply';
  payload.quantity = Number(payload.quantity);
  payload.unit_price_rub = Number(payload.unit_price_rub);
  payload.due_day = Number(payload.due_day);
  payload.penalty_rub = Number(payload.penalty_rub);
  await api('/api/contracts', { method: 'POST', body: JSON.stringify(payload) });
  await render();
});

decisionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(decisionForm);
  const companyId = form.get('company_id');
  const payload = {
    target_price_index: Number(form.get('target_price_index')),
    production_units: Number(form.get('production_units')),
    logistics_capacity_units: Number(form.get('logistics_capacity_units')),
    marketing_budget_rub: Number(form.get('marketing_budget_rub')),
    ready: true,
  };
  await api(`/api/decisions/${companyId}`, { method: 'POST', body: JSON.stringify(payload) });
  await render();
});

simulateButton.addEventListener('click', async () => {
  simulateButton.disabled = true;
  await api('/api/close-day', { method: 'POST', body: JSON.stringify({ closure_id: `ui-day-${Date.now()}` }) });
  await render();
  simulateButton.disabled = false;
});

runDemoButton.addEventListener('click', async () => {
  runDemoButton.disabled = true;
  const result = await api('/api/demo/run', { method: 'POST' });
  renderDemo(result);
  await render();
  runDemoButton.disabled = false;
});

resetButton.addEventListener('click', async () => {
  await api('/api/reset', { method: 'POST' });
  demoSummary.textContent = 'Мир сброшен. Запусти демо, чтобы увидеть динамику прибыли и операций.';
  profitChart.innerHTML = '';
  demoTable.innerHTML = '';
  await render();
});

// ─── Заявки: создать ────────────────────────────────────────────────────────

deliveryOrderForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(deliveryOrderForm);
  const shipperId = form.get('shipper_id');
  const payload = {
    distributor_id: form.get('distributor_id'),
    receiver_id: form.get('receiver_id'),
    product_id: form.get('product_id'),
    quantity: Number(form.get('quantity')),
    fee_rub_per_unit: Number(form.get('fee_rub_per_unit')),
    due_day: Number(form.get('due_day')),
  };
  try {
    await api(`/api/companies/${shipperId}/delivery-orders`, { method: 'POST', body: JSON.stringify(payload) });
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

// ─── Заявки: принять / отменить ─────────────────────────────────────────────

deliveryOrdersListRoot.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-do-action]');
  if (!button) return;
  const { doAction, orderId, distId, shipperId } = button.dataset;
  try {
    if (doAction === 'accept') {
      await api(`/api/delivery-orders/${orderId}/accept?distributor_company_id=${distId}`, { method: 'POST' });
    } else if (doAction === 'cancel') {
      await api(`/api/delivery-orders/${orderId}?shipper_company_id=${shipperId}`, { method: 'DELETE' });
    }
    await render();
  } catch (error) {
    newsRoot.innerHTML = `<li>${error.message}</li>`;
  }
});

// ─── Фильтры истории цен ────────────────────────────────────────────────────

priceProductFilter.addEventListener('change', () => {
  if (lastState && lastPriceHistory) renderPriceHistory(lastPriceHistory, lastState);
});
priceRegionFilter.addEventListener('change', () => {
  if (lastState && lastPriceHistory) renderPriceHistory(lastPriceHistory, lastState);
});

render().catch((error) => {
  newsRoot.innerHTML = `<li>${error.message}</li>`;
});
