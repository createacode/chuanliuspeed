/* 川流测速前端逻辑：所有服务端数据在写入 DOM 前都会转义。 */
(() => {
    'use strict';

    const state = {
        sources: {},
        selected: new Set(),
        userTouched: new Set(),
        knownIds: new Set(),
        loadedOnce: false,
        isTesting: false,
        testId: null,
        totalSelected: 0,
        testStartTime: null,
        completionTime: null,
        stats: { completed: 0, success: 0, failed: 0 },
        pollTimer: null,
        pollEpoch: 0,
        validationTimer: null,
        validationInProgress: false,
        chart: null,
        chartData: [],
        chartUnavailable: false,
        notificationTimer: null,
        resultSigs: new Map(),
    };

    const el = {};

    function cacheDom() {
        const ids = [
            'sourcesList', 'testResults', 'averageContainer', 'averageSpeedLabel',
            'avgSpeedMbps', 'avgSpeedMBs', 'calculationContent', 'calculationRow',
            'chartRow', 'speedChart', 'totalProgressRow', 'totalProgressFill',
            'totalProgressPercent', 'totalCompleted', 'totalSources', 'totalSuccess',
            'totalFailed', 'totalTimeValue', 'completionTimeValue', 'testId',
            'startTest', 'resetState', 'stopTest', 'validateSources', 'addSource',
            'refreshSources', 'importSources', 'exportSources', 'sourceModal',
            'closeModal', 'cancelModal', 'sourceForm', 'modalTitle', 'sourceId',
            'sourceName', 'sourceUrl', 'notification', 'selectAllCheckbox',
            'selectedCount', 'testStats', 'testingCount', 'completedCount',
            'successCount', 'failedCount', 'serverStatus',
        ];
        for (const id of ids) {
            const node = document.getElementById(id);
            if (!node) throw new Error(`页面缺少元素 #${id}`);
            el[id] = node;
        }
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    async function api(path, options = {}) {
        const headers = Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, options.headers || {});
        const init = Object.assign({ method: 'GET' }, options, { headers });
        if (init.body && typeof init.body !== 'string') {
            init.body = JSON.stringify(init.body);
        }
        if (init.body) headers['Content-Type'] = 'application/json';

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 15000);
        init.signal = controller.signal;
        let response;
        try {
            response = await fetch(path, init);
        } catch (error) {
            throw new Error(error.name === 'AbortError' ? '请求超时，请检查本地服务' : '无法连接本地服务');
        } finally {
            clearTimeout(timeout);
        }

        const type = response.headers.get('content-type') || '';
        let data = {};
        if (type.includes('application/json')) {
            try { data = await response.json(); } catch (_) { data = {}; }
        }
        if (!response.ok) {
            throw new Error(data.message || `请求失败 (HTTP ${response.status})`);
        }
        if (data.success === false) {
            throw new Error(data.message || '操作失败');
        }
        return data;
    }

    function notify(message, type = 'info') {
        el.notification.textContent = String(message);
        el.notification.className = `notification ${type} show`;
        clearTimeout(state.notificationTimer);
        state.notificationTimer = setTimeout(() => {
            el.notification.classList.remove('show');
        }, 3200);
    }

    function formatFileSize(sizeBytes) {
        const size = Number(sizeBytes) || 0;
        if (size < 1024) return `${Math.round(size)} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)} KB`;
        if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`;
        return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }

    // -------------------------------------------------------------- 下载源列表

    async function loadSources({ fresh = false } = {}) {
        const data = await api('/api/config');
        state.sources = data.sources || {};
        state.validationInProgress = Boolean(data.validation_in_progress);
        const ids = Object.keys(state.sources);

        if (fresh || !state.loadedOnce) {
            state.selected.clear();
            state.userTouched.clear();
            state.knownIds = new Set();
            const enabled = ids.filter((id) => state.sources[id].enabled !== false);
            const valid = enabled.filter((id) => state.sources[id].valid);
            (valid.length ? valid : enabled).forEach((id) => state.selected.add(id));
        } else {
            for (const id of Array.from(state.selected)) {
                if (!(id in state.sources)) state.selected.delete(id);
            }
            for (const id of ids) {
                const source = state.sources[id];
                if (source.enabled !== false && source.valid && !state.userTouched.has(id)) {
                    state.selected.add(id);
                }
            }
        }

        state.knownIds = new Set(ids);
        state.loadedOnce = true;
        renderSources();
        updateServerStatus();
        if (state.validationInProgress) startValidationPolling();
    }

    function renderSources() {
        const ids = Object.keys(state.sources);
        if (!ids.length) {
            el.sourcesList.innerHTML = '<div class="no-results">暂无下载源，请添加或等待验证完成</div>';
            updateSelectedCount();
            updateSelectAll();
            updateTestButtonState();
            return;
        }

        const rows = ids.map((id) => {
            const source = state.sources[id] || {};
            const valid = Boolean(source.valid);
            const enabled = source.enabled !== false;
            const lastStatus = String(source.last_status || '');
            const timeout = lastStatus.includes('超时');
            const checked = state.selected.has(id);

            let statusClass = 'status-invalid';
            let statusText = '不可用';
            if (valid) {
                statusClass = 'status-valid';
                statusText = '可用';
            } else if (state.validationInProgress) {
                statusClass = 'status-pending';
                statusText = '验证中';
            }
            if (timeout) {
                statusClass = 'status-timeout';
                statusText = '超时';
            }

            return `
                <div class="source-item" data-id="${escapeHtml(id)}">
                    <div class="source-checkbox">
                        <input type="checkbox" data-id="${escapeHtml(id)}"
                               aria-label="选择 ${escapeHtml(source.name || id)}"
                               ${checked ? 'checked' : ''} ${enabled ? '' : 'disabled'}>
                    </div>
                    <div class="source-info">
                        <div class="source-name">${escapeHtml(source.name || id)}</div>
                        <div class="source-details">
                            <div class="source-detail-row">
                                <span>大小: <span class="source-size">${escapeHtml(source.size || '未知')}</span></span>
                                <span>状态: ${escapeHtml(statusText)}</span>
                            </div>
                            <div class="source-detail-row">
                                <span class="source-time">上次验证: ${escapeHtml(source.last_validation || '从未验证')}</span>
                                ${lastStatus ? `<span class="source-status-text">${escapeHtml(lastStatus)}</span>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="source-status ${statusClass}">${escapeHtml(statusText)}</div>
                    <div class="panel-actions">
                        <button class="icon-btn" data-action="edit" data-id="${escapeHtml(id)}" title="编辑">✏</button>
                        <button class="icon-btn" data-action="delete" data-id="${escapeHtml(id)}" title="删除">🗑</button>
                    </div>
                </div>`;
        });
        el.sourcesList.innerHTML = rows.join('');
        updateSelectedCount();
        updateSelectAll();
        updateTestButtonState();
    }

    function updateSelectedCount() {
        el.selectedCount.textContent = `已选择 ${state.selected.size} 个`;
    }

    function updateSelectAll() {
        const boxes = Array.from(el.sourcesList.querySelectorAll('input[type="checkbox"][data-id]:not(:disabled)'));
        const allChecked = boxes.length > 0 && boxes.every((box) => box.checked);
        el.selectAllCheckbox.checked = allChecked;
        el.selectAllCheckbox.indeterminate = state.selected.size > 0 && !allChecked;
    }

    function updateTestButtonState() {
        const busy = state.isTesting || state.validationInProgress;
        const enabledSelected = Array.from(state.selected).filter(
            (id) => state.sources[id] && state.sources[id].enabled !== false,
        ).length;
        el.startTest.disabled = busy || enabledSelected === 0;
        if (state.validationInProgress) {
            el.startTest.title = '正在验证下载源，请稍候';
        } else if (enabledSelected === 0) {
            el.startTest.title = '请先勾选要测试的下载源';
        } else {
            el.startTest.title = '开始测试';
        }
        el.stopTest.disabled = !state.isTesting;
        el.validateSources.disabled = state.validationInProgress || state.isTesting;
        el.resetState.disabled = false;
    }

    function updateServerStatus() {
        if (state.validationInProgress) {
            el.serverStatus.innerHTML = '<span class="loading"></span> 正在验证下载源...';
            el.validateSources.disabled = true;
            el.validateSources.innerHTML = '<span class="loading"></span> 验证中...';
        } else {
            const sources = Object.values(state.sources);
            const validCount = sources.filter((source) => source.valid).length;
            el.serverStatus.textContent = `已验证 ${validCount}/${sources.length} 个下载源`;
            el.validateSources.disabled = state.isTesting;
            el.validateSources.textContent = '🔍 验证链接';
        }
    }

    function updateSelectAllHandler() {
        const checked = el.selectAllCheckbox.checked;
        const boxes = el.sourcesList.querySelectorAll('input[type="checkbox"][data-id]:not(:disabled)');
        boxes.forEach((box) => {
            box.checked = checked;
            const id = box.dataset.id;
            if (checked) state.selected.add(id); else state.selected.delete(id);
            state.userTouched.add(id);
        });
        updateSelectedCount();
        updateTestButtonState();
        updateSelectAll();
    }

    // -------------------------------------------------------------- 测试控制

    async function startTest() {
        if (state.isTesting) return;
        const ids = Array.from(state.selected).filter(
            (id) => state.sources[id] && state.sources[id].enabled !== false,
        );
        if (!ids.length) {
            notify('请先勾选要测试的下载源', 'error');
            return;
        }

        el.startTest.disabled = true;
        try {
            const data = await api('/api/test', { method: 'POST', body: { sources: ids } });
            state.pollEpoch += 1;
            state.isTesting = true;
            state.testId = data.test_id;
            state.totalSelected = ids.length;
            state.stats = { completed: 0, success: 0, failed: 0 };
            state.testStartTime = Date.now();
            state.completionTime = null;
            state.resultSigs.clear();

            el.testId.textContent = `测试ID: ${state.testId}`;
            el.testStats.classList.add('show');
            resetResultsUi(ids);
            updateTestButtonState();
            schedulePoll(300);
            notify('测试已开始', 'success');
        } catch (error) {
            if (error.message.includes('验证')) {
                state.validationInProgress = true;
                updateServerStatus();
                startValidationPolling();
            }
            notify(error.message, 'error');
            updateTestButtonState();
        }
    }

    function resetResultsUi(ids) {
        el.averageContainer.classList.add('show');
        el.averageSpeedLabel.textContent = '当前平均下载速度';
        el.avgSpeedMbps.textContent = '0.00';
        el.avgSpeedMBs.textContent = '0.00';
        el.calculationContent.textContent = '';
        el.chartRow.classList.add('hidden');
        if (state.chart) {
            state.chart.destroy();
            state.chart = null;
        }
        state.chartData = [];
        el.totalProgressRow.classList.remove('hidden');
        el.totalProgressFill.style.width = '0%';
        el.totalProgressFill.classList.remove('complete');
        el.totalProgressPercent.textContent = '0%';
        el.totalCompleted.textContent = '0';
        el.totalSuccess.textContent = '0';
        el.totalFailed.textContent = '0';
        el.totalSources.textContent = String(state.totalSelected);
        el.totalTimeValue.textContent = '0.00秒';
        el.completionTimeValue.textContent = '--';
        el.testResults.innerHTML = '';
        el.testStats.classList.add('show');

        ids.forEach((id) => {
            const source = state.sources[id] || {};
            renderResult(id, {
                name: source.name || id,
                status: '测试中...',
                progress: 0,
                elapsed_time: 0,
                current_speed_mbps: 0,
                current_speed_mbs: 0,
                downloaded_size: 0,
            });
        });
    }

    async function stopTest() {
        el.stopTest.disabled = true;
        try {
            const data = await api('/api/stop', { method: 'POST', timeoutMs: 12000 });
            notify(data.message || '已请求停止', 'info');
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function resetState() {
        state.pollEpoch += 1;
        if (state.pollTimer) {
            clearTimeout(state.pollTimer);
            state.pollTimer = null;
        }
        try {
            if (state.isTesting) {
                try { await api('/api/stop', { method: 'POST', timeoutMs: 12000 }); } catch (_) { /* 忽略 */ }
            }
            const data = await api('/api/reset', { method: 'POST', timeoutMs: 20000 });
            state.isTesting = false;
            state.testId = null;
            state.testStartTime = null;
            state.completionTime = null;
            state.totalSelected = 0;
            state.stats = { completed: 0, success: 0, failed: 0 };
            state.resultSigs.clear();
            state.sources = data.sources || state.sources;
            state.loadedOnce = false;
            state.knownIds = new Set();
            state.selected.clear();
            state.userTouched.clear();

            if (state.chart) {
                state.chart.destroy();
                state.chart = null;
            }
            state.chartData = [];
            el.testId.textContent = '等待测试开始';
            el.testStats.classList.remove('show');
            el.averageContainer.classList.remove('show');
            el.chartRow.classList.add('hidden');
            el.totalProgressRow.classList.add('hidden');
            el.totalProgressFill.style.width = '0%';
            el.totalProgressFill.classList.remove('complete');
            el.totalProgressPercent.textContent = '0%';
            el.calculationContent.textContent = '';
            el.totalTimeValue.textContent = '--';
            el.completionTimeValue.textContent = '--';
            el.testResults.innerHTML = `
                <div class="no-results">
                    <div class="no-results-icon">📈</div>
                    <div class="no-results-title">等待测试开始</div>
                    <div class="no-results-hint">选择下载源并点击“开始测试”按钮</div>
                </div>`;
            updateTestButtonState();
            await loadSources({ fresh: true });
            notify('所有状态已重置', 'info');
        } catch (error) {
            notify(error.message, 'error');
            updateTestButtonState();
        }
    }

    // -------------------------------------------------------------- 轮询与渲染

    function schedulePoll(delay) {
        if (state.pollTimer) clearTimeout(state.pollTimer);
        const epoch = state.pollEpoch;
        state.pollTimer = setTimeout(() => pollOnce(epoch), delay);
    }

    async function pollOnce(epoch) {
        state.pollTimer = null;
        if (epoch !== state.pollEpoch) return;
        try {
            const data = await api('/api/status', { timeoutMs: 8000 });
            if (epoch !== state.pollEpoch) return;
            if (!data.is_testing) {
                if (state.isTesting) finishTest(data);
                return;
            }
            if (!state.isTesting) {
                // 页面刷新后重新接管已开始的测试
                state.isTesting = true;
                state.testId = data.test_id;
                state.testStartTime = state.testStartTime || Date.now();
                el.testStats.classList.add('show');
                el.averageContainer.classList.add('show');
                el.totalProgressRow.classList.remove('hidden');
                updateTestButtonState();
            }
            updateTestResults(data);
            schedulePoll(500);
        } catch (error) {
            console.error(error);
            if (epoch === state.pollEpoch && state.isTesting) schedulePoll(1500);
        }
    }

    function finishTest(data) {
        if (!state.isTesting) return;
        updateTestResults(data);
        state.isTesting = false;
        if (state.pollTimer) {
            clearTimeout(state.pollTimer);
            state.pollTimer = null;
        }
        state.completionTime = new Date();
        el.averageSpeedLabel.textContent = '最终平均下载速度';
        el.completionTimeValue.textContent = state.completionTime.toLocaleString('zh-CN');
        if (state.testStartTime) {
            el.totalTimeValue.textContent = `${((Date.now() - state.testStartTime) / 1000).toFixed(2)}秒`;
        }
        updateProgress();
        updateTestButtonState();
        notify('测试完成', 'success');
        loadSources().catch(() => { /* 保持当前界面 */ });
    }

    function updateTestResults(data) {
        if (!data || !data.success) return;
        const results = data.results || {};
        const stats = data.stats || {};
        state.stats.completed = Number(stats.completed_count) || 0;
        state.stats.success = Number(stats.success_count) || 0;
        state.stats.failed = Number(stats.failed_count) || 0;
        const total = Number(data.total_count) || 0;
        if (total > 0) state.totalSelected = total;
        if (data.test_id) {
            state.testId = data.test_id;
            el.testId.textContent = `测试ID: ${state.testId}`;
        }

        el.testingCount.textContent = String(Number(stats.testing_count) || 0);
        el.completedCount.textContent = String(state.stats.completed);
        el.successCount.textContent = String(state.stats.success);
        el.failedCount.textContent = String(state.stats.failed);

        for (const [id, result] of Object.entries(results)) {
            renderResult(id, result);
            if (result.status === '成功') addChartPoint(id, result);
        }

        if (Object.keys(results).length > 0) {
            el.averageContainer.classList.add('show');
            el.testStats.classList.add('show');
        }
        setAverage(data.avg_speed_mbps, data.avg_speed_mbs);
        renderCalculation(data.calculation_process);
        updateChart();
        updateProgress();
        updateElapsed();
    }

    function setAverage(mbps, mbs) {
        const mbpsValue = Number(mbps);
        const mbsValue = Number(mbs);
        if (Number.isFinite(mbpsValue)) el.avgSpeedMbps.textContent = mbpsValue.toFixed(2);
        if (Number.isFinite(mbsValue)) el.avgSpeedMBs.textContent = mbsValue.toFixed(2);
    }

    function renderResult(id, result) {
        const signature = JSON.stringify([
            result.status, result.progress, result.current_speed_mbps,
            result.current_speed_mbs, result.downloaded_size, result.time,
            result.speed_mbps, result.speed_mbs, result.name, result.sampled,
        ]);
        const existing = document.getElementById(`result_${id}`);
        if (existing) {
            if (state.resultSigs.get(id) === signature) return;
            state.resultSigs.set(id, signature);
            existing.outerHTML = createResultItem(id, result);
            applyProgressWidth(id);
            return;
        }
        const placeholder = el.testResults.querySelector('.no-results');
        if (placeholder) placeholder.remove();
        state.resultSigs.set(id, signature);
        el.testResults.insertAdjacentHTML('beforeend', createResultItem(id, result));
        applyProgressWidth(id);
    }

    function applyProgressWidth(id) {
        const item = document.getElementById(`result_${id}`);
        const fill = item && item.querySelector('.progress-fill');
        if (!fill) return;
        const value = Number(fill.dataset.progress) || 0;
        fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    }

    function createResultItem(id, result) {
        const status = String(result.status ?? '');
        const pending = status === '测试中...' || status === '测试中';
        const success = status === '成功';
        const timeout = status.includes('超时');
        const progress = Math.max(0, Math.min(100, Number(result.progress) || 0));
        const elapsed = Number(result.elapsed_time) || 0;
        const currentMbps = Number(result.current_speed_mbps) || 0;
        const currentMBs = Number(result.current_speed_mbs) || 0;
        const downloaded = Number(result.downloaded_size) || 0;

        let statusClass = 'status-error';
        let statusText = '失败';
        if (pending) {
            statusClass = 'status-pending';
            statusText = '测试中';
        } else if (success) {
            statusClass = 'status-success';
            statusText = '成功';
        } else if (timeout) {
            statusClass = 'status-timeout';
            statusText = '超时';
        }

        let body = '';
        if (pending) {
            body = `
                <div class="progress-container">
                    <div class="progress-header">
                        <span>下载进度</span>
                        <span>${progress.toFixed(1)}%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" data-progress="${progress}"></div>
                    </div>
                    <div class="progress-stats">
                        <div class="stat-item">
                            <div>已耗时</div>
                            <div class="stat-value-small">${elapsed.toFixed(1)}s</div>
                        </div>
                        <div class="stat-item">
                            <div>实时速度</div>
                            <div class="stat-value-small">${currentMbps.toFixed(2)} Mbps</div>
                        </div>
                        <div class="stat-item">
                            <div>实时速度</div>
                            <div class="stat-value-small">${currentMBs.toFixed(2)} MB/s</div>
                        </div>
                    </div>
                </div>`;
        } else if (success) {
            body = `
                <div class="result-details">
                    <div class="result-detail">
                        <div class="detail-label">下载时间</div>
                        <div class="detail-value">${(Number(result.time) || 0).toFixed(2)}s</div>
                    </div>
                    <div class="result-detail">
                        <div class="detail-label">下载速度</div>
                        <div class="detail-value speed-value">
                            ${(Number(result.speed_mbps) || 0).toFixed(2)} Mbps<br>
                            ${(Number(result.speed_mbs) || 0).toFixed(2)} MB/s
                        </div>
                    </div>
                </div>`;
        }

        const downloadedHtml = downloaded > 0
            ? `<div class="download-size">已下载大小: ${formatFileSize(downloaded)}${
                result.sampled ? `（前 ${(Number(result.time) || 0).toFixed(1)} 秒采样）` : ''
            }</div>`
            : '';
        const errorHtml = !pending && !success
            ? `<div class="result-error">${escapeHtml(status)}</div>`
            : '';

        return `
            <div class="result-item" id="result_${escapeHtml(id)}">
                <div class="result-header">
                    <div class="result-name">${escapeHtml(result.name || id)}</div>
                    <div class="result-status ${statusClass}">${escapeHtml(statusText)}</div>
                </div>
                ${downloadedHtml}
                ${body}
                ${errorHtml}
            </div>`;
    }

    function renderCalculation(text) {
        el.calculationContent.textContent = '';
        const lines = String(text || '').split('\n').map((line) => line.trim()).filter(Boolean);
        if (!lines.length) {
            const line = document.createElement('div');
            line.className = 'calculation-line';
            line.textContent = '暂无有效测试结果';
            el.calculationContent.appendChild(line);
            return;
        }
        lines.forEach((textLine) => {
            const line = document.createElement('div');
            line.className = 'calculation-line';
            if (textLine.includes('平均下载速度') || textLine.includes('最终平均')) {
                line.classList.add('highlight');
            }
            line.textContent = textLine;
            el.calculationContent.appendChild(line);
        });
        el.calculationRow.scrollTop = el.calculationRow.scrollHeight;
    }

    function updateProgress() {
        const total = state.totalSelected || 0;
        const completed = Math.min(state.stats.completed, total || state.stats.completed);
        const percent = total > 0 ? Math.min(100, (completed / total) * 100) : 0;
        el.totalProgressFill.style.width = `${percent}%`;
        el.totalProgressPercent.textContent = `${percent.toFixed(1)}%`;
        el.totalCompleted.textContent = String(state.stats.completed);
        el.totalSuccess.textContent = String(state.stats.success);
        el.totalFailed.textContent = String(state.stats.failed);
        el.totalSources.textContent = String(total || state.stats.completed);
        el.totalProgressRow.classList.remove('hidden');
        if (!state.isTesting && total > 0 && state.stats.completed >= total) {
            el.totalProgressFill.classList.add('complete');
        }
    }

    function updateElapsed() {
        if (!state.isTesting || !state.testStartTime) return;
        el.totalTimeValue.textContent = `${((Date.now() - state.testStartTime) / 1000).toFixed(2)}秒`;
    }

    // -------------------------------------------------------------- 图表

    function addChartPoint(id, result) {
        if (!(Number(result.speed_mbps) > 0)) return;
        if (state.chartData.some((item) => item.id === id)) return;
        state.chartData.push({
            id,
            name: String(result.name || id),
            speedMbps: Number(result.speed_mbps),
        });
    }

    function updateChart() {
        if (!state.chartData.length) {
            el.chartRow.classList.add('hidden');
            return;
        }
        el.chartRow.classList.remove('hidden');
        if (typeof Chart === 'undefined') {
            if (!state.chartUnavailable) {
                state.chartUnavailable = true;
                notify('图表库加载失败，速度数据仍可查看', 'error');
            }
            return;
        }

        const labels = state.chartData.map((item) => item.name);
        const data = state.chartData.map((item) => item.speedMbps);
        const avg = data.reduce((sum, value) => sum + value, 0) / data.length;

        if (!state.chart) {
            state.chart = new Chart(el.speedChart.getContext('2d'), {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label: '下载速度 (Mbps)',
                            data,
                            borderColor: '#3b82f6',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            borderWidth: 2,
                            pointBackgroundColor: '#3b82f6',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            fill: true,
                            tension: 0.3,
                        },
                        {
                            label: '平均速度',
                            data: data.map(() => avg),
                            borderColor: '#10b981',
                            borderWidth: 1.5,
                            borderDash: [5, 5],
                            pointRadius: 0,
                            fill: false,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: '速度 (Mbps)', color: '#6b7280' },
                            grid: { color: 'rgba(0, 0, 0, 0.05)' },
                            ticks: { color: '#6b7280' },
                        },
                        x: {
                            title: { display: true, text: '测试源', color: '#6b7280' },
                            grid: { color: 'rgba(0, 0, 0, 0.05)' },
                            ticks: { color: '#6b7280' },
                        },
                    },
                    plugins: {
                        legend: { display: true, position: 'top', labels: { color: '#6b7280', padding: 15 } },
                        tooltip: {
                            backgroundColor: 'rgba(255, 255, 255, 0.95)',
                            titleColor: '#1f2937',
                            bodyColor: '#1f2937',
                            borderColor: '#e5e7eb',
                            borderWidth: 1,
                        },
                    },
                },
            });
        } else {
            state.chart.data.labels = labels;
            state.chart.data.datasets[0].data = data;
            state.chart.data.datasets[1].data = data.map(() => avg);
            state.chart.update();
        }
    }

    // -------------------------------------------------------------- 验证与配置

    async function startValidation(ids) {
        const target = Array.isArray(ids) && ids.length ? ids : Object.keys(state.sources);
        try {
            const data = await api('/api/validate', { method: 'POST', body: { sources: target } });
            state.validationInProgress = true;
            updateServerStatus();
            updateTestButtonState();
            startValidationPolling();
            notify(data.message || '验证已开始', 'info');
        } catch (error) {
            if (error.message.includes('正在进行')) {
                state.validationInProgress = true;
                updateServerStatus();
                startValidationPolling();
            }
            notify(error.message, 'error');
        }
    }

    function startValidationPolling() {
        if (state.validationTimer) return;
        const tick = async () => {
            state.validationTimer = null;
            try {
                const data = await api('/api/config');
                const active = Boolean(data.validation_in_progress);
                const changed = active !== state.validationInProgress;
                state.validationInProgress = active;
                if (changed) {
                    updateServerStatus();
                    updateTestButtonState();
                    if (!active) {
                        await loadSources();
                        notify('下载源验证完成', 'success');
                        // 再观察一轮：导入的源可能排在当前验证之后才启动
                        state.validationTimer = setTimeout(tick, 2000);
                        return;
                    }
                }
                if (state.validationInProgress) {
                    state.validationTimer = setTimeout(tick, 2000);
                }
            } catch (error) {
                console.error(error);
                state.validationTimer = setTimeout(tick, 4000);
            }
        };
        state.validationTimer = setTimeout(tick, 1200);
    }

    async function saveSource(event) {
        event.preventDefault();
        const id = el.sourceId.value;
        const name = el.sourceName.value.trim();
        const url = el.sourceUrl.value.trim();
        if (!name || !url) {
            notify('名称和 URL 不能为空', 'error');
            return;
        }
        const payload = { action: id ? 'update' : 'add', name, url };
        if (id) payload.id = id;
        try {
            const data = await api('/api/config/update', { method: 'POST', body: payload });
            state.sources = data.sources || state.sources;
            closeModal();
            await loadSources();
            notify(data.message || '已保存', 'success');
            if (!id && data.id) startValidation([data.id]);
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function deleteSource(id) {
        const source = state.sources[id];
        if (!source) return;
        if (!window.confirm(`确定要删除下载源“${source.name}”吗？`)) return;
        try {
            const data = await api('/api/config/update', { method: 'POST', body: { action: 'delete', id } });
            state.sources = data.sources || state.sources;
            state.selected.delete(id);
            state.userTouched.delete(id);
            await loadSources();
            notify(data.message || '下载源已删除', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    function openModal(sourceId = null) {
        if (sourceId && state.sources[sourceId]) {
            el.modalTitle.textContent = '编辑下载源';
            el.sourceId.value = sourceId;
            el.sourceName.value = state.sources[sourceId].name;
            el.sourceUrl.value = state.sources[sourceId].url;
        } else {
            el.modalTitle.textContent = '添加下载源';
            el.sourceId.value = '';
            el.sourceForm.reset();
        }
        el.sourceModal.classList.add('show');
        el.sourceName.focus();
    }

    function closeModal() {
        el.sourceModal.classList.remove('show');
        el.sourceForm.reset();
    }

    function importSources() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json,application/json';
        input.addEventListener('change', async () => {
            const file = input.files && input.files[0];
            if (!file) return;
            if (!window.confirm('导入会覆盖当前所有下载源，且需要重新验证。确定继续吗？')) return;
            try {
                const text = await file.text();
                const parsed = JSON.parse(text.replace(/^\uFEFF/, ''));
                if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                    throw new Error('JSON 顶层必须是以源 ID 为键的对象');
                }
                const data = await api('/api/config/import', {
                    method: 'POST',
                    body: JSON.stringify(parsed),
                });
                state.sources = data.sources || state.sources;
                state.selected.clear();
                state.userTouched.clear();
                state.loadedOnce = false;
                await loadSources({ fresh: true });
                notify(data.message || '导入成功', 'success');
            } catch (error) {
                notify(`导入失败：${error.message}`, 'error');
            }
        });
        input.click();
    }

    function exportSources() {
        let ids = Array.from(state.selected).filter((id) => state.sources[id]);
        if (!ids.length) ids = Object.keys(state.sources);
        if (!ids.length) {
            notify('暂无可导出的下载源', 'error');
            return;
        }
        const payload = {};
        ids.forEach((id) => {
            const source = state.sources[id];
            payload[id] = {
                name: source.name,
                url: source.url,
                size: source.size,
                enabled: source.enabled,
                valid: source.valid,
                last_validation: source.last_validation,
                last_status: source.last_status,
            };
        });

        const now = new Date();
        const stamp = [
            now.getFullYear(),
            String(now.getMonth() + 1).padStart(2, '0'),
            String(now.getDate()).padStart(2, '0'),
            '_',
            String(now.getHours()).padStart(2, '0'),
            String(now.getMinutes()).padStart(2, '0'),
            String(now.getSeconds()).padStart(2, '0'),
        ].join('');
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `chuanliu_sources_${stamp}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        notify(`已导出 ${ids.length} 个下载源`, 'success');
    }

    async function resumeRunningTest() {
        try {
            const data = await api('/api/status');
            if (!data.is_testing) return;
            state.pollEpoch += 1;
            state.isTesting = true;
            state.testId = data.test_id;
            state.testStartTime = Date.now();
            state.totalSelected = Number(data.total_count) || 0;
            el.testId.textContent = `测试ID: ${state.testId}`;
            el.testStats.classList.add('show');
            el.averageContainer.classList.add('show');
            el.totalProgressRow.classList.remove('hidden');
            updateTestResults(data);
            updateTestButtonState();
            schedulePoll(500);
            notify('已恢复正在进行的测试', 'info');
        } catch (_) {
            /* 忽略 */
        }
    }

    function attachEvents() {
        el.startTest.addEventListener('click', startTest);
        el.resetState.addEventListener('click', resetState);
        el.stopTest.addEventListener('click', stopTest);
        el.validateSources.addEventListener('click', () => startValidation());
        el.addSource.addEventListener('click', () => openModal());
        el.refreshSources.addEventListener('click', async () => {
            try {
                await loadSources();
                notify('列表已刷新', 'info');
            } catch (error) {
                notify(error.message, 'error');
            }
        });
        el.importSources.addEventListener('click', importSources);
        el.exportSources.addEventListener('click', exportSources);
        el.selectAllCheckbox.addEventListener('change', updateSelectAllHandler);
        el.closeModal.addEventListener('click', closeModal);
        el.cancelModal.addEventListener('click', closeModal);
        el.sourceForm.addEventListener('submit', saveSource);
        el.sourceModal.addEventListener('click', (event) => {
            if (event.target === el.sourceModal) closeModal();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && el.sourceModal.classList.contains('show')) closeModal();
        });

        el.sourcesList.addEventListener('change', (event) => {
            const box = event.target.closest('input[type="checkbox"][data-id]');
            if (!box) return;
            const id = box.dataset.id;
            if (box.checked) state.selected.add(id); else state.selected.delete(id);
            state.userTouched.add(id);
            updateSelectedCount();
            updateTestButtonState();
            updateSelectAll();
        });

        el.sourcesList.addEventListener('click', (event) => {
            const button = event.target.closest('button[data-action]');
            if (!button) return;
            const id = button.dataset.id;
            if (button.dataset.action === 'edit') openModal(id);
            else if (button.dataset.action === 'delete') deleteSource(id);
        });
    }

    async function init() {
        cacheDom();
        attachEvents();
        updateTestButtonState();
        try {
            await loadSources();
        } catch (error) {
            notify(error.message, 'error');
        }
        await resumeRunningTest();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
