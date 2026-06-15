/**
 * StopList Tool — Frontend JavaScript
 */

let pollInterval = null;

// При завантаженні сторінки імпорту — перевіряємо чи вже щось працює
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('progressCard')) {
        fetch('/api/import/progress')
        .then(r => r.json())
        .then(data => {
            if (data.running) {
                showProgress();
                startPolling();
            } else if (data.processed > 0 && data.total > 0) {
                showProgress();
                updateProgressUI(data);
                onImportComplete(data);
            }
        })
        .catch(() => {});
    }
});

// ============ ІМПОРТ: URL ============

function startImportUrls() {
    const textarea = document.getElementById('urlsInput');
    const isMaster = document.getElementById('isMaster').checked;
    const text = textarea.value.trim();

    if (!text) {
        alert('Вставте хоча б одне посилання!');
        return;
    }

    const urls = text.split('\n').map(u => u.trim()).filter(u => u.length > 0);

    fetch('/api/import/urls', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({urls: urls, is_master: isMaster})
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        showProgress();
        startPolling();
    })
    .catch(err => alert('Помилка: ' + err));
}

// ============ ІМПОРТ: ФАЙЛИ ============

function startImportFiles() {
    const input = document.getElementById('fileInput');
    if (!input.files.length) {
        alert('Виберіть хоча б один файл!');
        return;
    }

    const formData = new FormData();
    for (const file of input.files) {
        formData.append('files', file);
    }

    fetch('/api/import/files', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        showProgress();
        startPolling();
    })
    .catch(err => alert('Помилка: ' + err));
}

// ============ ПРОГРЕС ============

function showProgress() {
    const card = document.getElementById('progressCard');
    if (card) {
        card.classList.remove('d-none');
        document.getElementById('resultBlock').classList.add('d-none');
    }
    // Відключаємо кнопки
    const btns = document.querySelectorAll('#btnImportUrls, #btnImportFiles');
    btns.forEach(b => b.disabled = true);
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollProgress, 1500);
}

function pollProgress() {
    fetch('/api/import/progress')
    .then(r => r.json())
    .then(data => {
        updateProgressUI(data);
        if (!data.running) {
            clearInterval(pollInterval);
            pollInterval = null;
            onImportComplete(data);
        }
    })
    .catch(() => {});
}

function updateProgressUI(data) {
    const bar = document.getElementById('progressBar');
    const text = document.getElementById('progressText');
    const current = document.getElementById('progressCurrent');

    if (!bar) return;

    const pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;
    bar.style.width = pct + '%';
    bar.textContent = pct + '%';

    text.textContent = `Оброблено: ${data.processed} з ${data.total}`;
    current.textContent = data.current_item || '';

    // Помилки
    if (data.total_errors > 0) {
        document.getElementById('errorsBlock').classList.remove('d-none');
        document.getElementById('errorsCount').textContent = data.total_errors;
        const container = document.getElementById('errorsContent');
        container.innerHTML = data.errors.map(e =>
            `<div class="error-line text-danger">${escapeHtml(e)}</div>`
        ).join('');
    }

    // Недоступні таблиці
    if (data.total_failed > 0) {
        document.getElementById('failedBlock').classList.remove('d-none');
        document.getElementById('failedCount').textContent = data.total_failed;
        const list = document.getElementById('failedList');
        list.innerHTML = data.failed_urls.map(f => `
            <div class="d-flex justify-content-between align-items-center border-bottom py-1">
                <code class="small text-break me-2">${escapeHtml(f.url)}</code>
                <span class="badge bg-danger text-nowrap">${escapeHtml(f.reason)}</span>
            </div>
        `).join('');
    }
}

function onImportComplete(data) {
    const btns = document.querySelectorAll('#btnImportUrls, #btnImportFiles');
    btns.forEach(b => b.disabled = false);
    document.getElementById('btnCancel').classList.add('d-none');

    const bar = document.getElementById('progressBar');
    bar.classList.remove('progress-bar-animated');

    if (data.stats && Object.keys(data.stats).length > 0) {
        const result = document.getElementById('resultBlock');
        result.classList.remove('d-none');
        document.getElementById('resultStats').innerHTML = `
            <p class="mb-1">Акцепторів: <strong>${data.stats.total_acceptors}</strong></p>
            <p class="mb-1">Унікальних донорів: <strong>${data.stats.total_unique_donors}</strong></p>
            <p class="mb-1">Унікальних пар: <strong>${data.stats.total_unique_pairs}</strong></p>
            <p class="mb-1">Оброблено ТЗ: <strong>${data.stats.total_tz_done}</strong></p>
            ${data.total_failed > 0 ? `<p class="mb-1 text-warning"><i class="bi bi-lock-fill"></i> Недоступних таблиць: <strong>${data.total_failed}</strong> (див. список нижче)</p>` : ''}
            ${data.total_errors > 0 ? `<p class="mb-0 text-danger">Всього помилок: <strong>${data.total_errors}</strong></p>` : ''}
        `;
    }
}

function cancelImport() {
    if (!confirm('Скасувати імпорт?')) return;
    fetch('/api/import/cancel', {method: 'POST'})
    .then(r => r.json())
    .then(() => {});
}

function copyFailedUrls() {
    // Збираємо URL з DOM
    const items = document.querySelectorAll('#failedList code');
    const urls = Array.from(items).map(el => el.textContent).join('\n');
    navigator.clipboard.writeText(urls).then(() => {
        const btn = document.querySelector('#failedBlock .btn-outline-dark');
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check"></i> Скопійовано!';
        setTimeout(() => btn.innerHTML = orig, 2000);
    });
}

// ============ СТОП-ЛИСТ ============

let currentAcceptorPage = 1;

function loadAcceptors(page) {
    currentAcceptorPage = page;
    const search = document.getElementById('searchInput')?.value || '';
    const sortBy = document.getElementById('sortBy')?.value || 'unique_donors';
    const sortDir = document.getElementById('sortDir')?.value || 'desc';

    fetch(`/api/stoplist/acceptors?page=${page}&search=${encodeURIComponent(search)}&sort_by=${sortBy}&sort_dir=${sortDir}`)
    .then(r => r.json())
    .then(data => {
        renderAcceptorsTable(data);
        renderPagination(data, 'pagination', loadAcceptors);
        if (data.total_pages > 0) {
            document.getElementById('paginationNav').classList.remove('d-none');
        }
    })
    .catch(() => {});
}

function renderAcceptorsTable(data) {
    const tbody = document.getElementById('acceptorsBody');
    if (!tbody) return;

    if (!data.rows || data.rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Немає даних. Імпортуйте ТЗ.</td></tr>';
        return;
    }

    const offset = (data.page - 1) * data.per_page;
    tbody.innerHTML = data.rows.map((r, i) => `
        <tr>
            <td class="text-muted">${offset + i + 1}</td>
            <td><strong>${escapeHtml(r.acceptor)}</strong></td>
            <td>${r.unique_donors.toLocaleString()}</td>
            <td>${r.total_entries.toLocaleString()}</td>
            <td>${r.duplicates > 0 ? '<span class="text-danger">' + r.duplicates.toLocaleString() + '</span>' : '0'}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="showDonors('${escapeHtml(r.acceptor)}')">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function showDonors(acceptor, page = 1) {
    document.getElementById('modalAcceptor').textContent = acceptor;

    fetch(`/api/stoplist/donors?acceptor=${encodeURIComponent(acceptor)}&page=${page}&per_page=200`)
    .then(r => r.json())
    .then(data => {
        document.getElementById('modalTotal').textContent = data.total.toLocaleString();

        const list = document.getElementById('donorsList');
        list.innerHTML = data.donors.map(d =>
            `<div class="donor-item">${escapeHtml(d)}</div>`
        ).join('');

        renderPagination(data, 'donorsPagination', (p) => showDonors(acceptor, p));

        const modal = new bootstrap.Modal(document.getElementById('donorsModal'));
        modal.show();
    });
}

function renderPagination(data, containerId, callback) {
    const container = document.getElementById(containerId);
    if (!container || data.total_pages <= 1) {
        if (container) container.innerHTML = '';
        return;
    }

    let html = '';
    const page = data.page;
    const total = data.total_pages;

    // Попередня
    html += `<li class="page-item ${page <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="event.preventDefault(); ${callback.name}(${page-1})">«</a></li>`;

    // Сторінки
    let start = Math.max(1, page - 3);
    let end = Math.min(total, page + 3);

    if (start > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="event.preventDefault(); ${callback.name}(1)">1</a></li>`;
        if (start > 2) html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
    }

    for (let i = start; i <= end; i++) {
        html += `<li class="page-item ${i === page ? 'active' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault(); ${callback.name}(${i})">${i}</a></li>`;
    }

    if (end < total) {
        if (end < total - 1) html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        html += `<li class="page-item"><a class="page-link" href="#" onclick="event.preventDefault(); ${callback.name}(${total})">${total}</a></li>`;
    }

    // Наступна
    html += `<li class="page-item ${page >= total ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="event.preventDefault(); ${callback.name}(${page+1})">»</a></li>`;

    container.innerHTML = html;
}

// ============ СТАТИСТИКА ============

function loadStats() {
    // Глобальна статистика
    fetch('/api/stats/global')
    .then(r => r.json())
    .then(data => {
        const el = document.getElementById('globalStats');
        if (!el) return;
        el.innerHTML = `
            <div class="col"><span class="fs-4 text-primary">${data.total_acceptors.toLocaleString()}</span><br><small class="text-muted">Акцепторів</small></div>
            <div class="col"><span class="fs-4 text-success">${data.total_unique_donors.toLocaleString()}</span><br><small class="text-muted">Унік. донорів</small></div>
            <div class="col"><span class="fs-4 text-info">${data.total_unique_pairs.toLocaleString()}</span><br><small class="text-muted">Унік. пар</small></div>
            <div class="col"><span class="fs-4 text-warning">${data.total_raw_records.toLocaleString()}</span><br><small class="text-muted">Всього записів</small></div>
            <div class="col"><span class="fs-4 text-danger">${data.total_duplicates.toLocaleString()}</span><br><small class="text-muted">Дублікатів</small></div>
        `;
    });

    // ТЗ таблиці
    fetch('/api/stats/tz')
    .then(r => r.json())
    .then(data => {
        document.getElementById('tzCount').textContent = data.length;
        const tbody = document.getElementById('tzTableBody');
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Немає оброблених ТЗ</td></tr>';
            return;
        }
        tbody.innerHTML = data.map((t, i) => `
            <tr>
                <td>${i + 1}</td>
                <td class="text-truncate" style="max-width: 250px;" title="${escapeHtml(t.name)}">
                    ${escapeHtml(t.name)}
                </td>
                <td>
                    ${t.status === 'done' ? '<span class="badge bg-success">Готово</span>' :
                      t.status === 'error' ? '<span class="badge bg-danger" title="' + escapeHtml(t.error_message || '') + '">Помилка</span>' :
                      '<span class="badge bg-warning">В обробці</span>'}
                </td>
                <td>${t.total_rows || 0}</td>
                <td>${t.unique_acceptors || 0}</td>
                <td>${t.unique_donors || 0}</td>
                <td class="small">${t.processed_at ? new Date(t.processed_at).toLocaleString('uk-UA') : '—'}</td>
                <td>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteTz(${t.id})" title="Видалити">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    });

    // Топ-20 акцепторів
    fetch('/api/stoplist/acceptors?page=1&per_page=20&sort_by=unique_donors&sort_dir=desc')
    .then(r => r.json())
    .then(data => {
        const tbody = document.getElementById('topAcceptorsBody');
        if (!data.rows || data.rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Немає даних</td></tr>';
            return;
        }
        tbody.innerHTML = data.rows.map((r, i) => `
            <tr>
                <td>${i + 1}</td>
                <td><strong>${escapeHtml(r.acceptor)}</strong></td>
                <td>${r.unique_donors.toLocaleString()}</td>
                <td>${r.total_entries.toLocaleString()}</td>
                <td>${r.duplicates > 0 ? '<span class="text-danger">' + r.duplicates.toLocaleString() + '</span>' : '0'}</td>
            </tr>
        `).join('');
    });
}

function deleteTz(id) {
    if (!confirm('Видалити це ТЗ та всі його записи зі стоп-листа?')) return;
    fetch(`/api/tz/${id}/delete`, {method: 'POST'})
    .then(r => r.json())
    .then(() => loadStats());
}

function clearAllData() {
    if (!confirm('Ви впевнені? Це видалить ВСІ дані стоп-листа!')) return;
    if (!confirm('Точно видалити? Цю дію не можна скасувати.')) return;

    fetch('/api/clear', {method: 'POST'})
    .then(r => r.json())
    .then(() => {
        alert('Всі дані видалено.');
        loadStats();
    });
}

// ============ ЕКСПОРТ ============

function setExportButtonsDisabled(disabled) {
    const btn = document.getElementById('btnExport');
    if (btn) btn.disabled = disabled;
    const btnSel = document.getElementById('btnExportSelected');
    if (btnSel) {
        if (disabled) {
            btnSel.disabled = true;
        } else {
            // Після завершення вмикаємо лише якщо є вибрані сесії
            const anyChecked = document.querySelectorAll('#sessionsList input[type="checkbox"]:checked').length > 0;
            btnSel.disabled = !anyChecked;
        }
    }
}

function startExport(sessionIds) {
    setExportButtonsDisabled(true);

    const body = sessionIds && sessionIds.length ? JSON.stringify({session_ids: sessionIds}) : null;
    fetch('/api/export/start', {
        method: 'POST',
        headers: body ? {'Content-Type': 'application/json'} : {},
        body: body
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            setExportButtonsDisabled(false);
            return;
        }
        document.getElementById('exportProgressCard').classList.remove('d-none');
        const progressTitle = document.getElementById('exportProgressTitle');
        if (progressTitle) {
            progressTitle.innerHTML = sessionIds && sessionIds.length
                ? '<i class="bi bi-hourglass-split"></i> Експорт вибраних сесій...'
                : '<i class="bi bi-hourglass-split"></i> Експорт повного стоп-листа...';
        }
        const bar = document.getElementById('exportProgressBar');
        if (bar) {
            bar.classList.add('progress-bar-animated');
            bar.style.width = '0%';
            bar.textContent = '0%';
        }
        pollExport();
    })
    .catch(err => {
        alert('Помилка: ' + err);
        setExportButtonsDisabled(false);
    });
}

function startSelectedExport() {
    const checks = document.querySelectorAll('#sessionsList input[type="checkbox"]:checked');
    const ids = Array.from(checks).map(c => c.value);
    if (!ids.length) {
        alert('Обери хоча б одну імпорт-сесію.');
        return;
    }
    startExport(ids);
}

function pollExport() {
    const interval = setInterval(() => {
        fetch('/api/import/progress')
        .then(r => r.json())
        .then(data => {
            const bar = document.getElementById('exportProgressBar');
            const text = document.getElementById('exportProgressText');
            if (!bar) return;

            const pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;
            bar.style.width = pct + '%';
            bar.textContent = pct + '%';
            text.textContent = `Оброблено: ${data.processed.toLocaleString()} з ${data.total.toLocaleString()}`;

            if (!data.running) {
                clearInterval(interval);
                bar.classList.remove('progress-bar-animated');
                setExportButtonsDisabled(false);

                // Показуємо файли для завантаження
                if (data.completed_files && data.completed_files.length > 0) {
                    const card = document.getElementById('downloadCard');
                    card.classList.remove('d-none');
                    document.getElementById('downloadList').innerHTML = data.completed_files.map(f => `
                        <a href="/api/export/download/${f}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                            <span><i class="bi bi-file-earmark-excel text-success"></i> ${f}</span>
                            <span class="badge bg-success"><i class="bi bi-download"></i> Завантажити</span>
                        </a>
                    `).join('');
                }
            }
        });
    }, 2000);
}

function loadExportSessions() {
    const container = document.getElementById('sessionsList');
    if (!container) return;

    fetch('/api/export/sessions')
    .then(r => r.json())
    .then(sessions => {
        if (!sessions.length) {
            container.innerHTML = '<div class="text-muted small p-2">Імпорт-сесій поки немає. Зроби імпорт ТЗ — і він з\'явиться тут.</div>';
            return;
        }
        container.innerHTML = sessions.map(s => {
            const isLegacy = s.session_id === '__legacy__';
            const label = isLegacy
                ? 'Архівні імпорти (до оновлення)'
                : `Імпорт ${formatSessionDate(s.started_at)}`;
            const subtitle = `${s.tz_count} ТЗ · ${(s.total_rows || 0).toLocaleString()} рядків · ${s.sum_acceptors || 0} акцепторів`;
            const idAttr = `sess_${escapeAttr(s.session_id)}`;
            return `
                <label class="list-group-item d-flex align-items-center" for="${idAttr}" style="cursor: pointer;">
                    <input type="checkbox" class="form-check-input me-3" id="${idAttr}" value="${escapeAttr(s.session_id)}" onchange="onSessionToggle()">
                    <div class="flex-grow-1">
                        <div><strong>${escapeHtml(label)}</strong></div>
                        <div class="text-muted small">${escapeHtml(subtitle)}</div>
                    </div>
                </label>
            `;
        }).join('');
    })
    .catch(err => {
        container.innerHTML = `<div class="alert alert-warning small">Не вдалося завантажити сесії: ${escapeHtml(String(err))}</div>`;
    });
}

function onSessionToggle() {
    const btn = document.getElementById('btnExportSelected');
    if (!btn) return;
    const anyChecked = document.querySelectorAll('#sessionsList input[type="checkbox"]:checked').length > 0;
    btn.disabled = !anyChecked;
}

function formatSessionDate(isoString) {
    if (!isoString) return '—';
    // Очікуємо рядок з SQLite типу '2026-05-12 15:30:42' або ISO.
    const s = isoString.replace(' ', 'T');
    const d = new Date(s);
    if (isNaN(d.getTime())) return isoString;
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yyyy = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${dd}.${mm}.${yyyy} ${hh}:${mi}`;
}

function escapeAttr(str) {
    if (str == null) return '';
    return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============ УТИЛІТИ ============

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============ АВТОІНІЦІАЛІЗАЦІЯ ============

// На сторінці /export автоматично підвантажуємо список імпорт-сесій.
(function () {
    function initExportPage() {
        if (document.getElementById('sessionsList')) {
            loadExportSessions();
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExportPage);
    } else {
        initExportPage();
    }
})();
