document.addEventListener('DOMContentLoaded', () => {
    const loginSection = document.getElementById('login-section');
    const reportSection = document.getElementById('report-section');
    const usernameInput = document.getElementById('username-input');
    const passwordInput = document.getElementById('password-input');
    const loginBtn = document.getElementById('login-btn');
    const loginError = document.getElementById('login-error');
    const employeeSelect = document.getElementById('employee-select');
    const monthInput = document.getElementById('month-input');
    const cycleStartDateInput = document.getElementById('cycle-start-date-input');
    const generateReportBtn = document.getElementById('generate-report-btn');
    const reportResultDiv = document.getElementById('report-result');
    let authToken = null;
    const today = new Date();
    monthInput.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;

    const overrideEmployeeSelect = document.getElementById('override-employee-select');
    const overrideStartDateInput = document.getElementById('override-start-date-input');
    const overrideEndDateInput = document.getElementById('override-end-date-input');
    const overrideTypeSelect = document.getElementById('override-type-select');
    const saveOverrideBtn = document.getElementById('save-override-btn');
    const deleteOverrideBtn = document.getElementById('delete-override-btn');
    const overrideMessage = document.getElementById('override-message');
    const scheduleFileInput = document.getElementById('schedule-file-input');
    const uploadScheduleBtn = document.getElementById('upload-schedule-btn');
    const uploadMessage = document.getElementById('upload-message');

    function formatarMinutosParaHHMM(minutos) {
        if (minutos === null || typeof minutos === 'undefined' || minutos === 0) {
            return '00:00';
        }
        const sinal = minutos < 0 ? '-' : '';
        const absMinutos = Math.abs(minutos);
        const horas = Math.floor(absMinutos / 60);
        const minsRestantes = Math.round(absMinutos % 60);
        const horasFormatadas = String(horas).padStart(2, '0');
        const minutosFormatados = String(minsRestantes).padStart(2, '0');
        return `${sinal}${horasFormatadas}:${minutosFormatados}`;
    }

    async function handleLogin() {
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();
        if (!username || !password) {
            loginError.textContent = "Utilizador e senha são obrigatórios.";
            return;
        }
        loginBtn.disabled = true;
        loginBtn.textContent = 'Aguarde...';
        try {
            const params = new URLSearchParams();
            params.append('username', username);
            params.append('password', password);
            const response = await fetch('/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: params
            });
            if (!response.ok) throw new Error('Utilizador ou senha inválidos.');
            const data = await response.json();
            authToken = data.access_token;
            loginSection.style.display = 'none';
            reportSection.style.display = 'block';
            loadEmployees();
        } catch (error) {
            loginError.textContent = error.message;
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = 'Entrar';
        }
    }

    async function loadEmployees() {
        try {
            const response = await fetch('/employees/main', { headers: { 'Authorization': `Bearer ${authToken}` } });
            if (!response.ok) throw new Error('Falha ao carregar funcionários');
            const data = await response.json();
            const employeeOptions = data.employees.map(emp => ({ id: emp.employee_id, text: `${emp.name} (${emp.employee_id})` }));
            $(employeeSelect).select2({
                placeholder: 'Selecione um ou mais funcionários',
                data: employeeOptions
            });
            $(overrideEmployeeSelect).select2({
                placeholder: 'Selecione um funcionário',
                data: employeeOptions
            });
        } catch (error) {
            alert(`Não foi possível carregar a lista de funcionários: ${error.message}`);
        }
    }

    async function generateReport() {
        const selectedEmployees = $(employeeSelect).val();
        const [year, month] = monthInput.value.split('-').map(Number);
        const cycleStartDate = cycleStartDateInput.value;
        if (!selectedEmployees || selectedEmployees.length === 0) {
            alert('Por favor, selecione pelo menos um funcionário.');
            return;
        }
        if (!cycleStartDate) {
            alert('Por favor, informe a Data de Início do Ciclo.');
            return;
        }
        generateReportBtn.disabled = true;
        generateReportBtn.textContent = 'Gerando...';
        reportResultDiv.innerHTML = '<div class="loader"></div>';
        try {
            const response = await fetch('/report/monthly', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
                body: JSON.stringify({
                    employee_ids: selectedEmployees,
                    year: year,
                    month: month,
                    cycle_start_date: cycleStartDate
                })
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(`Erro na API: ${errorData.detail || response.statusText}`);
            }
            const result = await response.json();
            renderDetailedReport(result);
        } catch (error)
        {
            reportResultDiv.innerHTML = `<p class="error-message">Falha ao gerar o relatório: ${error.message}</p>`;
        } finally {
            generateReportBtn.disabled = false;
            generateReportBtn.textContent = 'Gerar Relatório';
        }
    }

    function renderDetailedReport(data) {
        if (!data || data.length === 0) {
            reportResultDiv.innerHTML = '<p>Nenhum dado encontrado para os filtros selecionados.</p>';
            return;
        }
        const formatTime = (timeStr) => timeStr ? timeStr.substring(0, 5) : '---';
        let reportHTML = '';

        data.forEach(employeeData => {
            reportHTML += `<div class="employee-report">
                <h2>${employeeData.employee_name} (${employeeData.employee_id})</h2>
                <h3 class="shift-description">Turno Padrão: ${employeeData.shift_description}</h3>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th rowspan="2">Data</th>
                                <th colspan="4">Batidas Sistema Principal</th>
                                <th colspan="4">Batidas Aplicativo</th>
                                <th colspan="4">Horas Calculadas</th>
                            </tr>
                            <tr>
                                <th>E1</th><th>S1</th><th>E2</th><th>S2</th>
                                <th>E1</th><th>S1</th><th>E2</th><th>S2</th>
                                <th>Normais</th>
                                <th>HE 50%</th>
                                <th>HE 100%</th>
                                <th>Faltas/Atrasos</th>
                            </tr>
                        </thead>
                        <tbody>`;
            
            employeeData.daily_breakdown.forEach(day => {
                const isSunday = new Date(day.date).getUTCDay() === 0;
                const rowClass = isSunday ? 'sunday-row' : '';
                
                let calculatedCells = '';
                const hasWorked = day.calculated_minutes.normal > 0 || day.calculated_minutes.overtime_50 > 0 || day.calculated_minutes.overtime_100 > 0;
                
                if (day.status && !hasWorked) {
                    calculatedCells = `<td colspan="4" class="status-cell">${day.status}</td>`;
                } else {
                    calculatedCells = `
                        <td>${formatarMinutosParaHHMM(day.calculated_minutes.normal)}</td>
                        <td>${formatarMinutosParaHHMM(day.calculated_minutes.overtime_50)}</td>
                        <td>${formatarMinutosParaHHMM(day.calculated_minutes.overtime_100)}</td>
                        <td>${formatarMinutosParaHHMM(day.calculated_minutes.undertime)}</td>`;
                }
                
                reportHTML += `<tr class="${rowClass}">
                    <td>${day.date}</td>
                    <td>${formatTime(day.main_system_punches.entry1)}</td>
                    <td>${formatTime(day.main_system_punches.exit1)}</td>
                    <td>${formatTime(day.main_system_punches.entry2)}</td>
                    <td>${formatTime(day.main_system_punches.exit2)}</td>
                    <td>${formatTime(day.app_punches.entry1)}</td>
                    <td>${formatTime(day.app_punches.exit1)}</td>
                    <td>${formatTime(day.app_punches.entry2)}</td>
                    <td>${formatTime(day.app_punches.exit2)}</td>
                    ${calculatedCells}
                </tr>`;
            });
            
            const totals = employeeData.totals_in_minutes;
            const saldoFinal = totals.overtime_50 + totals.overtime_100 + totals.undertime;
            
            reportHTML += `</tbody>
                <tfoot>
                    <tr>
                        <td colspan="9"><strong>TOTAIS DO MÊS</strong></td>
                        <td><strong>${formatarMinutosParaHHMM(totals.normal)}</strong></td>
                        <td><strong>${formatarMinutosParaHHMM(totals.overtime_50)}</strong></td>
                        <td><strong>${formatarMinutosParaHHMM(totals.overtime_100)}</strong></td>
                        <td><strong>${formatarMinutosParaHHMM(totals.undertime)}</strong></td>
                    </tr>
                    <tr>
                        <td colspan="10" style="text-align:right;"><strong>Resumo de Extras (50% + 100%):</strong></td>
                        <td colspan="3"><strong>${formatarMinutosParaHHMM(totals.overtime_50 + totals.overtime_100)}</strong></td>
                    </tr>
                     <tr>
                        <td colspan="10" style="text-align:right;"><strong>SALDO FINAL (EXTRAS - FALTAS):</strong></td>
                        <td colspan="3" style="font-size: 1.1em;"><strong>${formatarMinutosParaHHMM(saldoFinal)}</strong></td>
                    </tr>
                </tfoot>
            </table>
            </div></div>`;
        });
        reportResultDiv.innerHTML = reportHTML;
    }

    async function saveOverride() {
        const employee_id = $(overrideEmployeeSelect).val();
        const start_date = overrideStartDateInput.value;
        const end_date = overrideEndDateInput.value;
        const override_type = overrideTypeSelect.value;
        if (!employee_id || !start_date || !end_date || !override_type) {
            overrideMessage.textContent = 'Preencha todos os campos para salvar.';
            overrideMessage.className = 'error-message';
            return;
        }
        if (new Date(start_date) > new Date(end_date)) {
            overrideMessage.textContent = 'A data de início não pode ser depois da data de fim.';
            overrideMessage.className = 'error-message';
            return;
        }
        saveOverrideBtn.disabled = true;
        try {
            const response = await fetch('/overrides', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
                body: JSON.stringify({ employee_id, start_date, end_date, override_type, description: '' })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Erro ao salvar');
            overrideMessage.textContent = result.message;
            overrideMessage.className = 'success-message';
        } catch(error) {
            overrideMessage.textContent = `Erro: ${error.message}`;
            overrideMessage.className = 'error-message';
        } finally {
            saveOverrideBtn.disabled = false;
        }
    }

    async function deleteOverride() {
        const employee_id = $(overrideEmployeeSelect).val();
        const start_date = overrideStartDateInput.value;
        const end_date = overrideEndDateInput.value;
        if (!employee_id || !start_date || !end_date) {
            overrideMessage.textContent = 'Selecione funcionário e o período para remover.';
            overrideMessage.className = 'error-message';
            return;
        }
        if (!confirm(`Tem certeza que deseja remover os ajustes manuais para ${employee_id} entre ${start_date} e ${end_date}?`)) return;
        deleteOverrideBtn.disabled = true;
        try {
            const response = await fetch('/overrides', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${authToken}` },
                body: JSON.stringify({ employee_id, start_date, end_date, override_type: "placeholder" })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Erro ao remover');
            overrideMessage.textContent = result.message;
            overrideMessage.className = 'success-message';
        } catch(error) {
            overrideMessage.textContent = `Erro: ${error.message}`;
            overrideMessage.className = 'error-message';
        } finally {
            deleteOverrideBtn.disabled = false;
        }
    }
    
    async function uploadSchedule() {
        const file = scheduleFileInput.files[0];
        if (!file) {
            uploadMessage.textContent = 'Por favor, selecione um arquivo.';
            uploadMessage.className = 'error-message';
            return;
        }
        const formData = new FormData();
        formData.append('file', file);
        uploadScheduleBtn.disabled = true;
        uploadScheduleBtn.textContent = 'Importando...';
        uploadMessage.textContent = '';
        try {
            const response = await fetch('/schedules/upload', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${authToken}` },
                body: formData
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Erro no servidor');
            uploadMessage.textContent = result.message;
            uploadMessage.className = 'success-message';
            scheduleFileInput.value = '';
        } catch (error) {
            uploadMessage.textContent = `Erro: ${error.message}`;
            uploadMessage.className = 'error-message';
        } finally {
            uploadScheduleBtn.disabled = false;
            uploadScheduleBtn.textContent = 'Importar Escala';
        }
    }

    loginBtn.addEventListener('click', handleLogin);
    generateReportBtn.addEventListener('click', generateReport);
    saveOverrideBtn.addEventListener('click', saveOverride);
    deleteOverrideBtn.addEventListener('click', deleteOverride);
    uploadScheduleBtn.addEventListener('click', uploadSchedule);
});